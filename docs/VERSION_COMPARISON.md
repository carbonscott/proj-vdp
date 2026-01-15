# VDP Tiled Implementation: Version Comparison

**Date:** January 13, 2026
**Purpose:** Comprehensive analysis of all Tiled implementation versions

---

## Executive Summary

| Version | Directory | Port | Performance | vs Julia | Path Access | Adapter Access |
|---------|-----------|------|-------------|----------|-------------|----------------|
| V1 (Retrofit) | `tiled_retro` | 8001 | Not measured | - | No | Yes |
| V3 (Hierarchical) | `tiled_poc` | 8002 | 23,000 ms | 46x slower | No | Yes |
| V4 (Hybrid) | `tiled_poc_v4` | 8003 | 659 ms | 1.3x | Via manifest | Yes |
| V5 (Discovery) | `tiled_poc_v5` | 8004 | 534 ms | 1.1x | Yes | No |
| **V6 (Unified)** | `tiled_poc_v6` | 8005 | **~534 ms** | **~1.1x** | **Yes** | **Yes** |
| Julia baseline | - | - | ~500 ms | 1.0x | - | - |

**Key Finding:** V6 provides BOTH access modes in a unified catalog, giving users the choice.

---

## Version History

### V1: tiled_retro (Flat Retrofit)

**Concept:** Retrofit Tiled onto existing UUID-based file system.

```
Catalog Structure:
/
├── mh_curve_cfbc55c6   (110K flat siblings)
├── mh_curve_769f9570
├── ins_powder_07fff5c0
└── ...
```

**Issues:**
- Opaque UUID-based keys
- Duplicated metadata (physics params repeated 11x per Hamiltonian)
- 110K flat entries (no hierarchy)
- Two parallel metadata systems (Parquet + SQLite)

**Status:** Legacy, not actively used.

---

### V3: tiled_poc (Hierarchical Tiled-First)

**Concept:** Clean hierarchical design with Hamiltonians as containers.

```
Catalog Structure:
/
├── H_636ce3e4/              <- Container
│   ├── gs_state             <- Array child
│   ├── mh_powder_30T        <- Array child
│   └── ...
└── H_9b2388ba/
    └── ...
```

**Catalog Stats:**
- Nodes: 16,812 (1,403 containers + 15,409 arrays)
- Size: 21 MB
- Registered: ~1,400 Hamiltonians

**Performance Problem:**
- 23 seconds for 200 curves (52x slower than Julia)
- Root cause: 4,015 HTTP requests for 200 Hamiltonians (~20 per Hamiltonian)
- Each array fetch: 77ms average

**Status:** Identified HTTP overhead as critical issue.

---

### V4: tiled_poc_v4 (Hybrid Design)

**Concept:** Use Tiled for discovery/queries, direct HDF5 for data loading.

```
Data Flow:
1. Tiled: Query by physics params → get matching Hamiltonians
2. Manifest: Look up HDF5 paths by huid
3. HDF5: Load data directly (bypass Tiled HTTP)
```

**Catalog Stats:**
- Nodes: 120,001 (10,001 containers + 110,000 arrays)
- Size: 135 MB
- Registered: 10,000 Hamiltonians (full dataset)

**Key Change:** Added `huid` to container metadata for manifest lookup.

**Performance (after `.items()` fix):**
- Query: ~0 ms
- Extract metadata: 444 ms (was 3,500+ ms before fix)
- HDF5 load: 214 ms
- **Total: 659 ms (1.3x Julia)**

**Pros:**
- Arrays still registered in Tiled (can access via HTTP if needed)
- Full flexibility (Tiled OR HDF5 access)
- Supports remote users via HTTP

**Cons:**
- Larger catalog (135 MB)
- More complex (two data paths)
- Requires manifest files on client

---

### V5: tiled_poc_v5 (Discovery-Only)

**Concept:** Tiled only stores metadata + paths (NO arrays registered).

```
Data Flow:
1. Tiled: Query → get metadata including artifact paths
2. HDF5: Load data directly from paths in metadata
```

**Catalog Stats:**
- Nodes: 10,001 (10,001 containers + 0 arrays)
- Size: 68 MB
- Registered: 10,000 Hamiltonians

**Key Design:** Artifact paths stored directly in container metadata:
```python
metadata = {
    "Ja_meV": 0.51,
    "path_mh_powder_30T": "artifacts/95/95f02053.../mh.h5",
    "path_gs_state": "artifacts/9e/9e95715f.../gs.h5",
    ...
}
```

**Performance (after `.items()` fix):**
- Query: ~0 ms
- Extract metadata: 401 ms
- HDF5 load: 133 ms
- **Total: 534 ms (1.1x Julia)**

**Pros:**
- Smallest catalog (68 MB vs 135 MB)
- Simplest design (no array registration)
- Fastest performance (1.1x Julia)
- No manifest files needed on client

**Cons:**
- Cannot access data via Tiled HTTP (local filesystem only)
- Less flexible for remote users

---

### V6: tiled_poc_v6 (Unified Dual-Mode)

**Concept:** Unified catalog providing BOTH access modes - users choose.

```
Catalog Structure:
/
├── H_636ce3e4/              <- Container
│   ├── metadata:            <- Includes physics + paths
│   │   ├── Ja_meV, Jb_meV, ...
│   │   ├── path_mh_powder_30T, path_ins_12meV, ...
│   │   └── huid
│   ├── gs_state             <- Array child (adapter access)
│   ├── mh_powder_30T        <- Array child (adapter access)
│   ├── ins_12meV            <- Array child (adapter access)
│   └── ...
└── H_9b2388ba/
    └── ...
```

**Catalog Stats (expected):**
- Nodes: ~120,000 (10,000 containers + 110,000 arrays)
- Size: ~140 MB
- Registered: 10,000 Hamiltonians

**Key Design:** Every artifact gets BOTH:
1. `path_*` metadata field (for expert path-based access)
2. Tiled adapter child node (for visualization/chunked access)

**Two Access Modes:**
```python
# Mode A (Expert): Path-based access
manifest = query_manifest(client, axis="powder", Hmax_T=30)
X, Theta = load_from_manifest(manifest)  # Direct HDF5

# Mode B (Visualizer): Adapter access
ins_slice = h["ins_12meV"][100:200, 50:150]  # Chunked HTTP
```

**Expected Performance:**
- Mode A (bulk loading): ~534 ms (1.1x Julia) - same as V5
- Mode B (single item): ~50-100 ms per array

**Pros:**
- **User choice:** Same catalog serves both ML experts and visualizers
- **Flexibility:** Can use paths OR adapters for any artifact
- **Remote support:** HTTP access via adapters when needed
- **Simple client code:** No manifest files required

**Cons:**
- Larger catalog (~140 MB vs 68 MB for V5)
- Upfront registration cost (but no runtime impact)

---

## Architecture Comparison

| Aspect | V3 | V4 | V5 | V6 |
|--------|-----|-----|-----|-----|
| Catalog nodes | 16K | 120K | 10K | 120K |
| Catalog size | 21 MB | 135 MB | 68 MB | ~140 MB |
| Arrays in Tiled | Yes | Yes | No | **Yes** |
| Path in metadata | No | No | Yes | **Yes** |
| Data via HTTP | Yes | Optional | No | **Yes** |
| Direct HDF5 | No | Yes | Yes | **Yes** |
| Requires manifest | No | Yes | No | No |
| Performance | 23,000 ms | 659 ms | 534 ms | ~534 ms |
| User choice | No | Limited | No | **Yes** |

---

## The Critical Fix: `.items()` Pattern

**The Bottleneck Was NOT HTTP vs Direct Mode**

Our investigation revealed that the per-key lookup pattern was the real bottleneck:

```python
# SLOW: Each results[key] makes a separate HTTP request
for key in results.keys():
    meta = results[key].metadata  # ~17ms per access

# FAST: .items() batches the fetches
for key, container in results.items():
    meta = container.metadata  # Already fetched!
```

**Impact:**
| Pattern | Time for 200 items |
|---------|-------------------|
| Per-key lookup | 3,500+ ms |
| `.items()` batch | 400 ms |
| **Speedup** | **9-12x** |

This fix was applied to both V4 and V5, making both performant.

---

## Recommendation

### For This Project: **V6 (Unified Dual-Mode)**

**Reasons:**
1. **User choice:** Serves both ML experts (paths) and visualizers (adapters)
2. **Best of both worlds:** V5-like performance + V4-like flexibility
3. **Future-proof:** Same catalog handles all use cases
4. **No compromise:** ~534 ms bulk loading, HTTP access when needed

### When to Choose V5 Instead:

- Absolutely minimal catalog size is critical (68 MB vs ~140 MB)
- All users are local ML experts who only need bulk loading
- No visualization or interactive exploration use cases

### When to Choose V4 Instead:

- Need manifest-based path lookup (legacy compatibility)
- Don't want paths in metadata for some reason

### When to Choose V3:

- Never (HTTP overhead makes it impractical for bulk data loading)

---

## Files Changed

The `.items()` optimization was applied to:

1. **V4:** `tiled_poc_v4/load_mh_dataset.py` (line 90)
2. **V5:** `tiled_poc_v5/query_manifest.py` (line 105)

Documentation created:
- `tiled_poc_v4/TILED_DIRECT_MODE.md` - HTTP vs Direct client modes
- `tiled_poc_v4/CAVEAT.md` - The critical `.items()` pattern

---

## Summary Table

| Metric | V3 | V4 | V5 | V6 | Winner |
|--------|-----|-----|-----|-----|--------|
| Performance | 23s | 659ms | 534ms | ~534ms | V5/V6 |
| Catalog size | 21MB | 135MB | 68MB | ~140MB | V5 |
| Simplicity | Medium | Complex | Simple | Medium | V5 |
| Remote access | Yes | Yes | No | **Yes** | V4/V6 |
| Flexibility | Low | High | Medium | **Highest** | **V6** |
| User choice | No | Limited | No | **Yes** | **V6** |

**Final Recommendation:** Use **V6** for the unified approach that serves all user types. Use V5 only if minimal catalog size is critical.
