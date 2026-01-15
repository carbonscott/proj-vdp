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
#     "canonicaljson",
#     "sqlalchemy",
# ]
# ///
"""
VDP Bulk Registration with SQLAlchemy.

Bypasses Tiled HTTP layer for maximum bulk insert performance.
Uses direct SQLAlchemy with trigger disable/rebuild pattern.

Key optimizations:
- Single database transaction for all inserts
- Disables closure table trigger during bulk load
- Rebuilds closure table with set-based SQL
- Re-enables trigger for future incremental updates

When to use:
- Initial bulk load of 1K+ Hamiltonians
- Fresh database registration
- Maximum speed needed

When NOT to use:
- Incremental updates (use register_catalog.py instead)
- Server is running and serving queries

Usage:
    # Register with defaults (10 Hamiltonians to catalog.db)
    python bulk_register.py

    # Register specific number of Hamiltonians
    python bulk_register.py -n 1000

    # Register all 10K Hamiltonians to a specific database
    python bulk_register.py -n 10000 -o catalog-bulk.db

    # Force overwrite without prompting
    python bulk_register.py -n 100 --force

    # Environment variables still work as fallbacks
    VDP_MAX_HAMILTONIANS=10000 CATALOG_DB=catalog-bulk.db python bulk_register.py
"""

import os
import sys
import time
import json
import hashlib
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import canonicaljson
from sqlalchemy import create_engine, text

# Import from shared helpers
from config import (
    get_base_dir,
    get_latest_manifest,
    get_max_hamiltonians,
    get_dataset_paths,
    get_default_shapes,
    get_catalog_db_path,
)
from utils import make_artifact_key


def compute_structure_id(structure):
    """Compute HEX digest of MD5 hash of RFC 8785 canonical JSON."""
    canonical = canonicaljson.encode_canonical_json(structure)
    return hashlib.md5(canonical).hexdigest()


# SQLite trigger SQL (from Tiled orm.py)
CLOSURE_TRIGGER_SQL = """
CREATE TRIGGER update_closure_table_when_inserting
AFTER INSERT ON nodes
BEGIN
    INSERT INTO nodes_closure(ancestor, descendant, depth)
    SELECT NEW.id, NEW.id, 0;
    INSERT INTO nodes_closure(ancestor, descendant, depth)
    SELECT p.ancestor, c.descendant, p.depth+c.depth+1
    FROM nodes_closure p, nodes_closure c
    WHERE p.descendant=NEW.parent and c.ancestor=NEW.id;
END
"""


def init_database(db_path):
    """Initialize database with Tiled schema.

    Uses Tiled's catalog adapter to create schema, then returns
    a raw SQLAlchemy engine for bulk operations.
    """
    from tiled.catalog import from_uri as catalog_from_uri

    # Remove existing database for fresh start
    if os.path.exists(db_path):
        print(f"  Removing existing database: {db_path}")
        os.remove(db_path)

    # Use Tiled to create schema (runs migrations, creates triggers)
    print(f"  Initializing schema via Tiled...")
    uri = f"sqlite:///{db_path}"

    # from_uri is sync - just call it directly
    catalog_from_uri(
        uri,
        writable_storage=str(Path(db_path).parent / "storage"),
        readable_storage=[get_base_dir()],
        init_if_not_exists=True,
    )

    # Return sync engine for bulk operations
    engine = create_engine(f"sqlite:///{db_path}")
    return engine


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


def prepare_node_data(ham_df, art_df, max_hamiltonians):
    """Prepare all node data for bulk insert.

    Returns:
        ham_nodes: List of Hamiltonian node dicts
        art_nodes: List of artifact node dicts (with placeholder parent)
        art_data_sources: List of data source info for artifacts
    """
    base_dir = get_base_dir()
    dataset_paths = get_dataset_paths()
    default_shapes = get_default_shapes()

    ham_subset = ham_df.head(max_hamiltonians)
    art_grouped = art_df.groupby("huid")

    ham_nodes = []
    art_nodes = []
    art_data_sources = []

    print(f"Preparing data for {len(ham_subset)} Hamiltonians...")

    for _, ham_row in ham_subset.iterrows():
        huid = str(ham_row["huid"])
        h_key = f"H_{huid[:8]}"

        # Build Hamiltonian metadata with paths
        metadata = {
            "huid": huid,
            "Ja_meV": float(ham_row["Ja_meV"]),
            "Jb_meV": float(ham_row["Jb_meV"]),
            "Jc_meV": float(ham_row["Jc_meV"]),
            "Dc_meV": float(ham_row["Dc_meV"]),
            "spin_s": float(ham_row.get("spin_s", 2.5)),
            "g_factor": float(ham_row.get("g_factor", 2.0)),
        }

        # Add artifact paths to metadata
        artifacts = None
        if huid in art_grouped.groups:
            artifacts = art_grouped.get_group(huid)
            for _, art_row in artifacts.iterrows():
                path_key = make_artifact_key(art_row, prefix="path_")
                metadata[path_key] = art_row["path_rel"]

        ham_nodes.append({
            "key": h_key,
            "huid": huid,  # For linking artifacts
            "structure_family": "container",
            "metadata": metadata,
            "specs": [],
            "access_blob": {},
        })

        # Process artifacts for this Hamiltonian
        if artifacts is not None:
            for _, art_row in artifacts.iterrows():
                art_key = make_artifact_key(art_row)
                artifact_type = art_row["type"]
                h5_rel_path = art_row["path_rel"]
                h5_full_path = os.path.join(base_dir, h5_rel_path)

                # Get shape
                shape_default = default_shapes.get(artifact_type, [1])
                if artifact_type == "mh_curve":
                    data_shape = [int(art_row.get("n_hpts", shape_default[0]))]
                elif artifact_type == "gs_state":
                    data_shape = list(shape_default)
                elif artifact_type == "ins_powder":
                    data_shape = [
                        int(art_row.get("nq", shape_default[0])),
                        int(art_row.get("nw", shape_default[1])),
                    ]
                else:
                    data_shape = list(shape_default)

                # Build artifact metadata
                art_metadata = {
                    "type": artifact_type,
                    "shape": data_shape,
                    "dtype": "float64",
                }
                if artifact_type == "mh_curve":
                    art_metadata["axis"] = art_row["axis"]
                    art_metadata["Hmax_T"] = float(art_row["Hmax_T"])
                elif artifact_type == "ins_powder":
                    art_metadata["Ei_meV"] = float(art_row["Ei_meV"])

                # Build structure for this artifact
                # Chunks must be list of lists, one per dimension
                chunks = [[dim] for dim in data_shape]
                structure = {
                    "data_type": {
                        "endianness": "little",
                        "kind": "f",
                        "itemsize": 8,
                    },
                    "chunks": chunks,
                    "shape": data_shape,
                    "dims": None,
                    "resizable": False,
                }
                structure_id = compute_structure_id(structure)

                art_nodes.append({
                    "key": art_key,
                    "parent_huid": huid,  # For linking to parent
                    "structure_family": "array",
                    "metadata": art_metadata,
                    "specs": [],
                    "access_blob": {},
                })

                art_data_sources.append({
                    "art_key": art_key,
                    "parent_huid": huid,
                    "structure_id": structure_id,
                    "structure": structure,
                    "h5_path": h5_full_path,
                    "dataset_path": dataset_paths.get(artifact_type),
                })

    print(f"  Prepared {len(ham_nodes)} Hamiltonians, {len(art_nodes)} artifacts")
    return ham_nodes, art_nodes, art_data_sources


def bulk_register(engine, ham_nodes, art_nodes, art_data_sources):
    """Bulk insert all data with trigger disable/rebuild."""

    start_time = time.time()

    with engine.connect() as conn:
        # Step 1: Disable closure table trigger
        print("Step 1: Disabling closure table trigger...")
        conn.execute(text("DROP TRIGGER IF EXISTS update_closure_table_when_inserting"))

        # Step 2: Insert Hamiltonian nodes
        print(f"Step 2: Inserting {len(ham_nodes)} Hamiltonian nodes...")
        ham_id_map = {}  # huid -> node_id

        for ham in ham_nodes:
            result = conn.execute(
                text("""
                    INSERT INTO nodes (parent, key, structure_family, metadata, specs, access_blob)
                    VALUES (0, :key, :structure_family, :metadata, :specs, :access_blob)
                """),
                {
                    "key": ham["key"],
                    "structure_family": ham["structure_family"],
                    "metadata": json.dumps(ham["metadata"]),
                    "specs": json.dumps(ham["specs"]),
                    "access_blob": json.dumps(ham["access_blob"]),
                }
            )
            ham_id_map[ham["huid"]] = result.lastrowid

        # Step 3: Insert artifact nodes
        print(f"Step 3: Inserting {len(art_nodes)} artifact nodes...")
        art_id_map = {}  # (huid, art_key) -> node_id

        for art in art_nodes:
            parent_id = ham_id_map[art["parent_huid"]]
            result = conn.execute(
                text("""
                    INSERT INTO nodes (parent, key, structure_family, metadata, specs, access_blob)
                    VALUES (:parent, :key, :structure_family, :metadata, :specs, :access_blob)
                """),
                {
                    "parent": parent_id,
                    "key": art["key"],
                    "structure_family": art["structure_family"],
                    "metadata": json.dumps(art["metadata"]),
                    "specs": json.dumps(art["specs"]),
                    "access_blob": json.dumps(art["access_blob"]),
                }
            )
            art_id_map[(art["parent_huid"], art["key"])] = result.lastrowid

        # Step 4: Insert structures (deduplicated)
        print("Step 4: Inserting structures...")
        structures_seen = set()
        for ds in art_data_sources:
            sid = ds["structure_id"]
            if sid not in structures_seen:
                conn.execute(
                    text("""
                        INSERT OR IGNORE INTO structures (id, structure)
                        VALUES (:id, :structure)
                    """),
                    {"id": sid, "structure": json.dumps(ds["structure"])}
                )
                structures_seen.add(sid)
        print(f"  Inserted {len(structures_seen)} unique structures")

        # Step 5: Insert assets (deduplicated by data_uri)
        print("Step 5: Inserting assets...")
        asset_id_map = {}  # data_uri -> asset_id

        for ds in art_data_sources:
            data_uri = f"file://localhost{ds['h5_path']}"
            if data_uri not in asset_id_map:
                result = conn.execute(
                    text("""
                        INSERT OR IGNORE INTO assets (data_uri, is_directory)
                        VALUES (:data_uri, 0)
                    """),
                    {"data_uri": data_uri}
                )
                # Get the ID (either from insert or existing)
                existing = conn.execute(
                    text("SELECT id FROM assets WHERE data_uri = :data_uri"),
                    {"data_uri": data_uri}
                ).fetchone()
                asset_id_map[data_uri] = existing[0]
        print(f"  Inserted {len(asset_id_map)} unique assets")

        # Step 6: Insert data_sources
        print("Step 6: Inserting data sources...")
        ds_id_map = {}  # (huid, art_key) -> data_source_id

        for ds in art_data_sources:
            node_id = art_id_map[(ds["parent_huid"], ds["art_key"])]
            result = conn.execute(
                text("""
                    INSERT INTO data_sources (node_id, structure_id, mimetype, parameters, management, structure_family)
                    VALUES (:node_id, :structure_id, :mimetype, :parameters, :management, :structure_family)
                """),
                {
                    "node_id": node_id,
                    "structure_id": ds["structure_id"],
                    "mimetype": "application/x-hdf5",
                    "parameters": json.dumps({"dataset": ds["dataset_path"]}),
                    "management": "external",
                    "structure_family": "array",
                }
            )
            ds_id_map[(ds["parent_huid"], ds["art_key"])] = result.lastrowid

        # Step 7: Insert data_source_asset_association
        print("Step 7: Inserting data source asset associations...")
        for ds in art_data_sources:
            ds_id = ds_id_map[(ds["parent_huid"], ds["art_key"])]
            data_uri = f"file://localhost{ds['h5_path']}"
            asset_id = asset_id_map[data_uri]
            conn.execute(
                text("""
                    INSERT INTO data_source_asset_association (data_source_id, asset_id, parameter, num)
                    VALUES (:ds_id, :asset_id, :parameter, NULL)
                """),
                {"ds_id": ds_id, "asset_id": asset_id, "parameter": "data_uris"}
            )

        # Step 8: Rebuild closure table
        print("Step 8: Rebuilding closure table...")

        # Clear existing data (root node was auto-inserted)
        conn.execute(text("DELETE FROM nodes_closure"))

        # Self-references (depth=0)
        conn.execute(text("""
            INSERT INTO nodes_closure (ancestor, descendant, depth)
            SELECT id, id, 0 FROM nodes
        """))

        # Parent-child (depth=1)
        conn.execute(text("""
            INSERT INTO nodes_closure (ancestor, descendant, depth)
            SELECT parent, id, 1 FROM nodes WHERE parent IS NOT NULL
        """))

        # Grandparent (depth=2) - for 2-level hierarchy
        conn.execute(text("""
            INSERT INTO nodes_closure (ancestor, descendant, depth)
            SELECT gp.parent, n.id, 2
            FROM nodes n
            JOIN nodes gp ON n.parent = gp.id
            WHERE gp.parent IS NOT NULL
        """))

        # Verify closure table
        closure_count = conn.execute(text("SELECT COUNT(*) FROM nodes_closure")).fetchone()[0]
        print(f"  Closure table rows: {closure_count}")

        # Step 9: Re-enable trigger
        print("Step 9: Re-enabling closure table trigger...")
        conn.execute(text(CLOSURE_TRIGGER_SQL))

        # Commit everything
        conn.commit()

    elapsed = time.time() - start_time
    print(f"\nBulk registration complete in {elapsed:.1f} seconds")
    return elapsed


def verify_registration(db_path):
    """Verify the bulk registration worked."""
    print("\n" + "=" * 50)
    print("Verification")
    print("=" * 50)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        # Count tables
        nodes = conn.execute(text("SELECT COUNT(*) FROM nodes")).fetchone()[0]
        closure = conn.execute(text("SELECT COUNT(*) FROM nodes_closure")).fetchone()[0]
        data_sources = conn.execute(text("SELECT COUNT(*) FROM data_sources")).fetchone()[0]
        structures = conn.execute(text("SELECT COUNT(*) FROM structures")).fetchone()[0]
        assets = conn.execute(text("SELECT COUNT(*) FROM assets")).fetchone()[0]
        associations = conn.execute(text("SELECT COUNT(*) FROM data_source_asset_association")).fetchone()[0]

        print(f"Table counts:")
        print(f"  nodes:          {nodes}")
        print(f"  nodes_closure:  {closure}")
        print(f"  data_sources:   {data_sources}")
        print(f"  structures:     {structures}")
        print(f"  assets:         {assets}")
        print(f"  associations:   {associations}")

        # Sample a Hamiltonian
        ham = conn.execute(text("""
            SELECT id, key, metadata FROM nodes
            WHERE parent = 0 AND key != ''
            LIMIT 1
        """)).fetchone()

        if ham:
            print(f"\nSample Hamiltonian: {ham[1]}")
            meta = json.loads(ham[2])
            print(f"  Ja_meV: {meta.get('Ja_meV')}")
            print(f"  Jb_meV: {meta.get('Jb_meV')}")

            # Count children
            children = conn.execute(text("""
                SELECT COUNT(*) FROM nodes WHERE parent = :parent_id
            """), {"parent_id": ham[0]}).fetchone()[0]
            print(f"  Children: {children}")

            # Check path keys in metadata
            path_keys = [k for k in meta.keys() if k.startswith("path_")]
            print(f"  Path keys: {len(path_keys)}")

    print("\n" + "=" * 50)
    print("To test with Tiled server:")
    print("=" * 50)
    print("""
1. Start server:
   uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret

2. Test retrieval:
   uv run --with 'tiled[server]' --with pandas python -c "
   from tiled.client import from_uri
   client = from_uri('http://localhost:8005', api_key='secret')
   print(f'Hamiltonians: {len(client)}')
   h = client[list(client)[0]]
   print(f'Artifacts: {list(h)}')
   print(f'Data shape: {h[list(h.keys())[0]].read().shape}')
   "
""")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Bulk register VDP Hamiltonians to Tiled catalog using SQLAlchemy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                        # Register 10 Hamiltonians (default)
  %(prog)s -n 1000                # Register 1000 Hamiltonians
  %(prog)s -n 10000 -o bulk.db    # Register all to bulk.db
  %(prog)s -n 100 --force         # Overwrite without prompting

Environment variables (used as fallbacks):
  VDP_MAX_HAMILTONIANS   Number of Hamiltonians (default: from config)
  CATALOG_DB             Database filename (default: catalog.db)
"""
    )

    parser.add_argument(
        "-n", "--max-hamiltonians",
        type=int,
        default=None,
        metavar="NUM",
        help="Number of Hamiltonians to register (default: 10 or VDP_MAX_HAMILTONIANS)"
    )

    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        metavar="DB_NAME",
        help="Output database filename (default: catalog.db or CATALOG_DB)"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing database without prompting"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("VDP VDP Bulk Registration (SQLAlchemy + Trigger Rebuild)")
    print("=" * 60)

    # Determine database path (CLI > env var > config default)
    from config import get_service_dir

    if args.output:
        db_path = os.path.join(get_service_dir(), args.output)
    elif os.environ.get("CATALOG_DB"):
        db_path = os.path.join(get_service_dir(), os.environ.get("CATALOG_DB"))
    else:
        db_path = get_catalog_db_path()

    # Determine max Hamiltonians (CLI > env var > config default)
    if args.max_hamiltonians is not None:
        max_hamiltonians = args.max_hamiltonians
    else:
        max_hamiltonians = get_max_hamiltonians()

    print(f"Database:         {db_path}")
    print(f"Data dir:         {get_base_dir()}")
    print(f"Max Hamiltonians: {max_hamiltonians}")
    print()

    # Check if database exists and handle --force
    if os.path.exists(db_path) and not args.force:
        print(f"WARNING: Database already exists: {db_path}")
        response = input("Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("Aborted.")
            sys.exit(0)

    # Initialize database
    print("Initializing database...")
    engine = init_database(db_path)

    # Load manifests
    ham_df, art_df = load_manifests()

    # Prepare data
    ham_nodes, art_nodes, art_data_sources = prepare_node_data(
        ham_df, art_df, max_hamiltonians
    )

    # Bulk register
    print("\nStarting bulk registration...")
    elapsed = bulk_register(engine, ham_nodes, art_nodes, art_data_sources)

    # Calculate rate
    total_nodes = len(ham_nodes) + len(art_nodes) + 1  # +1 for root
    rate = total_nodes / elapsed if elapsed > 0 else 0
    print(f"Rate: {rate:.0f} nodes/sec")

    # Verify
    verify_registration(db_path)


if __name__ == "__main__":
    main()
