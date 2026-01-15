# V6a PostgreSQL Setup Notes

Experience report from setting up Tiled v6a with PostgreSQL backend.

---

## Quick Start

### Prerequisites
- PostgreSQL running on port 5433 (see `docs/INSTALL-POSTGRES.md`)
- Database `vdp_catalog` exists

### Start the PostgreSQL-backed Tiled Server

**Terminal 1:**
```bash
cd $PROJ_VDP/tiled_poc_v6a
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE

uv run --with 'tiled[server]' --with asyncpg \
  tiled serve config config_postgres.yml --api-key secret
```

Server runs on **port 8007**.

### Run Registration

**Terminal 2:**
```bash
cd $PROJ_VDP/tiled_poc_v6a
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE

# 10 Hamiltonians (test)
TILED_URL=http://localhost:8007 VDP_MAX_HAMILTONIANS=10 \
  uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python -u register_catalog.py

# Full dataset (10K Hamiltonians)
TILED_URL=http://localhost:8007 VDP_MAX_HAMILTONIANS=10000 \
  uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py --with 'ruamel.yaml' \
  python -u register_catalog.py
```

---

## Setup Issues Encountered

### Issue: `btree_gin` Extension Conflict

**Error:**
```
ProgrammingError: extension "btree_gin" already exists
[SQL: create extension btree_gin;]
```

**Cause:** Tiled's catalog initialization runs `CREATE EXTENSION btree_gin;` without `IF NOT EXISTS`. If the extension was pre-created (e.g., during PostgreSQL setup per `INSTALL-POSTGRES.md` Step 8), this fails.

**Solution:** Drop the extension before running Tiled for the first time:

```bash
source /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/postgres/setup_postgres.sh

PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "DROP EXTENSION btree_gin;"
```

Then either:
1. Start the server with `init_if_not_exists: true` in config, OR
2. Manually initialize:
   ```bash
   uv run --with 'tiled[server]' --with asyncpg \
     tiled catalog init --if-not-exists \
     'postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog'
   ```

---

## Speed Observations

### Test Run: 10 Hamiltonians

| Metric | Value |
|--------|-------|
| Hamiltonians registered | 10 |
| Artifacts registered | 110 |
| Total time | 3.9 seconds |
| Registration rate | **~2.6 Hamiltonians/sec** |
| Artifacts/sec | ~28/sec |

### Full Run: 10,000 Hamiltonians (Actual Results)

| Metric | Value |
|--------|-------|
| Hamiltonians registered | 10,000 |
| Artifacts registered | 110,000 |
| Total time | **2646.5 seconds (~44 minutes)** |
| Average rate | **3.8 Hamiltonians/sec** |
| Nodes/sec | ~45/sec |

**Key finding:** Rate *improved* during ingestion (3.2 → 3.8 H/sec), unlike SQLite which degrades.

---

## Database State After Full Registration (10K Hamiltonians)

```bash
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c \
  "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
```

| Table | Rows | Size | Description |
|-------|------|------|-------------|
| nodes | 119,990 | 96 MB | 10K Hamiltonians + 110K artifacts + root |
| nodes_closure | 350,041 | 32 MB | Hierarchy relationships |
| assets | 110,020 | 48 MB | File URIs (one per artifact) |
| data_sources | 110,014 | 23 MB | How to read each file |
| data_source_asset_association | 110,018 | 12 MB | Links data_sources to assets |
| structures | 3 | 32 KB | Unique array shapes (deduplicated) |
| alembic_version | 1 | 24 KB | Schema migration version |
| revisions | 0 | 32 KB | Data revisions (unused) |

**Total database size: ~211 MB**

---

## Speed Degradation Analysis

### Results (Full 10K Ingestion - January 2026)

**Finding: No degradation observed - rate actually improved!**

| Range | Rate (H/sec) | Notes |
|-------|--------------|-------|
| 0-100 | 3.5 | Initial warmup |
| 100-1,000 | 3.5-3.6 | Stable |
| 1,000-5,000 | 3.6-3.7 | Slight improvement |
| 5,000-10,000 | 3.7-3.8 | Continued improvement |
| Final | **3.8** | Best rate at end |

### Analysis

Unlike SQLite (which degrades from ~55/sec to ~1.7/sec), PostgreSQL maintained consistent performance:

| Database | Start Rate | End Rate | Degradation |
|----------|------------|----------|-------------|
| SQLite | 55 H/sec | 1.7 H/sec | **32x slower** |
| PostgreSQL | 3.5 H/sec | 3.8 H/sec | **None (improved)** |

**Why PostgreSQL performs better:**
1. Better B-tree implementation for large indexes
2. Query planner optimizes for table statistics
3. Connection pooling reduces overhead
4. WAL-based writes more efficient than SQLite's journal

### PostgreSQL vs SQLite Comparison

| Metric | SQLite | PostgreSQL |
|--------|--------|------------|
| Total time (10K) | ~90 min | **44 min** |
| Rate degradation | 32x slower | None |
| Final rate | 1.7 H/sec | 3.8 H/sec |
| Database size | 192 MB | 211 MB |

---

## Configuration Reference

### config_postgres.yml

```yaml
uvicorn:
  host: "127.0.0.1"
  port: 8007

trees:
  - path: /
    tree: catalog
    args:
      uri: "postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog"
      init_if_not_exists: true
      writable_storage: "/sdf/.../tiled_poc_v6a/storage"
      readable_storage:
        - "/sdf/.../vdp/data/schema_v1"
```

### Key Differences from SQLite Config

| Setting | SQLite | PostgreSQL |
|---------|--------|------------|
| Port | 8005 | 8007 |
| URI | `sqlite:///catalog.db` | `postgresql+asyncpg://...` |
| Extra package | (none) | `asyncpg` |

---

## Useful Commands

### Check PostgreSQL Status
```bash
source /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/postgres/setup_postgres.sh
pg_ctl -D $PG_DATA status
```

### Query Node Counts
```bash
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c \
  "SELECT structure_family, COUNT(*) FROM nodes GROUP BY structure_family;"
```

### Check Table Sizes
```bash
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "
SELECT relname as table,
       pg_size_pretty(pg_total_relation_size(relid)) as size,
       n_live_tup as rows
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;"
```

### Reset Database (Start Fresh)
```bash
# Drop all tables and re-initialize
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO vdp_admin;"

# Re-initialize Tiled catalog
uv run --with 'tiled[server]' --with asyncpg \
  tiled catalog init 'postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog'
```

---

## PostgreSQL Advantages for Bulk Loading

PostgreSQL supports `DISABLE TRIGGER ALL` which SQLite does not. This enables faster bulk loading by:

1. Disabling closure table triggers during insert
2. Bulk inserting nodes without per-row trigger overhead
3. Rebuilding closure table with set-based SQL
4. Re-enabling triggers

See `docs/v6a-bulk-registration-options.md` for implementation details. Expected speedup: **50-100x** for initial bulk load.

---

## Related Documentation

- `docs/INSTALL-POSTGRES.md` - PostgreSQL installation without root
- `docs/v6a-bulk-registration-options.md` - Bulk loading optimization strategies
- `tiled_poc_v6a/README.md` - V6a general usage
