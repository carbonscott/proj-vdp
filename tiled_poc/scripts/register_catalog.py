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
V6 Unified Dual-Mode Registration.

Registers Hamiltonians with BOTH:
- Artifact paths in container metadata (for expert path-based access)
- Array children via DataSource adapters (for visualization/chunked access)

Key differences from V4 and V5:
- V4: Arrays as children, huid in metadata (no paths)
- V5: Paths in metadata, no children (discovery-only)
- V6: BOTH paths in metadata AND arrays as children (unified dual-mode)

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

import numpy as np
import pandas as pd

from config import (
    get_base_dir,
    get_latest_manifest,
    get_tiled_url,
    get_api_key,
    get_max_hamiltonians,
    get_dataset_paths,
    get_default_shapes,
    get_service_dir,
)
from utils import check_server, make_artifact_key


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


def create_data_source(art_row):
    """Create a DataSource for an artifact pointing to external HDF5."""
    from tiled.structures.core import StructureFamily
    from tiled.structures.array import ArrayStructure
    from tiled.structures.data_source import Asset, DataSource, Management

    base_dir = get_base_dir()
    dataset_paths = get_dataset_paths()
    default_shapes = get_default_shapes()

    artifact_type = art_row["type"]
    h5_rel_path = art_row["path_rel"]
    h5_full_path = os.path.join(base_dir, h5_rel_path)

    # Get dataset path
    dataset_path = dataset_paths.get(artifact_type)
    if not dataset_path:
        raise ValueError(f"Unknown artifact type: {artifact_type}")

    # Get shape from config defaults or row
    shape_default = default_shapes.get(artifact_type, [1])
    if artifact_type == "mh_curve":
        data_shape = (int(art_row.get("n_hpts", shape_default[0])),)
    elif artifact_type == "gs_state":
        data_shape = tuple(shape_default)
    elif artifact_type == "ins_powder":
        data_shape = (
            int(art_row.get("nq", shape_default[0])),
            int(art_row.get("nw", shape_default[1])),
        )
    else:
        data_shape = tuple(shape_default)

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

    # Create data source
    data_source = DataSource(
        mimetype="application/x-hdf5",
        assets=[asset],
        structure_family=StructureFamily.array,
        structure=structure,
        parameters={"dataset": dataset_path},
        management=Management.external,
    )

    return data_source, data_shape, data_dtype


def register_unified_catalog(client, ham_df, art_df):
    """Register Hamiltonians with BOTH paths AND array adapters.

    V6 UNIFIED: Combines V4 (adapters) + V5 (paths in metadata).
    Users choose their access pattern at query time.
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
    print(f"Registering {len(ham_subset)} Hamiltonians (unified: paths + adapters)...")

    for i, (_, ham_row) in enumerate(ham_subset.iterrows()):
        huid = str(ham_row["huid"])
        h_key = f"H_{huid[:8]}"

        # Skip if container already exists
        if h_key in client:
            skip_count += 1
            continue

        # Build metadata with physics parameters
        metadata = {
            "huid": huid,
            "Ja_meV": float(ham_row["Ja_meV"]),
            "Jb_meV": float(ham_row["Jb_meV"]),
            "Jc_meV": float(ham_row["Jc_meV"]),
            "Dc_meV": float(ham_row["Dc_meV"]),
            "spin_s": float(ham_row.get("spin_s", 2.5)),
            "g_factor": float(ham_row.get("g_factor", 2.0)),
        }

        # V6 ADDITION: Add artifact paths to metadata (V5 pattern)
        artifacts = None
        if huid in art_grouped.groups:
            artifacts = art_grouped.get_group(huid)
            for _, art_row in artifacts.iterrows():
                path_key = make_artifact_key(art_row, prefix="path_")
                metadata[path_key] = art_row["path_rel"]

        # Create container with enriched metadata
        h_container = client.create_container(key=h_key, metadata=metadata)
        ham_count += 1

        # V6: Also register arrays as children (V4 pattern)
        if artifacts is not None:
            for _, art_row in artifacts.iterrows():
                try:
                    art_key = make_artifact_key(art_row)

                    # Create data source pointing to external HDF5
                    data_source, data_shape, data_dtype = create_data_source(art_row)

                    # Build artifact-specific metadata
                    art_metadata = {
                        "type": art_row["type"],
                        "shape": list(data_shape),
                        "dtype": str(data_dtype),
                    }

                    # Add type-specific metadata
                    if art_row["type"] == "mh_curve":
                        art_metadata["axis"] = art_row["axis"]
                        art_metadata["Hmax_T"] = float(art_row["Hmax_T"])
                    elif art_row["type"] == "ins_powder":
                        art_metadata["Ei_meV"] = float(art_row["Ei_meV"])

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
        print(f"  Physics params:")
        for k in ["Ja_meV", "Jb_meV", "Jc_meV", "Dc_meV"]:
            print(f"    {k}: {meta.get(k)}")

        # V6: Check paths in metadata
        path_keys = [k for k in meta.keys() if k.startswith("path_")]
        print(f"\n  Artifact paths in metadata: {len(path_keys)}")
        for pk in path_keys[:3]:
            val = meta[pk]
            if len(val) > 50:
                val = "..." + val[-47:]
            print(f"    {pk}: {val}")
        if len(path_keys) > 3:
            print(f"    ... and {len(path_keys) - 3} more")

        # V6: Check array children
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

        # V6 Verification
        if path_keys and children:
            print("\n  V6 VERIFIED: Both paths AND array children present!")
            print("  Users can choose either access mode.")
        else:
            print("\n  WARNING: V6 incomplete!")
            if not path_keys:
                print("    Missing: path_* metadata")
            if not children:
                print("    Missing: array children")


def main():
    tiled_url = get_tiled_url()
    max_hamiltonians = get_max_hamiltonians()

    print("=" * 60)
    print("VDP V6 Unified Dual-Mode Registration")
    print("=" * 60)
    print(f"Base dir:         {get_base_dir()}")
    print(f"Tiled URL:        {tiled_url}")
    print(f"Max Hamiltonians: {max_hamiltonians}")
    print()
    print("V6 registers BOTH:")
    print("  - path_* fields in metadata (expert path-based access)")
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
    print("Done! V6 catalog ready for dual-mode access.")
    print("=" * 60)


if __name__ == "__main__":
    main()
