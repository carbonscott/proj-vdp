## Environment Setup

Set these environment variables before running any commands:

```bash
export PROJ_VDP=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp
export VDP_DATA=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp
export TILED_DIR=/sdf/data/lcls/ds/prj/prjcwang31/results/software/tiled
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE
```

Use `uv` to run python programs. The UV_CACHE_DIR avoids repeated package downloads.

## Project Overview

This is the **VDP Hierarchical Tiled Catalog** - a clean implementation using Tiled's container structure where:
- **Hamiltonians are containers** with physics parameters (Ja, Jb, Jc, Dc) as metadata
- **Artifacts are children** of their parent Hamiltonian (gs_state, mh_curve, ins_powder)
- **Keys are human-readable**: `H_636ce3e4/mh_powder_30T` instead of UUIDs

## Directory Structure

```
proj-vdp/
├── CLAUDE.md              # This file
├── .gitignore
├── tiled_poc/             # Main implementation
│   ├── config.yml         # Server configuration
│   ├── README.md          # Implementation details
│   ├── scripts/           # Core scripts
│   │   ├── bulk_register.py     # Bulk registration (production)
│   │   ├── register_catalog.py  # Incremental registration
│   │   ├── query_manifest.py    # Discovery API
│   │   ├── config.py            # Configuration module
│   │   └── utils.py             # Shared utilities
│   ├── examples/          # Demo scripts
│   │   ├── demo_mh_dataset.py          # Marimo notebook demo
│   │   ├── demo_mh_dataset_with_query.py  # Query-based demo
│   │   └── demo_dual_mode.py           # Dual-mode CLI demo
│   └── tests/             # Test suite
│       ├── conftest.py           # Shared pytest fixtures
│       ├── test_config.py        # Configuration unit tests
│       ├── test_utils.py         # Utility unit tests
│       ├── test_registration.py  # Registration integration tests
│       └── test_data_retrieval.py # Mode A/B integration tests
├── docs/                  # Documentation
│   ├── HANDOFF_02.md
│   ├── HANDOFF_03.md
│   ├── LESSONS_LEARNED.md
│   └── ...
├── archive/               # Old versions (not tracked in git)
└── data -> ...            # Symlink to VDP data
```

## How to Run

**Terminal 1 - Start server:**
```bash
cd $PROJ_VDP/tiled_poc
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
```

**Terminal 2 - Register data:**
```bash
cd $PROJ_VDP/tiled_poc

# Bulk registration (recommended for initial load)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with canonicaljson --with 'ruamel.yaml' \
  python scripts/bulk_register.py -n 1000

# Incremental registration (for updates)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python scripts/register_catalog.py
```

**Run marimo notebook (interactive demo):**
```bash
cd $PROJ_VDP/tiled_poc
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with marimo --with matplotlib --with torch --with 'ruamel.yaml' \
  marimo edit examples/demo_mh_dataset.py
```

**Run CLI demo:**
```bash
cd $PROJ_VDP/tiled_poc
uv run --with 'tiled[server]' --with pandas --with h5py --with 'ruamel.yaml' \
  python examples/demo_dual_mode.py
```

## Running Tests

```bash
cd $PROJ_VDP/tiled_poc

# Unit tests (no server required)
uv run --with pytest pytest tests/test_config.py tests/test_utils.py -v

# Integration tests (requires running server with data)
uv run --with pytest pytest tests/ -v
```

## Architecture

```
/                           <- Root
  /H_636ce3e4/              <- Container (Hamiltonian)
      metadata: {Ja_meV, Jb_meV, Jc_meV, Dc_meV, spin_s, g_factor, path_*}
      gs_state              <- Array (3x8)
      mh_x_7T, mh_y_7T, mh_z_7T, mh_powder_7T    <- Arrays (200,)
      mh_x_30T, mh_y_30T, mh_z_30T, mh_powder_30T
      ins_12meV, ins_25meV  <- Arrays (600x400)
```

**Dual-mode access:**
- **Mode A (Expert):** Query metadata for paths, load directly from HDF5
- **Mode B (Visualizer):** Access arrays via Tiled adapters (chunked HTTP)

## Data Sources

**Manifests (Parquet):**
```
$VDP_DATA/data/schema_v1/manifest_hamiltonians_*.parquet  (10K rows)
$VDP_DATA/data/schema_v1/manifest_artifacts_*.parquet    (110K rows)
```

**HDF5 files:**
```
$VDP_DATA/data/schema_v1/artifacts/  (110K files, 111 GB)
```

## Julia vs Python Data Loading

**Julia (direct HDF5):**
```julia
X, h_grid, Θ, meta = build_mh_dataset(axis="powder", Hmax_T=30.0)
```

**Python (via Tiled - Mode A):**
```python
from tiled.client import from_uri
from query_manifest import build_mh_dataset

client = from_uri("http://localhost:8005", api_key="secret")
X, h_grid, Theta, manifest = build_mh_dataset(client, axis="powder", Hmax_T=30)
```

Both return:
- `X`: (n_curves, n_points) normalized magnetization curves
- `h_grid`: (n_points,) reduced field values [0, 1]
- `Theta/Θ`: (n_curves, 6) parameters [Ja, Jb, Jc, Dc, spin_s, g_factor]
- `manifest/meta`: metadata for each curve

## Related Documentation

| Document | Path |
|----------|------|
| Implementation guide | `docs/HANDOFF_02.md` |
| Lessons learned | `docs/LESSONS_LEARNED.md` |
| Version comparison | `docs/VERSION_COMPARISON.md` |
