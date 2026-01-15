# V6 Benchmark Test Guide

**Date:** January 2026
**Purpose:** Compare V6a vs V6b path access approaches

---

## Overview

We have two V6 implementations that provide the same functionality but use different approaches for path access:

| Variant | Directory | Port | Path Access |
|---------|-----------|------|-------------|
| **V6a** | `tiled_poc_v6a` | 8005 | Paths stored in container metadata |
| **V6b** | `tiled_poc_v6b` | 8006 | Paths via Tiled's native `get_asset_filepaths()` |

**Goal:** Determine which approach is faster for bulk data loading.

---

## Prerequisites

### 1. Set Environment Variables

Add these to your shell (or run each time):

```bash
export PROJ_VDP=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp
export VDP_DATA=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE
```

### 2. Verify Data Access

```bash
ls $VDP_DATA/data/schema_v1/manifest_hamiltonians_*.parquet
```

Should show the manifest file exists.

---

## Test V6a (Metadata Paths)

### Step 1: Open Two Terminal Windows

You need two terminals - one for the server, one for commands.

### Step 2: Start Server (Terminal 1)

```bash
cd $PROJ_VDP/tiled_poc_v6a

uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
```

Keep this running. You should see output like:
```
Uvicorn running on http://127.0.0.1:8005
```

### Step 3: Register Data (Terminal 2)

```bash
cd $PROJ_VDP/tiled_poc_v6a

# Register 10 Hamiltonians (quick test)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python register_catalog.py
```

Wait for "Registration complete" message.

### Step 4: Run Benchmark (Terminal 2)

```bash
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python benchmark_v6.py
```

### Step 5: Record Results

Copy the benchmark output. Key metrics to note:
- **Query time** (ms)
- **HDF5 load time** (ms)
- **Total time** (ms)
- **Number of curves loaded**

### Step 6: Stop Server

Press `Ctrl+C` in Terminal 1 to stop the server.

### Step 7: Clean Up (Optional)

If you want to re-run with different data size:
```bash
rm -f $PROJ_VDP/tiled_poc_v6a/catalog.db
```

---

## Test V6b (Tiled-Native Paths)

### Step 1: Start Server (Terminal 1)

```bash
cd $PROJ_VDP/tiled_poc_v6b

uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
```

You should see:
```
Uvicorn running on http://127.0.0.1:8006
```

### Step 2: Register Data (Terminal 2)

```bash
cd $PROJ_VDP/tiled_poc_v6b

uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python register_catalog.py
```

### Step 3: Run Benchmark (Terminal 2)

```bash
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python benchmark_v6.py
```

### Step 4: Record Results

Copy the benchmark output (same metrics as V6a).

### Step 5: Stop Server

Press `Ctrl+C` in Terminal 1.

---

## Scaling Up (More Data)

To test with more Hamiltonians, set `VDP_MAX_HAMILTONIANS` before registering:

```bash
# Clear old database first
rm -f catalog.db

# Register 100 Hamiltonians
VDP_MAX_HAMILTONIANS=100 uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python register_catalog.py

# Or 1000 Hamiltonians (takes longer)
VDP_MAX_HAMILTONIANS=1000 uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  python register_catalog.py
```

---

## Results Template

Fill in this table with your benchmark results:

| Metric | V6a (10 Ham) | V6b (10 Ham) | V6a (100 Ham) | V6b (100 Ham) |
|--------|--------------|--------------|---------------|---------------|
| Query time (ms) | | | | |
| HDF5 load time (ms) | | | | |
| Total time (ms) | | | | |
| Curves loaded | | | | |

---

## Decision Criteria

After collecting results:

- **If V6b is within 20% of V6a performance** → Recommend V6b (cleaner, more Tiled-native)
- **If V6b is significantly slower** → Recommend V6a (pragmatic choice)

---

## Troubleshooting

### "Server not running" error
Make sure Terminal 1 has the server running before running commands in Terminal 2.

### Port already in use
If you see "Address already in use", kill the old server:
```bash
pkill -f "tiled serve"
```

### Permission denied
Make sure you have access to the VDP data directory:
```bash
ls $VDP_DATA/data/schema_v1/
```

---

## Questions?

Contact the project lead if you run into issues.
