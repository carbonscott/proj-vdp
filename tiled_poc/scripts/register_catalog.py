#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "tiled[server]",
#     "pandas",
#     "pyarrow",
#     "h5py",
#     "numpy",
#     "ruamel.yaml",
# ]
# ///
"""
Generic Unified Dual-Mode Registration.

Registers Hamiltonians with BOTH:
- Artifact locators in container metadata (for expert path-based access)
- Array children via DataSource adapters (for visualization/chunked access)

Dataset-agnostic: reads all metadata columns dynamically from manifests.
The manifest is the contract -- no hardcoded parameter names or artifact types.

Usage:
    # Start the Tiled server first:
    #   tiled serve config config.yml --api-key secret
    #
    # Then run this script:
    python register_catalog.py

    # Register more Hamiltonians:
    VDP_MAX_HAMILTONIANS=1000 python register_catalog.py
"""

import os
import sys
import time
from pathlib import Path

# Add tiled_poc directory to path for broker package imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import h5py
import numpy as np
import pandas as pd

from broker.config import (
    get_base_dir,
    get_latest_manifest,
    get_tiled_url,
    get_api_key,
    get_max_hamiltonians,
    get_service_dir,
)
from broker.utils import check_server, make_artifact_key


# Standard columns in the artifact manifest that are NOT stored as metadata.
ARTIFACT_STANDARD_COLS = {"huid", "type", "file", "dataset", "index"}


def _to_json_safe(value):
    """Convert a value to a JSON-serializable type."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    if pd.isna(value):
        return None
    return value


def _get_artifact_shape(base_dir, file_path, dataset_path, index=None, _cache={}):
    """Read artifact shape from HDF5, with caching by dataset path."""
    if dataset_path not in _cache:
        full_path = os.path.join(base_dir, file_path)
        with h5py.File(full_path, "r") as f:
            _cache[dataset_path] = f[dataset_path].shape
    full_shape = _cache[dataset_path]
    if index is not None:
        return tuple(full_shape[1:])
    return tuple(full_shape)


def load_manifests():
    """Load Hamiltonian and Artifact manifests."""
    base_dir = get_base_dir()
    print(f"Loading manifests from {base_dir}...")

    ham_path = get_latest_manifest("hamiltonians")
    art_path = get_latest_manifest("artifacts")

    print(f"  Hamiltonians: {Path(ham_path).name}")
    print(f"  Artifacts:    {Path(art_path).name}")

    ham_df = pd.read_parquet(ham_path)
    art_df = pd.read_parquet(art_path)

    print(f"  Rows: {len(ham_df)} Hamiltonians, {len(art_df)} artifacts")

    return ham_df, art_df


def create_data_source(art_row, base_dir=None):
    """Create a DataSource for an artifact pointing to external HDF5.

    Reads dataset path and shape from the manifest and HDF5 file directly.
    No hardcoded artifact types or shapes.
    """
    from tiled.structures.core import StructureFamily
    from tiled.structures.array import ArrayStructure
    from tiled.structures.data_source import Asset, DataSource, Management

    if base_dir is None:
        base_dir = get_base_dir()

    h5_rel_path = art_row["file"]
    h5_full_path = os.path.join(base_dir, h5_rel_path)
    dataset_path = art_row["dataset"]

    # Determine index for batched files
    index = None
    if "index" in art_row.index and pd.notna(art_row.get("index")):
        index = int(art_row["index"])

    # Get shape from HDF5 (cached by dataset path)
    data_shape = _get_artifact_shape(base_dir, h5_rel_path, dataset_path, index)
    data_dtype = np.float64

    # Create asset pointing to HDF5 file
    asset = Asset(
        data_uri=f"file://localhost{h5_full_path}",
        is_directory=False,
        parameter="data_uris",
    )

    # Create array structure
    structure = ArrayStructure.from_array(
        np.empty(data_shape, dtype=data_dtype)
    )

    # Build parameters
    ds_params = {"dataset": dataset_path}
    if index is not None:
        ds_params["index"] = index

    # Create data source
    data_source = DataSource(
        mimetype="application/x-hdf5",
        assets=[asset],
        structure_family=StructureFamily.array,
        structure=structure,
        parameters=ds_params,
        management=Management.external,
    )

    return data_source, data_shape, data_dtype


def register_unified_catalog(client, ham_df, art_df):
    """Register Hamiltonians with BOTH locators AND array adapters.

    Unified dual-mode: combines path-based metadata (Mode A) with
    array children via adapters (Mode B).

    All metadata columns are read dynamically from the manifests.
    """
    from tiled.structures.core import StructureFamily

    base_dir = get_base_dir()
    max_hamiltonians = get_max_hamiltonians()

    start_time = time.time()
    ham_count = 0
    art_count = 0
    skip_count = 0

    # Pre-group artifacts by huid for O(1) lookup
    print("Pre-grouping artifacts by huid...")
    art_grouped = art_df.groupby("huid")

    # Limit Hamiltonians
    ham_subset = ham_df.head(max_hamiltonians)
    print(f"Registering {len(ham_subset)} Hamiltonians (unified: locators + adapters)...")

    for i, (_, ham_row) in enumerate(ham_subset.iterrows()):
        huid = str(ham_row["huid"])
        h_key = f"H_{huid[:8]}"

        # Skip if container already exists
        if h_key in client:
            skip_count += 1
            continue

        # Build metadata dynamically from ALL manifest columns
        metadata = {}
        for col in ham_df.columns:
            metadata[col] = _to_json_safe(ham_row[col])

        # Attach artifact locators to metadata (for Mode A access)
        artifacts = None
        if huid in art_grouped.groups:
            artifacts = art_grouped.get_group(huid)
            for _, art_row in artifacts.iterrows():
                art_key = make_artifact_key(art_row)
                metadata[f"path_{art_key}"] = art_row["file"]
                metadata[f"dataset_{art_key}"] = art_row["dataset"]
                if "index" in art_row.index and pd.notna(art_row.get("index")):
                    metadata[f"index_{art_key}"] = int(art_row["index"])

        # Create container with all metadata
        h_container = client.create_container(key=h_key, metadata=metadata)
        ham_count += 1

        # Register arrays as children (Mode B)
        if artifacts is not None:
            for _, art_row in artifacts.iterrows():
                try:
                    art_key = make_artifact_key(art_row)

                    # Create data source pointing to external HDF5
                    data_source, data_shape, data_dtype = create_data_source(
                        art_row, base_dir=base_dir
                    )

                    # Build artifact metadata dynamically from non-standard columns
                    art_metadata = {
                        "type": art_row["type"],
                        "shape": list(data_shape),
                        "dtype": str(data_dtype),
                    }
                    for col in art_df.columns:
                        if col not in ARTIFACT_STANDARD_COLS:
                            art_metadata[col] = _to_json_safe(art_row[col])

                    # Register artifact as child of container
                    h_container.new(
                        structure_family=StructureFamily.array,
                        data_sources=[data_source],
                        key=art_key,
                        metadata=art_metadata,
                    )
                    art_count += 1

                except Exception as e:
                    print(f"  ERROR registering artifact {art_key}: {e}")

        # Progress update
        if (i + 1) % 5 == 0 or (i + 1) == len(ham_subset):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  Progress: {i+1}/{len(ham_subset)} Hamiltonians ({rate:.1f}/sec)")

    elapsed_total = time.time() - start_time
    print(f"\nRegistration complete:")
    print(f"  Hamiltonians: {ham_count}")
    print(f"  Artifacts:    {art_count}")
    print(f"  Skipped:      {skip_count}")
    print(f"  Time:         {elapsed_total:.1f} seconds")

    return ham_count > 0


def verify_registration(client):
    """Verify unified registration worked correctly."""
    print("\n" + "=" * 50)
    print("Verification")
    print("=" * 50)

    # Check total containers
    total = len(client)
    print(f"Total Hamiltonian containers: {total}")

    if total == 0:
        print("No containers registered yet.")
        return

    # List first few container keys
    keys = list(client.keys())[:3]
    print(f"First 3 container keys: {keys}")

    # Inspect first container
    if keys:
        h_key = keys[0]
        h = client[h_key]
        meta = dict(h.metadata)

        print(f"\nContainer '{h_key}':")

        # Show metadata keys (generic -- no hardcoded param names)
        param_keys = [k for k in meta if not k.startswith(("path_", "dataset_", "index_"))]
        print(f"  Metadata keys: {param_keys}")

        # Check locators in metadata
        path_keys = [k for k in meta if k.startswith("path_")]
        dataset_keys = [k for k in meta if k.startswith("dataset_")]
        index_keys = [k for k in meta if k.startswith("index_")]
        print(f"\n  Locators in metadata:")
        print(f"    path_*:    {len(path_keys)}")
        print(f"    dataset_*: {len(dataset_keys)}")
        print(f"    index_*:   {len(index_keys)}")
        for pk in path_keys[:3]:
            val = meta[pk]
            if isinstance(val, str) and len(val) > 50:
                val = "..." + val[-47:]
            print(f"    {pk}: {val}")

        # Check array children
        children = list(h.keys())
        print(f"\n  Array children: {len(children)}")
        if children:
            print(f"    {children[:5]}")
            if len(children) > 5:
                print(f"    ... and {len(children) - 5} more")

            # Check one child
            child_key = children[0]
            child = h[child_key]
            print(f"\n  Sample child '{child_key}':")
            print(f"    Shape: {child.shape}")
            print(f"    Dtype: {child.dtype}")

        # Dual-mode verification
        if path_keys and children:
            print("\n  VERIFIED: Both locators AND array children present!")
            print("  Users can choose either access mode.")
        else:
            print("\n  WARNING: Dual-mode incomplete!")
            if not path_keys:
                print("    Missing: path_* metadata")
            if not children:
                print("    Missing: array children")


def main():
    tiled_url = get_tiled_url()
    max_hamiltonians = get_max_hamiltonians()

    print("=" * 60)
    print("Generic Unified Dual-Mode Registration")
    print("=" * 60)
    print(f"Base dir:         {get_base_dir()}")
    print(f"Tiled URL:        {tiled_url}")
    print(f"Max Hamiltonians: {max_hamiltonians}")
    print()
    print("Registers BOTH:")
    print("  - Locator fields in metadata (expert path-based access)")
    print("  - Array children via adapters (visualization chunked access)")

    # Check server
    print("\nChecking Tiled server...")
    if not check_server():
        service_dir = get_service_dir()
        print("ERROR: Tiled server not running!")
        print("\nStart the server first:")
        print(f"  uv run --with 'tiled[server]' tiled serve config {service_dir}/config.yml --api-key secret")
        sys.exit(1)
    print("Server is running")

    # Load manifests
    ham_df, art_df = load_manifests()

    # Import tiled here (after server check)
    from tiled.client import from_uri
    client = from_uri(tiled_url, api_key=get_api_key())
    print(f"Current catalog containers: {len(client)}")

    # Register unified catalog
    if not register_unified_catalog(client, ham_df, art_df):
        print("\nERROR: Registration failed")
        sys.exit(1)

    # Verify
    verify_registration(client)

    print("\n" + "=" * 60)
    print("Done! Catalog ready for dual-mode access.")
    print("=" * 60)


if __name__ == "__main__":
    main()
