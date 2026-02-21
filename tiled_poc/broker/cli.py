"""
CLI entry points for the broker package.

Provides three commands:
  - broker-ingest:    Bulk SQL registration from Parquet manifests
  - broker-generate:  Manifest generation from dataset configs
  - broker-register:  HTTP registration against a running Tiled server

All paths (catalog.db, manifests/, storage/, datasets/) are resolved
relative to the current working directory.
"""

import sys
import argparse
import importlib
from pathlib import Path

DB_PATH = Path("catalog.db")
MANIFESTS_DIR = Path("manifests")
STORAGE_DIR = Path("storage")


def _load_config(config_path):
    """Load a dataset config YAML file."""
    from ruamel.yaml import YAML

    yaml = YAML()
    with open(config_path) as f:
        return yaml.load(f)


# ── broker-ingest ────────────────────────────────────────────────

def ingest_main():
    """Bulk SQL registration (from ingest.py).

    Reads dataset config files (YAML), loads corresponding Parquet manifests
    from manifests/, and bulk-registers into catalog.db.
    """
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
        config = _load_config(config_path)
        name = Path(config_path).stem
        configs.append((name, config))

    readable_storage = [c["base_dir"] for _, c in configs]

    # Ensure catalog exists
    STORAGE_DIR.mkdir(exist_ok=True)
    engine = ensure_catalog(DB_PATH, readable_storage, STORAGE_DIR)

    # Register each dataset
    for name, config in configs:
        label = config.get("label", config["key"])
        base_dir = config["base_dir"]

        ent_path = MANIFESTS_DIR / f"{name}_entities.parquet"
        art_path = MANIFESTS_DIR / f"{name}_artifacts.parquet"

        if not ent_path.exists() or not art_path.exists():
            print(f"\nERROR: Parquet files not found for '{name}':")
            print(f"  Expected: {ent_path}")
            print(f"  Expected: {art_path}")
            print(f"  Run generate.py first.")
            sys.exit(1)

        ent_df = pd.read_parquet(ent_path)
        art_df = pd.read_parquet(art_path)

        dataset_key = config["key"]
        dataset_metadata = config.get("metadata", {"label": label})
        register_dataset(engine, ent_df, art_df, base_dir, label,
                         dataset_key=dataset_key,
                         dataset_metadata=dataset_metadata)

    # Verify
    from broker.bulk_register import verify_registration
    print()
    verify_registration(str(DB_PATH))

    print("\nDone!")


# ── broker-generate ──────────────────────────────────────────────

def generate_main(default_generators_dir="generators"):
    """Manifest generation (from generate.py).

    Reads dataset config files (YAML) and runs the corresponding manifest
    generator module.

    Args:
        default_generators_dir: Default directory for generator modules.
            The entry point (broker-generate) defaults to "generators/";
            tiled_poc/generate.py passes "extra/".
    """
    parser = argparse.ArgumentParser(description="Generate manifests from dataset configs.")
    parser.add_argument("configs", nargs="+", help="Dataset config YAML files")
    parser.add_argument("-n", type=int, default=10, help="Entities per dataset (default: 10)")
    parser.add_argument(
        "--generators-dir",
        type=str,
        default=default_generators_dir,
        help=f"Directory containing generator modules (default: {default_generators_dir})",
    )
    args = parser.parse_args()

    # Add generators dir to path for imports
    generators_path = Path(args.generators_dir).resolve()
    sys.path.insert(0, str(generators_path))

    manifests_dir = Path("manifests")
    manifests_dir.mkdir(exist_ok=True)

    print("=" * 50)
    print("Manifest Generation")
    print("=" * 50)
    print(f"Configs: {args.configs}")
    print(f"Entities per dataset: {args.n}")
    print(f"Generators dir: {generators_path}")
    print(f"Output: {manifests_dir.resolve()}")

    for config_path in args.configs:
        if not Path(config_path).exists():
            print(f"\nERROR: Config not found: {config_path}")
            sys.exit(1)

        config = _load_config(config_path)
        name = Path(config_path).stem
        label = config.get("label", config["key"])
        generator_module = config["generator"]

        print(f"\n--- Generating {label} ({name}) ---")

        module = importlib.import_module(generator_module)
        module.generate(str(manifests_dir), n_entities=args.n)

    print("\nDone!")


# ── broker-register ──────────────────────────────────────────────

def register_main():
    """HTTP registration against a running Tiled server (from register.py).

    Reads dataset config files (YAML), loads corresponding Parquet manifests
    from manifests/, and registers into a running Tiled server via HTTP.
    Incremental: skips entities that already exist.
    """
    parser = argparse.ArgumentParser(
        description="Register datasets into a running Tiled server via HTTP."
    )
    parser.add_argument("configs", nargs="+", help="Dataset config YAML files")
    parser.add_argument(
        "-n", "--max-entities",
        type=int,
        default=None,
        metavar="NUM",
        help="Limit number of entities per dataset (default: all)",
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

        config = _load_config(config_path)
        name = Path(config_path).stem
        label = config.get("label", config["key"])
        base_dir = config["base_dir"]

        ent_path = MANIFESTS_DIR / f"{name}_entities.parquet"
        art_path = MANIFESTS_DIR / f"{name}_artifacts.parquet"

        if not ent_path.exists() or not art_path.exists():
            print(f"\nERROR: Parquet files not found for '{name}':")
            print(f"  Expected: {ent_path}")
            print(f"  Expected: {art_path}")
            print(f"  Run generate.py first.")
            sys.exit(1)

        ent_df = pd.read_parquet(ent_path)
        art_df = pd.read_parquet(art_path)

        # Apply limit if specified
        if args.max_entities is not None:
            ent_df = ent_df.head(args.max_entities)

        # Clear shape cache between datasets
        get_artifact_shape.__defaults__[-1].clear()

        dataset_key = config["key"]
        dataset_metadata = config.get("metadata", {"label": label})
        register_dataset_http(client, ent_df, art_df, base_dir, label,
                              dataset_key=dataset_key,
                              dataset_metadata=dataset_metadata)

    # Verify
    verify_registration_http(client)

    print("\nDone!")
