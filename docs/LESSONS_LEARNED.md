# Lessons Learned: Tiled Performance Investigation

**Date:** January 9, 2026
**Project:** VDP Synthetic Magnetics Database
**Authors:** Investigation conducted with Claude

---

## Executive Summary

After extensive benchmarking across 5 implementation versions, we discovered:

1. **The bottleneck is NOT HTTP** - it's Tiled's internal array adapter overhead
2. **Direct Client Mode doesn't help** - Tiled's adapter is 34x slower than raw HDF5
3. **The solution**: Use Tiled for discovery (metadata queries) only, bypass it for array access

---

## The Investigation Journey

### Initial Observation (V3)

V3 (`tiled_poc`) used Tiled for everything - queries AND data loading:

```python
# V3 pattern
for h_key in client.keys():
    h = client[h_key]
    M = h["mh_powder_30T"][:]  # Array via Tiled
```

**Result:** 23 seconds for 200 curves (46x slower than Julia's 500ms)

### Hypothesis 1: HTTP Overhead

We assumed HTTP was the bottleneck. The diagnostic showed:
- 4,015 HTTP requests for 200 Hamiltonians
- ~5ms latency per request

**Attempted fix:** Direct Client Mode (in-process, no HTTP)

### Testing Direct Client Mode

```python
# Direct mode - no HTTP
config = parse_configs("config.yml")
app = build_app_from_config(config)
context = Context.from_app(app)
client = from_context(context)
```

**Result:** Still 18-23 seconds! Direct mode didn't help.

### Hypothesis 2: Per-Key Lookup Pattern

We discovered that `results[key]` makes separate requests even in Direct mode.

**Fix:** Use `.items()` for batch fetching:

```python
# Slow: per-key lookup
for key in results.keys():
    meta = results[key].metadata  # Separate lookup each time

# Fast: batch fetch with .items()
for key, container in results.items():
    meta = container.metadata  # Already fetched
```

**Result:** Metadata extraction improved 9-12x, but V3 still slow overall.

### The Real Discovery: Adapter Overhead

Detailed timing breakdown revealed the true bottleneck:

| Operation | Time per item | Method |
|-----------|--------------|--------|
| Container access | 16 ms | Tiled |
| Keys check | 16 ms | Tiled |
| **Array fetch** | **60 ms** | **Tiled** |

Compare to raw HDF5:

| Method | Time per array |
|--------|---------------|
| Tiled Direct Mode | 60.3 ms |
| Raw HDF5 (`h5py`) | 1.8 ms |
| **Overhead** | **34x** |

**The bottleneck is Tiled's array adapter, not HTTP!**

---

## Why Tiled's Array Access is Slow

For each `container[array_key][:]` call, Tiled:

1. Looks up the data source in SQLite catalog
2. Instantiates the appropriate adapter (HDF5Adapter)
3. Opens the HDF5 file
4. Navigates to the dataset
5. Reads the data
6. Validates and converts to numpy array
7. Returns through Tiled's response pipeline

This machinery provides flexibility (supports many formats, remote access, chunking, etc.) but adds overhead that's significant for small arrays.

```
Raw HDF5:
    h5py.File(path)["dataset"][:]  →  1.8 ms

Tiled (even Direct Mode):
    catalog lookup → adapter init → file open → read → validate → return  →  60 ms
```

---

## The Solution: Hybrid Architecture

**Use Tiled for what it's good at, bypass it for what it's slow at.**

### What Tiled is Good At
- Queryable metadata catalog
- Server-side filtering by physics parameters
- Authentication and access control
- HTTP API for remote discovery
- Uniform interface across data formats

### What Tiled is Slow At
- Serving many small arrays
- High-throughput data loading
- Bulk data transfer

### The Hybrid Pattern (V4/V5)

```python
# Step 1: Use Tiled for DISCOVERY (fast)
results = client.search(Key("Ja_meV") > 0)
paths = []
for key, container in results.items():  # Use .items()!
    paths.append(container.metadata["path_to_data"])

# Step 2: Use raw HDF5 for DATA LOADING (fast)
for path in paths:
    with h5py.File(path, "r") as f:
        data = f["/dataset"][:]
```

---

## Performance Summary

| Version | Architecture | 200 curves | vs Julia |
|---------|-------------|------------|----------|
| V3 + HTTP | Tiled for all | 23,000 ms | 46x slower |
| V3 + Direct | Tiled for all (no HTTP) | 18,000 ms | 36x slower |
| **V4** | **Tiled discovery + HDF5 data** | **659 ms** | **1.3x** |
| **V5** | **Tiled discovery + HDF5 data** | **534 ms** | **1.1x** |
| Julia | Direct HDF5 | 500 ms | 1.0x |

---

## Two Critical Fixes

### Fix 1: Use `.items()` for Metadata Extraction

```python
# SLOW: Per-key lookup (makes separate request per key)
for key in results.keys():
    container = results[key]  # 17ms per access
    meta = container.metadata

# FAST: Batch fetch with .items()
for key, container in results.items():  # Batched!
    meta = container.metadata  # Already in memory
```

**Speedup:** 9-12x for metadata extraction

### Fix 2: Bypass Tiled for Array Data

```python
# SLOW: Array via Tiled (60ms per array)
data = container["array_key"][:]

# FAST: Direct HDF5 (1.8ms per array)
with h5py.File(path, "r") as f:
    data = f["/dataset"][:]
```

**Speedup:** 34x for array access

---

## When to Use Each Approach

### Use Tiled for Arrays When:
- Remote users without filesystem access
- Need authentication/authorization per-array
- Small number of array accesses (< 10)
- Debugging or interactive exploration

### Bypass Tiled for Arrays When:
- Bulk data loading (100+ arrays)
- ML training pipelines
- Performance-critical applications
- Users have local filesystem access

---

## Recommended Architecture (V5)

```
┌─────────────────────────────────────────────────────────────┐
│                    Tiled Server                              │
│              "Queryable Metadata Catalog"                    │
│                                                              │
│  Stores: Physics params + file paths (NO arrays)            │
│  Provides: Fast filtered queries, HTTP API                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ Query results (metadata + paths)
┌─────────────────────────────────────────────────────────────┐
│                    Client Code                               │
│                                                              │
│  1. Query Tiled for matching Hamiltonians                    │
│  2. Extract paths from metadata (using .items()!)            │
│  3. Load arrays directly via h5py                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Takeaways

1. **Don't assume HTTP is the bottleneck** - profile before optimizing
2. **Tiled's value is discovery, not data transfer** - use it accordingly
3. **Always use `.items()` for iteration** - never `results[key]` in a loop
4. **Hybrid architecture wins** - right tool for each job
5. **Simple designs often perform best** - V5 is simpler AND faster than V4

---

## Files Reference

| File | Purpose |
|------|---------|
| `tiled_poc/DIAGNOSTIC_01.md` | Initial performance investigation |
| `tiled_poc_v4/CAVEAT.md` | The `.items()` pattern documentation |
| `tiled_poc_v4/TILED_DIRECT_MODE.md` | HTTP vs Direct mode comparison |
| `VERSION_COMPARISON.md` | Full version comparison |

---

## Appendix: Benchmark Commands

### Test V3 with Direct Mode
```bash
cd $PROJ_VDP/tiled_poc
uv run --with 'tiled[server]' --with h5py python -c "
from tiled.client import Context, from_context
from tiled.server.app import build_app_from_config
from tiled.config import parse_configs

config = parse_configs('config.yml')
app = build_app_from_config(config)
context = Context.from_app(app)
client = from_context(context)
# ... benchmark code
"
```

### Compare Tiled vs Raw HDF5
```bash
# Tiled array fetch
M = container["mh_powder_30T"][:]  # ~60ms

# Raw HDF5
with h5py.File(path, "r") as f:
    M = f["/curve/M_parallel"][:]  # ~1.8ms
```
