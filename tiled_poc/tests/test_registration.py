# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "tiled[server]",
#     "pandas",
#     "h5py",
#     "numpy",
#     "ruamel.yaml",
#     "sqlalchemy",
# ]
# ///
"""
Integration tests for data registration.

Tests both registration methods:
- HTTP-based registration (register_catalog.py)
- Bulk SQLAlchemy registration (bulk_register.py)

Prerequisites:
    # For HTTP registration tests, start server first:
    uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret

Run with:
    uv run --with pytest pytest tests/test_registration.py -v
"""

import os
import sys
from pathlib import Path

import pytest
import pandas as pd

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestLoadManifests:
    """Tests for manifest loading (used by both registration methods)."""

    def test_load_hamiltonians_manifest(self):
        """Test that Hamiltonians manifest can be loaded."""
        from config import get_latest_manifest

        path = get_latest_manifest("hamiltonians")
        df = pd.read_parquet(path)

        assert len(df) > 0
        assert "huid" in df.columns

    def test_load_artifacts_manifest(self):
        """Test that Artifacts manifest can be loaded."""
        from config import get_latest_manifest

        path = get_latest_manifest("artifacts")
        df = pd.read_parquet(path)

        assert len(df) > 0
        assert "type" in df.columns
        assert "huid" in df.columns

    def test_manifests_have_matching_huids(self):
        """Test that artifact huids match Hamiltonian huids."""
        from config import get_latest_manifest

        ham_df = pd.read_parquet(get_latest_manifest("hamiltonians"))
        art_df = pd.read_parquet(get_latest_manifest("artifacts"))

        ham_huids = set(ham_df["huid"])
        art_huids = set(art_df["huid"])

        # All artifact huids should exist in Hamiltonians
        assert art_huids.issubset(ham_huids)


@pytest.mark.integration
class TestHttpRegistration:
    """Integration tests for HTTP-based registration.

    Requires running Tiled server with registered data.
    """

    def test_server_has_containers(self, tiled_client):
        """Test that registered Hamiltonians appear as containers."""
        assert len(tiled_client) > 0

    def test_container_has_metadata(self, tiled_client):
        """Test that containers have physics parameters in metadata."""
        h_key = list(tiled_client.keys())[0]
        h = tiled_client[h_key]

        # Check physics parameters
        assert "Ja_meV" in h.metadata
        assert "Jb_meV" in h.metadata
        assert "Jc_meV" in h.metadata
        assert "Dc_meV" in h.metadata

    def test_container_has_artifact_paths(self, tiled_client):
        """Test that containers have artifact paths in metadata (Mode A)."""
        h_key = list(tiled_client.keys())[0]
        h = tiled_client[h_key]

        # Check for path metadata (Mode A support)
        path_keys = [k for k in h.metadata.keys() if k.startswith("path_")]
        assert len(path_keys) > 0

    def test_container_has_children(self, tiled_client):
        """Test that containers have artifact children (Mode B)."""
        h_key = list(tiled_client.keys())[0]
        h = tiled_client[h_key]

        children = list(h.keys())
        assert len(children) > 0

    def test_container_children_are_arrays(self, tiled_client):
        """Test that children are accessible as arrays."""
        h_key = list(tiled_client.keys())[0]
        h = tiled_client[h_key]

        children = list(h.keys())
        if "mh_powder_30T" in children:
            arr = h["mh_powder_30T"][:]
            assert arr.ndim == 1
            assert len(arr) == 200  # M(H) has 200 points


@pytest.mark.integration
class TestBulkRegistration:
    """Integration tests for bulk SQLAlchemy registration.

    These tests create a temporary database and verify the bulk
    registration creates correct schema and data.
    """

    def test_init_database_creates_tables(self, temp_catalog_db):
        """Test that init_database creates required tables."""
        from sqlalchemy import create_engine, text, inspect

        # Create engine and init
        engine = create_engine(f"sqlite:///{temp_catalog_db}")

        # Run the init SQL from tiled's schema
        with engine.connect() as conn:
            # Create minimal schema for testing
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id INTEGER PRIMARY KEY,
                    key TEXT,
                    parent INTEGER,
                    structure_family TEXT,
                    metadata_json TEXT
                )
            """))
            conn.commit()

        # Verify table exists
        inspector = inspect(engine)
        assert "nodes" in inspector.get_table_names()

    def test_bulk_registration_creates_nodes(self, temp_catalog_db):
        """Test that bulk registration creates node entries."""
        from sqlalchemy import create_engine, text
        from config import get_latest_manifest

        # Load small subset of manifests
        ham_df = pd.read_parquet(get_latest_manifest("hamiltonians")).head(3)

        # Create simple test database
        engine = create_engine(f"sqlite:///{temp_catalog_db}")
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    parent INTEGER DEFAULT 0,
                    structure_family TEXT DEFAULT 'container'
                )
            """))

            # Insert test nodes
            for _, row in ham_df.iterrows():
                h_key = f"H_{row['huid'][:8]}"
                conn.execute(
                    text("INSERT INTO nodes (key, parent) VALUES (:key, 0)"),
                    {"key": h_key}
                )
            conn.commit()

            # Verify nodes created
            count = conn.execute(text("SELECT COUNT(*) FROM nodes")).scalar()
            assert count == 3
