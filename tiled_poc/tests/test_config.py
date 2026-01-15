# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "ruamel.yaml",
# ]
# ///
"""
Unit tests for config module.

These tests verify configuration loading and accessor functions.
No Tiled server required.

Run with:
    uv run --with pytest pytest tests/test_config.py -v
"""

import os
import sys
from pathlib import Path

import pytest

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestGetBaseDir:
    """Tests for get_base_dir()."""

    def test_returns_string(self):
        from config import get_base_dir

        base = get_base_dir()
        assert isinstance(base, str)

    def test_contains_schema_version(self):
        from config import get_base_dir

        base = get_base_dir()
        assert "schema_v1" in base

    def test_contains_data_path(self):
        from config import get_base_dir

        base = get_base_dir()
        assert "/data/" in base


class TestGetLatestManifest:
    """Tests for get_latest_manifest()."""

    def test_finds_hamiltonians_manifest(self):
        from config import get_latest_manifest

        path = get_latest_manifest("hamiltonians")
        assert path.endswith(".parquet")
        assert os.path.exists(path)

    def test_finds_artifacts_manifest(self):
        from config import get_latest_manifest

        path = get_latest_manifest("artifacts")
        assert path.endswith(".parquet")
        assert os.path.exists(path)

    def test_raises_for_invalid_prefix(self):
        from config import get_latest_manifest

        with pytest.raises(FileNotFoundError):
            get_latest_manifest("nonexistent_prefix")


class TestGetMaxHamiltonians:
    """Tests for get_max_hamiltonians()."""

    def test_returns_integer(self):
        from config import get_max_hamiltonians

        result = get_max_hamiltonians()
        assert isinstance(result, int)

    def test_default_is_positive(self):
        from config import get_max_hamiltonians

        result = get_max_hamiltonians()
        assert result > 0

    def test_respects_env_variable(self):
        """Test that VDP_MAX_HAMILTONIANS environment variable is respected."""
        import importlib
        import config

        # Set env var
        os.environ["VDP_MAX_HAMILTONIANS"] = "42"

        # Reload config to pick up new env var
        # Reset the module-level cache first
        config._config = None
        importlib.reload(config)

        result = config.get_max_hamiltonians()
        assert result == 42

        # Cleanup
        del os.environ["VDP_MAX_HAMILTONIANS"]
        config._config = None
        importlib.reload(config)


class TestGetTiledUrl:
    """Tests for get_tiled_url()."""

    def test_returns_string(self):
        from config import get_tiled_url

        url = get_tiled_url()
        assert isinstance(url, str)

    def test_default_is_localhost(self):
        from config import get_tiled_url

        # Clear env var if set
        old_val = os.environ.pop("TILED_URL", None)

        url = get_tiled_url()
        assert "localhost" in url

        # Restore
        if old_val:
            os.environ["TILED_URL"] = old_val

    def test_respects_env_variable(self):
        from config import get_tiled_url

        os.environ["TILED_URL"] = "http://test:9999"

        url = get_tiled_url()
        assert url == "http://test:9999"

        # Cleanup
        del os.environ["TILED_URL"]


class TestGetApiKey:
    """Tests for get_api_key()."""

    def test_returns_string(self):
        from config import get_api_key

        key = get_api_key()
        assert isinstance(key, str)

    def test_default_is_secret(self):
        from config import get_api_key

        # Clear env var if set
        old_val = os.environ.pop("TILED_API_KEY", None)

        key = get_api_key()
        assert key == "secret"

        # Restore
        if old_val:
            os.environ["TILED_API_KEY"] = old_val
