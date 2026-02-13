#!/usr/bin/env python
"""
Generic ingest CLI.

Reads dataset config files (YAML), loads corresponding Parquet manifests
from manifests/, and bulk-registers into catalog.db. Fully generic — zero
dataset-specific knowledge.

Usage:
    python ingest.py datasets/vdp.yml
    python ingest.py datasets/vdp.yml datasets/edrixs.yml

Dataset config format (YAML):
    label: VDP
    generator: gen_vdp_manifest    # ignored by ingest
    base_dir: /path/to/data

Parquet filenames are derived from the config filename stem:
    datasets/vdp.yml → manifests/vdp_hamiltonians.parquet, manifests/vdp_artifacts.parquet

IMPORTANT: This script is ADDITIVE. Running it twice with the same config
will create duplicate entries. To re-ingest, delete catalog.db first.
"""

import sys
import argparse
from pathlib import Path

DB_PATH = Path("catalog.db")
MANIFESTS_DIR = Path("manifests")
STORAGE_DIR = Path("storage")


def load_config(config_path):
    """Load a dataset config YAML file."""
    from ruamel.yaml import YAML

    yaml = YAML()
    with open(config_path) as f:
        return yaml.load(f)


def main():
    parser = argparse.ArgumentParser(description="Ingest datasets from config files.")
    parser.add_argument("configs", nargs="+", help="Dataset config YAML files")
    args = parser.parse_args()

    import pandas as pd
    from broker.catalog import ensure_catalog, register_dataset

    print("=" * 50)
    print("Ingest")
    print("=" * 50)
    print(f"Configs: {args.configs}")
    print(f"Database: {DB_PATH.resolve()}")

    # Collect base_dirs from all configs for readable_storage
    configs = []
    for config_path in args.configs:
        if not Path(config_path).exists():
            print(f"\nERROR: Config not found: {config_path}")
            sys.exit(1)
        config = load_config(config_path)
        name = Path(config_path).stem
        configs.append((name, config))

    readable_storage = [c["base_dir"] for _, c in configs]

    # Ensure catalog exists
    STORAGE_DIR.mkdir(exist_ok=True)
    engine = ensure_catalog(DB_PATH, readable_storage, STORAGE_DIR)

    # Register each dataset
    for name, config in configs:
        label = config["label"]
        base_dir = config["base_dir"]

        ham_path = MANIFESTS_DIR / f"{name}_hamiltonians.parquet"
        art_path = MANIFESTS_DIR / f"{name}_artifacts.parquet"

        if not ham_path.exists() or not art_path.exists():
            print(f"\nERROR: Parquet files not found for '{name}':")
            print(f"  Expected: {ham_path}")
            print(f"  Expected: {art_path}")
            print(f"  Run generate.py first.")
            sys.exit(1)

        ham_df = pd.read_parquet(ham_path)
        art_df = pd.read_parquet(art_path)

        register_dataset(engine, ham_df, art_df, base_dir, label)

    # Verify
    from broker.bulk_register import verify_registration
    print()
    verify_registration(str(DB_PATH))

    print("\nDone!")


if __name__ == "__main__":
    main()
