# VDP Hierarchical Tiled Catalog

This implementation provides **two access modes** for VDP data:
- **Mode A (Expert):** Query metadata → get HDF5 paths → load directly with h5py
- **Mode B (Visualizer):** Access arrays as Tiled children via HTTP adapters

## Quick Start

### Step 1: Set Environment Variables

```bash
export PROJ_VDP=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp
export VDP_DATA=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE
```

### Step 2: Start the Tiled Server FIRST

**Important:** The registration script connects to the server via HTTP API. The server must be running before registration.

```bash
cd $PROJ_VDP/tiled_poc

# Start server (creates empty catalog.db if not exists)
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
```

The server runs on **port 8005** (configured in `config.yml`).

**To verify the server is running:**
```bash
lsof -i :8005 | grep LISTEN
# Or
curl -s http://localhost:8005/api/v1 | head
```

### Step 3: Run Data Registration (in another terminal)

```bash
cd $PROJ_VDP/tiled_poc

# Register 10 Hamiltonians (default)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python scripts/register_catalog.py

# Register more Hamiltonians (e.g., all 10,000)
VDP_MAX_HAMILTONIANS=10000 uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python scripts/register_catalog.py
```

## Full Registration (All 10,000 Hamiltonians)

For a fresh full registration:

```bash
cd $PROJ_VDP/tiled_poc

# 1. Stop any running server on port 8005
lsof -ti :8005 | xargs kill 2>/dev/null || true

# 2. Remove old database (optional - backup first if needed)
mv catalog.db catalog.db.bak 2>/dev/null || true

# 3. Start fresh server (creates new catalog.db)
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret &
sleep 5  # Wait for server to start

# 4. Run full registration
VDP_MAX_HAMILTONIANS=10000 uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python scripts/register_catalog.py
```

---

## Bulk Registration (Fast Alternative)

For maximum speed on large datasets, use `bulk_register.py` which bypasses the HTTP layer and writes directly to SQLite.

### When to Use Bulk Registration

| Use Case | Script | Speed |
|----------|--------|-------|
| Incremental updates | `scripts/register_catalog.py` | ~5 nodes/sec |
| Fresh bulk load (1K+) | `scripts/bulk_register.py` | ~2,250 nodes/sec |

### How It Works

`bulk_register.py` uses direct SQLAlchemy with a trigger disable/rebuild pattern:
1. Disables the closure table trigger
2. Bulk inserts all nodes in a single transaction
3. Rebuilds the closure table with set-based SQL
4. Re-enables the trigger for future incremental updates

### Running Bulk Registration

**No server needed** - the script accesses the database directly.

#### CLI Options

```
python scripts/bulk_register.py [OPTIONS]

Options:
  -n, --max-hamiltonians NUM   Number of Hamiltonians to register (default: 10)
  -o, --output DB_NAME         Output database filename (default: catalog.db)
  --force                      Overwrite existing database without prompting
  -h, --help                   Show help message
```

#### Examples

```bash
cd $PROJ_VDP/tiled_poc

# Show help
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with canonicaljson --with 'ruamel.yaml' \
  python scripts/bulk_register.py --help

# Bulk register 10 Hamiltonians (default)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with canonicaljson --with 'ruamel.yaml' \
  python scripts/bulk_register.py

# Bulk register 1000 Hamiltonians
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with canonicaljson --with 'ruamel.yaml' \
  python scripts/bulk_register.py -n 1000

# Bulk register all 10,000 Hamiltonians to a specific database (~53 seconds)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with canonicaljson --with 'ruamel.yaml' \
  python scripts/bulk_register.py -n 10000 -o catalog-bulk.db
```

Environment variables `VDP_MAX_HAMILTONIANS` and `CATALOG_DB` still work as fallbacks for backwards compatibility.

### Performance Comparison

| Dataset | HTTP Registration | Bulk Registration | Speedup |
|---------|-------------------|-------------------|---------|
| 10 Hamiltonians | ~2 sec | 0.1 sec | 20x |
| 1,000 Hamiltonians | ~3.3 min | 5 sec | 40x |
| 10,000 Hamiltonians | ~90 min | 53 sec | **100x** |

### After Bulk Registration

Start the server to query the catalog:

```bash
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
```

**Note:** `bulk_register.py` creates a fresh database. If you have existing data, back it up first.

---

## Common Issues

### "Server error 500" during registration
**Cause:** Database missing or corrupted while server is running.
**Fix:** Stop server, remove `catalog.db`, restart server (it will create a fresh database).

### "Server not running" error
**Fix:** Start the server first (Step 2), then run registration.

### Port 8005 already in use
**Fix:**
```bash
# Find and kill existing process
lsof -ti :8005 | xargs kill
```

## Directory Structure

```
tiled_poc/
├── config.yml                          # Server configuration (port 8005)
├── catalog.db                          # SQLite database (created by server)
├── scripts/
│   ├── config.py                       # Configuration loader
│   ├── utils.py                        # Shared utilities
│   ├── register_catalog.py             # HTTP-based registration
│   ├── bulk_register.py                # SQLAlchemy bulk registration
│   └── query_manifest.py               # Mode A: query → direct HDF5
├── examples/
│   ├── demo_dual_mode.py               # CLI demo of both modes
│   ├── demo_mh_dataset.py              # Marimo notebook demo
│   └── demo_mh_dataset_with_query.py   # Marimo + query_manifest API
└── tests/
    ├── conftest.py                     # Shared pytest fixtures
    ├── test_config.py                  # Configuration unit tests
    ├── test_utils.py                   # Utility unit tests
    ├── test_registration.py            # Registration integration tests
    └── test_data_retrieval.py          # Mode A/B integration tests
```

## Configuration

Edit `config.yml` to change:
- Server port (default: 8005)
- Database location
- Data source paths
- Default registration count (`max_hamiltonians: 10`)

Use `VDP_MAX_HAMILTONIANS` environment variable to override the default count.

## Data Access After Registration

```python
from tiled.client import from_uri

client = from_uri("http://localhost:8005", api_key="secret")

# List Hamiltonians
print(list(client.keys())[:5])

# Access a Hamiltonian container
h = client["H_636ce3e4"]

# Mode A: Get artifact path from metadata
path = h.metadata["path_mh_powder_30T"]

# Mode B: Access array child directly
arr = h["mh_powder_30T"][:]
```

## Interactive Demo (Marimo Notebook)

Run the interactive Marimo notebook to explore the dual-mode access patterns:

```bash
cd $PROJ_VDP/tiled_poc

# Make sure server is running first (in another terminal)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with marimo --with matplotlib --with torch --with 'ruamel.yaml' \
  marimo edit examples/demo_mh_dataset.py
```

The notebook demonstrates:
- **Mode A (Expert):** `query_manifest()` → direct HDF5 loading for ML pipelines
- **Mode B (Visualizer):** Tiled adapter access for interactive exploration
- **Performance comparison** between modes
- **PyTorch DataLoader** integration
- **M(H) curve visualization**

## Running Tests

The test suite includes unit tests (no server needed) and integration tests (require running server).

### Unit Tests

```bash
cd $PROJ_VDP/tiled_poc

# Run unit tests (no server required)
uv run --with pytest pytest tests/test_config.py tests/test_utils.py -v
```

### Integration Tests

```bash
# 1. Start server in one terminal
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret

# 2. Register test data (small subset)
VDP_MAX_HAMILTONIANS=5 uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python scripts/register_catalog.py

# 3. Run integration tests
uv run --with pytest --with 'ruamel.yaml' pytest tests/ -v
```

### Test Categories

| Test File | Type | Description |
|-----------|------|-------------|
| `test_config.py` | Unit | Configuration loading, path resolution |
| `test_utils.py` | Unit | Artifact key generation |
| `test_registration.py` | Integration | HTTP and bulk registration methods |
| `test_data_retrieval.py` | Integration | Mode A/B data access, equivalence |

## Expected Database Size (SQLite)

| Hamiltonians | Approximate Size | Registration Time |
|--------------|------------------|-------------------|
| 10 | ~300 KB | ~2 sec |
| 1,000 | ~20 MB | ~5 min |
| 10,000 | ~192 MB | ~90 min |

**Note:** Registration rate decreases as database grows due to SQLite B-tree overhead (starts at ~55/sec, drops to ~1.7/sec).

---

## PostgreSQL Backend (Recommended for Production)

For better performance with large datasets, use PostgreSQL instead of SQLite.

### Prerequisites

PostgreSQL must be installed and running. See `docs/INSTALL-POSTGRES.md` for setup instructions.

### PostgreSQL Quick Start

**Terminal 1 - Start PostgreSQL server (if not running):**
```bash
source /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/postgres/setup_postgres.sh
pg_ctl -D $PG_DATA -l $PG_LOG/postgres.log start
```

**Terminal 2 - Start Tiled with PostgreSQL:**
```bash
cd $PROJ_VDP/tiled_poc

uv run --with 'tiled[server]' --with asyncpg \
  tiled serve config config_postgres.yml --api-key secret
```

Server runs on **port 8007**.

**Terminal 3 - Run registration:**
```bash
cd $PROJ_VDP/tiled_poc

# Register 10 Hamiltonians (test)
TILED_URL=http://localhost:8007 VDP_MAX_HAMILTONIANS=10 \
  uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python scripts/register_catalog.py

# Register all 10K Hamiltonians
TILED_URL=http://localhost:8007 VDP_MAX_HAMILTONIANS=10000 \
  uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python scripts/register_catalog.py
```

### Clean PostgreSQL Registration

To start fresh with PostgreSQL:

```bash
# 1. Reset database
source /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/postgres/setup_postgres.sh
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO vdp_admin;"

# 2. Initialize Tiled catalog
uv run --with 'tiled[server]' --with asyncpg \
  tiled catalog init 'postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog'

# 3. Start server and run registration (as shown above)
```

### PostgreSQL vs SQLite

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Config file | `config.yml` | `config_postgres.yml` |
| Port | 8005 | 8007 |
| Extra package | - | `asyncpg` |
| Bulk loading | Limited | `DISABLE TRIGGER` support |
| Concurrent access | Limited | Full support |

### PostgreSQL Documentation

See `docs/V6A-POSTGRES-NOTES.md` for detailed setup notes, performance observations, and troubleshooting.
