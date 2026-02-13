#!/usr/bin/env python
"""
Generic manifest generator CLI.

Reads dataset config files (YAML) and runs the corresponding manifest
generator from extra/. Fully generic — zero dataset-specific knowledge.

Usage:
    python generate.py datasets/vdp.yml -n 10
    python generate.py datasets/vdp.yml datasets/edrixs.yml -n 10

Dataset config format (YAML):
    label: VDP
    generator: gen_vdp_manifest
    base_dir: /path/to/data

The generator module must expose: generate(output_dir, n_entities) -> (ent_df, art_df)
"""

import sys
import argparse
import importlib
from pathlib import Path

# Add extra/ to path for generator imports
TILED_POC = Path(__file__).resolve().parent
sys.path.insert(0, str(TILED_POC / "extra"))


def load_config(config_path):
    """Load a dataset config YAML file."""
    from ruamel.yaml import YAML

    yaml = YAML()
    with open(config_path) as f:
        return yaml.load(f)


def generate_one(config_path, manifests_dir, n_entities):
    """Generate manifests for one dataset config."""
    config = load_config(config_path)
    name = Path(config_path).stem
    label = config["label"]
    generator_module = config["generator"]

    print(f"\n--- Generating {label} ({name}) ---")

    module = importlib.import_module(generator_module)
    ent_df, art_df = module.generate(str(manifests_dir), n_entities=n_entities)

    return ent_df, art_df


def main():
    parser = argparse.ArgumentParser(description="Generate manifests from dataset configs.")
    parser.add_argument("configs", nargs="+", help="Dataset config YAML files")
    parser.add_argument("-n", type=int, default=10, help="Entities per dataset (default: 10)")
    args = parser.parse_args()

    manifests_dir = Path("manifests")
    manifests_dir.mkdir(exist_ok=True)

    print("=" * 50)
    print("Manifest Generation")
    print("=" * 50)
    print(f"Configs: {args.configs}")
    print(f"Entities per dataset: {args.n}")
    print(f"Output: {manifests_dir.resolve()}")

    for config_path in args.configs:
        if not Path(config_path).exists():
            print(f"\nERROR: Config not found: {config_path}")
            sys.exit(1)
        generate_one(config_path, manifests_dir, args.n)

    print("\nDone!")


if __name__ == "__main__":
    main()
