#!/usr/bin/env python
"""
Generic HTTP registration CLI.

Reads dataset config files (YAML), loads corresponding Parquet manifests
from manifests/, and registers into a running Tiled server via HTTP.
Fully generic -- zero dataset-specific knowledge.

Usage:
    python register.py datasets/vdp.yml
    python register.py datasets/vdp.yml datasets/edrixs.yml
    python register.py datasets/edrixs.yml -n 5

Dataset config format (YAML):
    label: VDP
    generator: gen_vdp_manifest    # ignored by register
    base_dir: /path/to/data

Parquet filenames are derived from the config filename stem:
    datasets/vdp.yml -> manifests/vdp_hamiltonians.parquet, manifests/vdp_artifacts.parquet

NOTE: This script is INCREMENTAL. It skips Hamiltonians that already exist
in the catalog (by key). Safe to run multiple times.

Requires a running Tiled server. Set TILED_URL and TILED_API_KEY env vars
or use defaults (http://localhost:8005, secret).
"""

import sys
import argparse
from pathlib import Path

MANIFESTS_DIR = Path("manifests")


def load_config(config_path):
    """Load a dataset config YAML file."""
    from ruamel.yaml import YAML

    yaml = YAML()
    with open(config_path) as f:
        return yaml.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Register datasets into a running Tiled server via HTTP."
    )
    parser.add_argument("configs", nargs="+", help="Dataset config YAML files")
    parser.add_argument(
        "-n", "--max-hamiltonians",
        type=int,
        default=None,
        metavar="NUM",
        help="Limit number of Hamiltonians per dataset (default: all)",
    )
    args = parser.parse_args()

    import pandas as pd
    from broker.utils import check_server, get_artifact_shape
    from broker.http_register import register_dataset_http, verify_registration_http

    print("=" * 50)
    print("Register (HTTP)")
    print("=" * 50)
    print(f"Configs: {args.configs}")

    # Check server is running
    print("\nChecking Tiled server...")
    if not check_server():
        print("ERROR: Tiled server not running!")
        print("\nStart the server first:")
        print("  uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret")
        sys.exit(1)
    print("Server is running.")

    # Connect to Tiled
    from broker.config import get_tiled_url, get_api_key
    from tiled.client import from_uri

    tiled_url = get_tiled_url()
    client = from_uri(tiled_url, api_key=get_api_key())
    print(f"Connected to {tiled_url} ({len(client)} existing containers)")

    # Load and register each dataset
    for config_path in args.configs:
        if not Path(config_path).exists():
            print(f"\nERROR: Config not found: {config_path}")
            sys.exit(1)

        config = load_config(config_path)
        name = Path(config_path).stem
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

        # Apply limit if specified
        if args.max_hamiltonians is not None:
            ham_df = ham_df.head(args.max_hamiltonians)

        # Clear shape cache between datasets
        get_artifact_shape.__defaults__[-1].clear()

        register_dataset_http(client, ham_df, art_df, base_dir, label)

    # Verify
    verify_registration_http(client)

    print("\nDone!")


if __name__ == "__main__":
    main()
