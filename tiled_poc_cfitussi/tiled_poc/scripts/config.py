"""
VDP Configuration Module.

Loads configuration from config.yml and provides accessor functions.
Uses ruamel.yaml to preserve comments for round-trip editing.
"""

import os
import glob
from pathlib import Path
from ruamel.yaml import YAML


# Module-level config cache
_config = None
_config_path = None


def load_config(config_path=None):
    """Load VDP config from YAML file.

    Args:
        config_path: Path to config.yml. Defaults to config.yml in parent directory.

    Returns:
        dict: The 'vdp' section of the config file.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yml"

    yaml = YAML()
    with open(config_path) as f:
        full_config = yaml.load(f)

    return full_config.get("vdp", {})


def get_config():
    """Get cached config (loads once on first call)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_base_dir():
    """Get the base directory for schema data."""
    cfg = get_config()
    return f"{cfg['data_dir']}/manifests"


def get_service_dir():
    """Get the service directory (where catalog.db and storage/ live)."""
    return get_config()["service_dir"]


def get_catalog_db_path():
    """Get full path to catalog.db."""
    return os.path.join(get_service_dir(), "catalog.db")


def get_dataset_paths():
    """Get HDF5 dataset paths by artifact type."""
    return get_config().get("dataset_paths", {})


def get_default_shapes():
    """Get default array shapes by artifact type."""
    return get_config().get("default_shapes", {})


def get_latest_manifest(prefix):
    """Find latest manifest file by prefix.

    Args:
        prefix: "hamiltonians" or "artifacts"

    Returns:
        str: Path to the latest manifest file.

    Raises:
        FileNotFoundError: If no manifest file found.
    """
    base_dir = get_base_dir()
    pattern = f"{base_dir}/manifest_{prefix}.parquet"
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No manifest found matching: {pattern}")
    return files[-1]  # Latest by timestamp in filename


def get_tiled_url():
    """Get Tiled server URL (from env or default)."""
    return os.environ.get("TILED_URL", "http://localhost:8005")


def get_api_key():
    """Get Tiled API key (from env or default)."""
    return os.environ.get("TILED_API_KEY", "secret")


def get_max_hamiltonians():
    """Get max Hamiltonians to register (from env or config)."""
    default = get_config().get("max_hamiltonians", 10)
    return int(os.environ.get("VDP_MAX_HAMILTONIANS", default))
