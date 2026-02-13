"""
HTTP Registration via Tiled Client.

Registers Hamiltonians with BOTH:
- Artifact locators in container metadata (for expert path-based access)
- Array children via DataSource adapters (for visualization/chunked access)

Dataset-agnostic: reads all metadata columns dynamically from manifests.
The manifest is the contract -- no hardcoded parameter names or artifact types.

When to use:
- Incremental updates to a running server
- Adding new datasets alongside existing ones
- Server is running and serving queries

When NOT to use:
- Initial bulk load of 1K+ Hamiltonians (use bulk_register.py / ingest.py)
"""

import os
import time

import numpy as np
import pandas as pd

from .utils import (
    make_artifact_key,
    to_json_safe,
    get_artifact_shape,
    ARTIFACT_STANDARD_COLS,
)


def create_data_source(art_row, base_dir):
    """Create a Tiled DataSource for an artifact pointing to external HDF5.

    Reads dataset path and shape from the manifest and HDF5 file directly.

    Args:
        art_row: DataFrame row with artifact manifest columns.
        base_dir: Base directory for resolving relative file paths.

    Returns:
        Tuple of (DataSource, data_shape, data_dtype).
    """
    from tiled.structures.core import StructureFamily
    from tiled.structures.array import ArrayStructure
    from tiled.structures.data_source import Asset, DataSource, Management

    h5_rel_path = art_row["file"]
    h5_full_path = os.path.join(base_dir, h5_rel_path)
    dataset_path = art_row["dataset"]

    # Determine index for batched files
    index = None
    if "index" in art_row.index and pd.notna(art_row.get("index")):
        index = int(art_row["index"])

    # Get shape from HDF5 (cached by dataset path)
    data_shape = get_artifact_shape(base_dir, h5_rel_path, dataset_path, index)
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


def register_dataset_http(client, ham_df, art_df, base_dir, label):
    """Register one dataset via HTTP through a running Tiled server.

    Creates Hamiltonian containers with locator metadata (Mode A) and
    array children via DataSource adapters (Mode B).

    Args:
        client: Tiled client connected to a running server.
        ham_df: Hamiltonian manifest DataFrame.
        art_df: Artifact manifest DataFrame.
        base_dir: Base directory for resolving relative file paths.
        label: Dataset name (for logging).

    Returns:
        bool: True if any Hamiltonians were registered.
    """
    from tiled.structures.core import StructureFamily

    start_time = time.time()
    ham_count = 0
    art_count = 0
    skip_count = 0

    # Pre-group artifacts by huid for O(1) lookup
    print("Pre-grouping artifacts by huid...")
    art_grouped = art_df.groupby("huid")

    n = len(ham_df)
    print(f"\n--- Registering {label} ({n} Hamiltonians via HTTP) ---")

    for i, (_, ham_row) in enumerate(ham_df.iterrows()):
        huid = str(ham_row["huid"])
        h_key = f"H_{huid[:8]}"

        # Skip if container already exists
        if h_key in client:
            skip_count += 1
            continue

        # Build metadata dynamically from ALL manifest columns
        metadata = {}
        for col in ham_df.columns:
            metadata[col] = to_json_safe(ham_row[col])

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
                            art_metadata[col] = to_json_safe(art_row[col])

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
        if (i + 1) % 5 == 0 or (i + 1) == n:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  Progress: {i+1}/{n} Hamiltonians ({rate:.1f}/sec)")

    elapsed_total = time.time() - start_time
    print(f"\nRegistration complete:")
    print(f"  Hamiltonians: {ham_count}")
    print(f"  Artifacts:    {art_count}")
    print(f"  Skipped:      {skip_count}")
    print(f"  Time:         {elapsed_total:.1f} seconds")

    return ham_count > 0


def verify_registration_http(client):
    """Verify registration via Tiled client.

    Args:
        client: Tiled client connected to a running server.
    """
    print("\n" + "=" * 50)
    print("Verification")
    print("=" * 50)

    total = len(client)
    print(f"Total Hamiltonian containers: {total}")

    if total == 0:
        print("No containers registered yet.")
        return

    keys = list(client.keys())[:3]
    print(f"First 3 container keys: {keys}")

    if keys:
        h_key = keys[0]
        h = client[h_key]
        meta = dict(h.metadata)

        print(f"\nContainer '{h_key}':")

        param_keys = [k for k in meta if not k.startswith(("path_", "dataset_", "index_"))]
        print(f"  Metadata keys: {param_keys}")

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

        children = list(h.keys())
        print(f"\n  Array children: {len(children)}")
        if children:
            print(f"    {children[:5]}")
            if len(children) > 5:
                print(f"    ... and {len(children) - 5} more")

            child_key = children[0]
            child = h[child_key]
            print(f"\n  Sample child '{child_key}':")
            print(f"    Shape: {child.shape}")
            print(f"    Dtype: {child.dtype}")

        if path_keys and children:
            print("\n  VERIFIED: Both locators AND array children present!")
        else:
            print("\n  WARNING: Dual-mode incomplete!")
            if not path_keys:
                print("    Missing: path_* metadata")
            if not children:
                print("    Missing: array children")
