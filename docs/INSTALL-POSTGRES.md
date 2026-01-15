# Installing PostgreSQL Without Root Access

Instructions for setting up a local PostgreSQL instance for VDP/Tiled development.

**Why PostgreSQL?**
- Native `DISABLE TRIGGER` support for bulk data loading
- Better performance for large catalogs (10K+ Hamiltonians)
- Production-ready features (concurrent connections, better indexing)

---

## Prerequisites

- Linux x86_64 system (RHEL/CentOS 8 or similar)
- ~500 MB disk space
- No root/sudo access required
- Internet access (for downloading packages)

---

## Installation Method: Micromamba + Conda-Forge

The original EnterpriseDB binary downloads are blocked (403 Forbidden), and GitHub-hosted binaries require libraries (OpenSSL 3.x, musl libc) not available on SLAC systems. The working solution is to use **micromamba** to install PostgreSQL from conda-forge.

---

## Step 1: Set Up Directory Structure

```bash
# Set base directory (adjust as needed)
export PG_BASE=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/postgres

# Create directories
mkdir -p $PG_BASE
cd $PG_BASE
```

---

## Step 2: Download and Install Micromamba

Micromamba is a fast, standalone package manager that can install conda packages without a full Anaconda/Miniconda installation.

```bash
# Download micromamba
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj -C $PG_BASE bin/micromamba

# Verify it works
$PG_BASE/bin/micromamba --version
# Should show: 2.x.x
```

---

## Step 3: Install PostgreSQL via Micromamba

```bash
# Set up micromamba environment
export MAMBA_ROOT_PREFIX=$PG_BASE/mamba
mkdir -p $PG_BASE/mamba_cache
export CONDA_PKGS_DIRS=$PG_BASE/mamba_cache

# Install PostgreSQL 16 from conda-forge
$PG_BASE/bin/micromamba create -n pg16 postgresql=16 -c conda-forge -y --root-prefix=$MAMBA_ROOT_PREFIX

# This installs PostgreSQL and all dependencies (~35 MB download)
# Installation location: $PG_BASE/mamba/envs/pg16/
```

---

## Step 4: Create Environment Setup Script

```bash
# Create setup script
cat > $PG_BASE/setup_postgres.sh << 'EOF'
#!/bin/bash
export PG_BASE=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/postgres
export PG_HOME=$PG_BASE/mamba/envs/pg16
export PG_DATA=$PG_BASE/data
export PG_LOG=$PG_BASE/logs
export PATH=$PG_HOME/bin:$PATH
export LD_LIBRARY_PATH=$PG_HOME/lib:$LD_LIBRARY_PATH

# PostgreSQL connection defaults
export PGHOST=localhost
export PGPORT=5433
export PGUSER=vdp_admin
export PGDATABASE=vdp_catalog
EOF

# Make it executable
chmod +x $PG_BASE/setup_postgres.sh

# Source it
source $PG_BASE/setup_postgres.sh

# Verify PostgreSQL is accessible
which initdb
initdb --version
# Should show: initdb (PostgreSQL) 16.x
```

**Note:** We use port `5433` (not default `5432`) to avoid conflicts with any system PostgreSQL.

---

## Step 5: Initialize the Database

```bash
# Source environment (if not already done)
source $PG_BASE/setup_postgres.sh

# Create data and log directories
mkdir -p $PG_DATA $PG_LOG

# Initialize database cluster with password file (non-interactive)
echo "vdp_secret" > /tmp/pgpass_$$
initdb -D $PG_DATA \
    --auth=scram-sha-256 \
    --username=vdp_admin \
    --pwfile=/tmp/pgpass_$$ \
    --encoding=UTF8 \
    --locale=C
rm /tmp/pgpass_$$

# Expected output:
# Success. You can now start the database server using:
#     pg_ctl -D /path/to/data -l logfile start
```

---

## Step 6: Configure PostgreSQL

Edit the configuration for local development:

```bash
# Append VDP-specific settings
cat >> $PG_DATA/postgresql.conf << 'EOF'

# VDP Custom Settings
listen_addresses = 'localhost'
port = 5433
max_connections = 50
shared_buffers = 256MB
work_mem = 64MB
maintenance_work_mem = 128MB

# Logging
log_destination = 'stderr'
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'

# Performance for bulk loading
wal_level = minimal
max_wal_senders = 0
fsync = on
synchronous_commit = off
EOF
```

---

## Step 7: Start PostgreSQL

```bash
# Source environment
source $PG_BASE/setup_postgres.sh

# Start the server
pg_ctl -D $PG_DATA -l $PG_LOG/postgres.log start

# Expected output:
# waiting for server to start.... done
# server started

# Verify it's running
pg_ctl -D $PG_DATA status

# Should show:
# pg_ctl: server is running (PID: XXXXX)
```

---

## Step 8: Create the Tiled Database

```bash
# Source environment
source $PG_BASE/setup_postgres.sh

# Create database (use PGPASSWORD for non-interactive)
PGPASSWORD=vdp_secret psql -U vdp_admin -d postgres -c "CREATE DATABASE vdp_catalog;"

# Add btree_gin extension for advanced indexing
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "CREATE EXTENSION IF NOT EXISTS btree_gin;"
```

---

## Step 9: Verify Installation

```bash
# Source environment
source $PG_BASE/setup_postgres.sh

# Test connection
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "SELECT version();"

# Expected output (similar to):
# PostgreSQL 16.11 on x86_64-conda-linux-gnu, compiled by gcc...

# Test from Python (using uv)
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE
uv run --with psycopg2-binary python3 -c "
import psycopg2
conn = psycopg2.connect(
    host='localhost',
    port=5433,
    user='vdp_admin',
    password='vdp_secret',
    dbname='vdp_catalog'
)
print('Connection successful!')
conn.close()
"
```

---

## Step 10: Configure Tiled to Use PostgreSQL

Update `tiled_poc_v6a/config.yml`:

```yaml
# Before (SQLite)
database:
  uri: sqlite:///./catalog.db

# After (PostgreSQL)
database:
  uri: postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog
```

**Required Python packages:**

```bash
# Install PostgreSQL drivers (with uv)
uv run --with psycopg2-binary --with asyncpg python -c "print('drivers installed')"

# Or with pip
pip install psycopg2-binary asyncpg
```

---

## Using PostgreSQL with Tiled

This section describes the complete workflow for using PostgreSQL as Tiled's catalog backend.

### Multi-Terminal Workflow

Running the VDP system requires three terminals:

| Terminal | Purpose | Command |
|----------|---------|---------|
| 1 | PostgreSQL server | `pg_ctl -D $PG_DATA start` |
| 2 | Tiled server | `tiled serve config config.yml` |
| 3 | Registration/queries | `python register_catalog.py` |

### Complete Workflow Example

**Terminal 1: Start PostgreSQL**

```bash
# Set up environment
source /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/postgres/setup_postgres.sh

# Start PostgreSQL (if not already running)
pg_ctl -D $PG_DATA -l $PG_LOG/postgres.log start

# Verify it's running
pg_ctl -D $PG_DATA status
```

**Terminal 2: Configure and Start Tiled**

First, create or update `config.yml` to use PostgreSQL:

```yaml
# tiled_poc_v6a/config.yml
trees:
  - path: /
    tree: catalog
    args:
      uri: "postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog"
      init_if_not_exists: true
      writable_storage: "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc_v6a/storage"
      readable_storage:
        - "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1"

authentication:
  allow_anonymous_access: true
```

Then start the Tiled server:

```bash
cd /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc_v6a
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE

uv run --with 'tiled[server]' --with asyncpg \
  tiled serve config config.yml --api-key secret --port 8005

# Server will be available at http://localhost:8005
```

**Terminal 3: Register Data**

```bash
cd /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc_v6a
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE

# Register 10 Hamiltonians (default)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python register_catalog.py

# Register more Hamiltonians
VDP_MAX_HAMILTONIANS=100 uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python register_catalog.py

# For large-scale registration (1000+)
VDP_MAX_HAMILTONIANS=1000 uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python register_catalog.py
```

### Querying Data via Python

```python
from tiled.client import from_uri

# Connect to Tiled server
client = from_uri("http://localhost:8005", api_key="secret")

# Browse the catalog hierarchy
print(list(client))  # List all Hamiltonians
# ['H_636ce3e4', 'H_7a8b9c0d', ...]

# Access a specific Hamiltonian
h = client["H_636ce3e4"]

# View metadata (physics parameters)
print(h.metadata)
# {'Ja_meV': -0.5, 'Jb_meV': 0.2, 'Jc_meV': 0.1, 'Dc_meV': 0.05, ...}

# List artifacts
print(list(h))
# ['gs_state', 'mh_powder_7T', 'mh_powder_30T', 'ins_12meV', ...]

# Load an array
mh_curve = h["mh_powder_30T"][:]  # Full array
print(mh_curve.shape)  # (200,)

# Sliced access (only transfers requested data)
ins_slice = h["ins_12meV"][100:200, 50:150]
print(ins_slice.shape)  # (100, 100)
```

### Building M(H) Datasets

Use the provided `load_mh_dataset.py` for ML workflows:

```python
from load_mh_dataset import build_mh_dataset

# Build dataset (equivalent to Julia's mh_dataset.jl)
X, h_grid, Theta, meta = build_mh_dataset(
    client,
    axis="powder",   # or "x", "y", "z"
    Hmax_T=30        # 7 or 30
)

print(X.shape)      # (n_curves, 200) - magnetization curves
print(Theta.shape)  # (n_curves, 6) - [Ja, Jb, Jc, Dc, spin_s, g_factor]
```

### Switching Between SQLite and PostgreSQL

**SQLite (development):**
```yaml
uri: "sqlite:////path/to/catalog.db"
```

**PostgreSQL (production):**
```yaml
uri: "postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog"
```

When to use each:

| Use Case | Recommended Backend |
|----------|-------------------|
| Quick testing, single user | SQLite |
| Bulk loading 10K+ nodes | PostgreSQL |
| Multiple concurrent users | PostgreSQL |
| Production deployment | PostgreSQL |

### Bulk Loading for Production

For registering 10K+ Hamiltonians, use direct database access with trigger management:

```python
# Direct database access (bypasses HTTP overhead)
from sqlalchemy import create_engine, text

engine = create_engine("postgresql://vdp_admin:vdp_secret@localhost:5433/vdp_catalog")

with engine.connect() as conn:
    # Disable triggers for bulk insert
    conn.execute(text("ALTER TABLE nodes DISABLE TRIGGER ALL"))

    # Bulk insert nodes...
    # (use SQLAlchemy Core insert for best performance)

    # Re-enable triggers
    conn.execute(text("ALTER TABLE nodes ENABLE TRIGGER ALL"))

    # Rebuild closure table
    conn.execute(text("""
        INSERT INTO nodes_closure (ancestor, descendant, depth)
        SELECT id, id, 0 FROM nodes WHERE id NOT IN (SELECT descendant FROM nodes_closure)
    """))

    conn.commit()
```

**Performance comparison:**

| Approach | Speed | Time for 10K Hamiltonians |
|----------|-------|--------------------------|
| HTTP per-node (current) | 1x | ~33 minutes |
| SQLAlchemy bulk insert | 10-50x | ~1-3 minutes |
| Disable triggers + rebuild | 50-100x | ~20-40 seconds |

### Monitoring the Database

```bash
# Check table sizes
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "
SELECT relname as table,
       pg_size_pretty(pg_total_relation_size(relid)) as size,
       n_live_tup as rows
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;
"

# Check active connections
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "
SELECT count(*) as connections FROM pg_stat_activity WHERE datname = 'vdp_catalog';
"
```

---

## Common Commands

### Start/Stop/Restart

```bash
# Source environment first
source $PG_BASE/setup_postgres.sh

# Start
pg_ctl -D $PG_DATA -l $PG_LOG/postgres.log start

# Stop
pg_ctl -D $PG_DATA stop

# Restart
pg_ctl -D $PG_DATA restart

# Check status
pg_ctl -D $PG_DATA status
```

### View Logs

```bash
# Recent log entries
tail -f $PG_LOG/postgres.log

# Or check pg_log directory
tail -f $PG_DATA/log/postgresql-*.log
```

### Connect to Database

```bash
# Interactive shell
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog

# Run a query
PGPASSWORD=vdp_secret psql -U vdp_admin -d vdp_catalog -c "SELECT count(*) FROM nodes;"
```

### Reset Database (Start Fresh)

```bash
# Stop server
pg_ctl -D $PG_DATA stop

# Remove data (DESTRUCTIVE!)
rm -rf $PG_DATA

# Re-initialize
mkdir -p $PG_DATA
echo "vdp_secret" > /tmp/pgpass_$$
initdb -D $PG_DATA --auth=scram-sha-256 --username=vdp_admin --pwfile=/tmp/pgpass_$$ --encoding=UTF8 --locale=C
rm /tmp/pgpass_$$

# Reconfigure and start (repeat Steps 6-8)
```

---

## Troubleshooting

### "Connection refused"

```bash
# Check if server is running
pg_ctl -D $PG_DATA status

# Check if port is correct
grep "^port" $PG_DATA/postgresql.conf

# Check logs
tail -50 $PG_LOG/postgres.log
```

### "Password authentication failed"

```bash
# Reset password
PGPASSWORD=vdp_secret psql -U vdp_admin -d postgres -c "ALTER USER vdp_admin PASSWORD 'new_password';"
```

### "Address already in use"

Another process is using port 5433. Either:
1. Change port in `postgresql.conf` to 5434 or another free port
2. Find and stop the conflicting process: `lsof -i :5433`

### "Could not create shared memory segment"

System shared memory limits too low. Add to `postgresql.conf`:
```
shared_buffers = 128MB  # Reduce from 256MB
```

### Permission Denied Errors

Ensure all directories are owned by your user:
```bash
ls -la $PG_BASE
# Should all be owned by your username
```

### Micromamba Cache Errors

If you see cache lock errors, they can usually be ignored. To fix:
```bash
# Point cache to a writable location
export CONDA_PKGS_DIRS=$PG_BASE/mamba_cache
```

---

## Cleanup / Uninstall

To completely remove PostgreSQL:

```bash
# Stop server if running
source $PG_BASE/setup_postgres.sh
pg_ctl -D $PG_DATA stop 2>/dev/null

# Remove everything
rm -rf $PG_BASE

# Remove from PATH (edit ~/.bashrc if you added it there)
```

---

## Quick Reference

| Item | Value |
|------|-------|
| Install location | `$PG_BASE/mamba/envs/pg16` |
| Data directory | `$PG_BASE/data` |
| Log directory | `$PG_BASE/logs` |
| Port | 5433 |
| Admin user | vdp_admin |
| Password | vdp_secret |
| Database name | vdp_catalog |
| Connection string | `postgresql://vdp_admin:vdp_secret@localhost:5433/vdp_catalog` |
| Async connection | `postgresql+asyncpg://vdp_admin:vdp_secret@localhost:5433/vdp_catalog` |

---

## Why Micromamba?

Previous approaches that **did not work** on SLAC systems:

1. **EnterpriseDB binaries**: Returns 403 Forbidden (access blocked)
2. **GitHub theseus-rs/postgresql-binaries (glibc)**: Requires OpenSSL 3.x (system has 1.1)
3. **GitHub theseus-rs/postgresql-binaries (musl)**: Requires musl libc (system uses glibc)

**Micromamba + conda-forge works** because:
- Self-contained download (~10 MB)
- Installs PostgreSQL with all dependencies in an isolated environment
- Binaries are compatible with RHEL/CentOS 8 glibc
- No root access required

---

## References

- [Micromamba Documentation](https://mamba.readthedocs.io/en/latest/user_guide/micromamba.html)
- [Conda-Forge PostgreSQL Package](https://anaconda.org/conda-forge/postgresql)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/current/)
- [Installing PostgreSQL without Root](https://www.endpointdev.com/blog/2013/06/installing-postgresql-without-root/)
