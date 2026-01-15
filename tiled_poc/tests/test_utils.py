# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest",
#     "ruamel.yaml",
# ]
# ///
"""
Unit tests for utils module.

These tests verify utility functions like artifact key generation.
No Tiled server required.

Run with:
    uv run --with pytest pytest tests/test_utils.py -v
"""

import sys
from pathlib import Path

import pytest

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from utils import make_artifact_key


class TestMakeArtifactKey:
    """Tests for make_artifact_key()."""

    def test_mh_curve_powder_30T(self):
        row = {"type": "mh_curve", "axis": "powder", "Hmax_T": 30}
        assert make_artifact_key(row) == "mh_powder_30T"

    def test_mh_curve_x_7T(self):
        row = {"type": "mh_curve", "axis": "x", "Hmax_T": 7}
        assert make_artifact_key(row) == "mh_x_7T"

    def test_mh_curve_y_30T(self):
        row = {"type": "mh_curve", "axis": "y", "Hmax_T": 30}
        assert make_artifact_key(row) == "mh_y_30T"

    def test_mh_curve_z_7T(self):
        row = {"type": "mh_curve", "axis": "z", "Hmax_T": 7}
        assert make_artifact_key(row) == "mh_z_7T"

    def test_ins_powder_12meV(self):
        row = {"type": "ins_powder", "Ei_meV": 12}
        assert make_artifact_key(row) == "ins_12meV"

    def test_ins_powder_25meV(self):
        row = {"type": "ins_powder", "Ei_meV": 25}
        assert make_artifact_key(row) == "ins_25meV"

    def test_gs_state(self):
        row = {"type": "gs_state"}
        assert make_artifact_key(row) == "gs_state"

    def test_with_prefix_path(self):
        row = {"type": "mh_curve", "axis": "powder", "Hmax_T": 30}
        assert make_artifact_key(row, prefix="path_") == "path_mh_powder_30T"

    def test_with_prefix_empty(self):
        row = {"type": "gs_state"}
        assert make_artifact_key(row, prefix="") == "gs_state"

    def test_unknown_type_raises(self):
        row = {"type": "unknown_artifact"}
        with pytest.raises(ValueError, match="Unknown artifact type"):
            make_artifact_key(row)

    def test_handles_float_Hmax_T(self):
        """Test that float Hmax_T values are converted to int."""
        row = {"type": "mh_curve", "axis": "powder", "Hmax_T": 30.0}
        assert make_artifact_key(row) == "mh_powder_30T"

    def test_handles_float_Ei_meV(self):
        """Test that float Ei_meV values are converted to int."""
        row = {"type": "ins_powder", "Ei_meV": 12.0}
        assert make_artifact_key(row) == "ins_12meV"
