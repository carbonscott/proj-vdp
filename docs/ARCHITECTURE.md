# VDP Data Architecture: From Raw Data to Dual-Mode Access

This document explains the complete data flow from VDP's raw simulation data to the Tiled-based dual-mode access system.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         RAW VDP DATA                                     │
│  /sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1/         │
├─────────────────────────────────────────────────────────────────────────┤
│  manifest_hamiltonians.parquet    manifest_artifacts.parquet            │
│  (10K rows)                       (110K rows)                           │
│        │                                │                               │
│        └───────────── JOIN ON huid ─────┘                               │
│                           │                                             │
│                           ▼                                             │
│                    artifacts/ (111K HDF5 files, 110 GB)                 │
└─────────────────────────────────────────────────────────────────────────┘
                            │
                            │ bulk_register.py or register_catalog.py
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      TILED CATALOG (SQLite)                             │
│  catalog.db (~120 MB)                                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  nodes (120K)  →  data_sources (110K)  →  assets (110K)                │
│       │                   │                    │                        │
│       │                   └─── structure_id ───┘                        │
│       │                           │                                     │
│       └─── parent/child ──────────┘                                     │
│                                                                         │
│  nodes_closure (350K) ← Materialized ancestry for fast queries          │
│  structures (3) ← Reusable array definitions                            │
└─────────────────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            │                               │
            ▼                               ▼
┌───────────────────────────┐   ┌───────────────────────────┐
│     MODE A (Expert)       │   │   MODE B (Visualizer)     │
│                           │   │                           │
│  query_manifest()         │   │  client["H_xxx"]["arr"][:]│
│       │                   │   │       │                   │
│       ▼                   │   │       ▼                   │
│  Extract path_* from      │   │  Tiled HTTP adapter       │
│  container metadata       │   │  reads from HDF5          │
│       │                   │   │       │                   │
│       ▼                   │   │       ▼                   │
│  Direct h5py.File()       │   │  Chunked array response   │
│  (no HTTP overhead)       │   │  (supports slicing)       │
└───────────────────────────┘   └───────────────────────────┘
```

---

## 1. Raw VDP Data Structure

### Source Location
```
/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1/
├── manifest_hamiltonians_20251205-130253.parquet  (1.2 MB, 10K rows)
├── manifest_artifacts_20251205-130253.parquet     (12 MB, 110K rows)
└── artifacts/                                      (110 GB, 111K files)
    └── XX/UUID.h5                                  (partitioned by UUID prefix)
```

### Hamiltonians Manifest (10,000 rows)

| Column | Type | Description |
|--------|------|-------------|
| `huid` | UUID | Primary key (Hamiltonian unique ID) |
| `Ja_meV` | float | Exchange coupling, a-axis [-1, 1] |
| `Jb_meV` | float | Exchange coupling, b-axis [-1, 1] |
| `Jc_meV` | float | Exchange coupling, c-axis [-1, 1] |
| `Dc_meV` | float | Single-ion anisotropy [-1, 1] |
| `spin_s` | float | Spin quantum number (fixed: 2.5) |
| `g_factor` | float | Landé g-factor (fixed: 2.0) |

### Artifacts Manifest (110,000 rows)

| Column | Type | Description |
|--------|------|-------------|
| `huid` | UUID | Foreign key → Hamiltonians |
| `auid` | UUID | Primary key (Artifact unique ID) |
| `type` | string | `gs_state`, `mh_curve`, or `ins_powder` |
| `path_rel` | string | Relative path to HDF5 file |
| `axis` | string | For mh_curve: x, y, z, or powder |
| `Hmax_T` | float | For mh_curve: 7.0 or 30.0 Tesla |
| `Ei_meV` | float | For ins_powder: 12.0 or 25.0 meV |
| `n_hpts` | int | For mh_curve: 200 points |
| `nq`, `nw` | int | For ins_powder: 600×400 grid |

### Artifacts per Hamiltonian (11 total)

| Type | Count | Shape | HDF5 Dataset |
|------|-------|-------|--------------|
| `gs_state` | 1 | (3, 8) | `/gs/spin_dir` |
| `mh_curve` | 8 | (200,) | `/curve/M_parallel` |
| `ins_powder` | 2 | (600, 400) | `/ins/broadened` |

---

## 2. SQLite Database Schema

### Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          NODES                                   │
│  (119,991 rows - hierarchical tree)                             │
├─────────────────────────────────────────────────────────────────┤
│  id          INTEGER PRIMARY KEY                                │
│  parent      INTEGER FK → nodes(id)   -- NULL for root          │
│  key         VARCHAR(1023)            -- "H_636ce3e4" or "gs_state"
│  structure_family  VARCHAR(9)         -- "container" or "array" │
│  metadata    JSON                     -- physics params + paths │
│  specs       JSON                     -- []                     │
│  time_created, time_updated  DATETIME                           │
├─────────────────────────────────────────────────────────────────┤
│  UNIQUE(key, parent)                                            │
└──────────────────────────────┬──────────────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       │                       │                       │
       ▼                       ▼                       ▼
┌──────────────────┐  ┌─────────────────────┐  ┌─────────────────┐
│  NODES_CLOSURE   │  │    DATA_SOURCES     │  │   STRUCTURES    │
│  (349,971 rows)  │  │   (109,990 rows)    │  │    (3 rows)     │
├──────────────────┤  ├─────────────────────┤  ├─────────────────┤
│ ancestor   INT   │  │ id        INT PK    │  │ id   VARCHAR(32)│
│ descendant INT   │  │ node_id   INT FK    │  │ structure JSON  │
│ depth      INT   │  │ structure_id FK ────┼──│                 │
├──────────────────┤  │ mimetype  VARCHAR   │  │ Stores: shape,  │
│ Materialized     │  │ parameters JSON     │  │ dtype, chunks   │
│ tree paths for   │  │ management VARCHAR  │  │                 │
│ fast queries     │  │ (HDF5 dataset path) │  │ Only 3 unique:  │
└──────────────────┘  └──────────┬──────────┘  │ - (3,8)         │
                                 │             │ - (200,)        │
                                 ▼             │ - (600,400)     │
                      ┌─────────────────────┐  └─────────────────┘
                      │ DATA_SOURCE_ASSET   │
                      │   ASSOCIATION       │
                      │  (109,990 rows)     │
                      ├─────────────────────┤
                      │ data_source_id FK   │
                      │ asset_id       FK ──┼──┐
                      │ parameter VARCHAR   │  │
                      └─────────────────────┘  │
                                               ▼
                                    ┌─────────────────────┐
                                    │      ASSETS         │
                                    │   (109,990 rows)    │
                                    ├─────────────────────┤
                                    │ id       INT PK     │
                                    │ data_uri VARCHAR    │
                                    │ (file://localhost/..)
                                    │                     │
                                    │ UNIQUE(data_uri)    │
                                    └─────────────────────┘
```

### Sample Node Hierarchy

```
id=0  parent=NULL  key=""           structure_family="container"  (Root)
  │
  ├─ id=1  parent=0  key="H_636ce3e4"  structure_family="container"
  │    metadata: {
  │      "huid": "636ce3e4-1ea0-5f0f-a515-a4378fa5c842",
  │      "Ja_meV": 0.509, "Jb_meV": 0.745, "Jc_meV": -0.734, "Dc_meV": -0.109,
  │      "spin_s": 2.5, "g_factor": 2.0,
  │      "path_gs_state": "artifacts/9e/9e95715f-...-b66721bdd308.h5",
  │      "path_mh_powder_30T": "artifacts/cf/cfbc55c6-...-b680f1f8f627.h5",
  │      ...
  │    }
  │    │
  │    ├─ id=2  parent=1  key="gs_state"       structure_family="array"
  │    ├─ id=3  parent=1  key="mh_x_7T"        structure_family="array"
  │    ├─ id=4  parent=1  key="mh_y_7T"        structure_family="array"
  │    ├─ id=5  parent=1  key="mh_z_7T"        structure_family="array"
  │    ├─ id=6  parent=1  key="mh_powder_7T"   structure_family="array"
  │    ├─ id=7  parent=1  key="mh_x_30T"       structure_family="array"
  │    ├─ id=8  parent=1  key="mh_y_30T"       structure_family="array"
  │    ├─ id=9  parent=1  key="mh_z_30T"       structure_family="array"
  │    ├─ id=10 parent=1  key="mh_powder_30T"  structure_family="array"
  │    ├─ id=11 parent=1  key="ins_12meV"      structure_family="array"
  │    └─ id=12 parent=1  key="ins_25meV"      structure_family="array"
  │
  ├─ id=13 parent=0  key="H_7a2b3c4d"  ...
  ...
```

---

## 3. Registration Process

### Data Flow: Parquet → SQLite

```
manifest_hamiltonians.parquet     manifest_artifacts.parquet
         │                                  │
         │ pandas.read_parquet()            │
         ▼                                  ▼
    df_hamiltonians                    df_artifacts
    (10K rows)                         (110K rows)
         │                                  │
         │                   df_artifacts.groupby('huid')
         │                                  │
         └──────────────────┬───────────────┘
                            │
                For each Hamiltonian huid:
                            │
                            ▼
    ┌───────────────────────────────────────────────────────┐
    │ 1. Create container node                              │
    │    key = "H_" + huid[:8]                             │
    │    metadata = {Ja, Jb, Jc, Dc, spin_s, g_factor}     │
    │                                                       │
    │ 2. Add artifact paths to metadata                     │
    │    For each artifact in group:                        │
    │      path_key = make_artifact_key(artifact, prefix="path_")
    │      metadata[path_key] = artifact.path_rel          │
    │                                                       │
    │ 3. Create array children (Mode B support)             │
    │    For each artifact:                                 │
    │      - Insert node (parent=container_id)              │
    │      - Insert structure (shape, dtype, chunks)        │
    │      - Insert asset (file://localhost/path/to/h5)     │
    │      - Insert data_source (node_id, structure_id,     │
    │                            mimetype, {dataset: path}) │
    │      - Insert association (data_source_id, asset_id)  │
    └───────────────────────────────────────────────────────┘
```

### bulk_register.py vs register_catalog.py

| Aspect | bulk_register.py | register_catalog.py |
|--------|------------------|---------------------|
| **Method** | Direct SQLAlchemy | Tiled HTTP client |
| **Speed** | ~1000 nodes/sec | ~10 nodes/sec |
| **Use case** | Initial load | Incremental updates |
| **Transaction** | Single commit | Per-Hamiltonian |
| **Closure table** | Disable trigger, rebuild with SQL | Auto-managed by Tiled |
| **Deduplication** | Manual (INSERT OR IGNORE) | Auto by Tiled |

### Artifact Key Generation

```python
def make_artifact_key(artifact_type, axis=None, Hmax_T=None, Ei_meV=None, prefix=""):
    if artifact_type == "gs_state":
        return f"{prefix}gs_state"
    elif artifact_type == "mh_curve":
        return f"{prefix}mh_{axis}_{int(Hmax_T)}T"
    elif artifact_type == "ins_powder":
        return f"{prefix}ins_{int(Ei_meV)}meV"
```

Examples:
- `make_artifact_key("mh_curve", axis="powder", Hmax_T=30)` → `"mh_powder_30T"`
- `make_artifact_key("mh_curve", axis="powder", Hmax_T=30, prefix="path_")` → `"path_mh_powder_30T"`

---

## 4. Dual-Mode Access

### Mode A: Expert (Direct HDF5)

**Best for:** ML training, bulk loading, maximum throughput

```python
from tiled.client import from_uri
from query_manifest import build_mh_dataset

client = from_uri("http://localhost:8005", api_key="secret")

# Step 1: Query Tiled for metadata (fast, ~50ms)
X, h_grid, Theta, manifest = build_mh_dataset(
    client,
    axis="powder",
    Hmax_T=30,
    Ja_min=0  # Filter: ferromagnetic only
)

# What happens internally:
# 1. client.search(Key("Ja_meV") >= 0) - server-side filter
# 2. Extract path_mh_powder_30T from each container's metadata
# 3. Open HDF5 files directly with h5py (no HTTP)
# 4. Read /curve/M_parallel dataset
# 5. Stack into arrays

# Result: X.shape = (n_samples, 200), Theta.shape = (n_samples, 6)
```

**Data path:**
```
Tiled metadata (path_mh_powder_30T)
         │
         ▼
    "artifacts/cf/cfbc55c6-...-b680f1f8f627.h5"
         │
         │ h5py.File(base_dir + path)["/curve/M_parallel"]
         ▼
    numpy array (200,)
```

### Mode B: Visualizer (HTTP Adapters)

**Best for:** Interactive exploration, remote access, slicing

```python
from tiled.client import from_uri

client = from_uri("http://localhost:8005", api_key="secret")

# Navigate hierarchy
h = client["H_636ce3e4"]
print(h.metadata)  # {Ja_meV: 0.509, Jb_meV: 0.745, ...}
print(list(h.keys()))  # ['gs_state', 'mh_x_7T', ..., 'ins_25meV']

# Full array access
mh_curve = h["mh_powder_30T"][:]  # shape (200,)

# Efficient slicing (HTTP range request)
ins_slice = h["ins_12meV"][100:200, 50:150]  # Only fetches requested region
```

**Data path:**
```
Tiled client request
         │
         ▼
    GET /H_636ce3e4/mh_powder_30T?slice=:
         │
         ▼
    Tiled server → data_sources → assets → file://localhost/path.h5
         │
         ▼
    HDF5 adapter reads /curve/M_parallel
         │
         ▼
    HTTP response (chunked array)
```

### Performance Comparison

| Operation | Mode A | Mode B |
|-----------|--------|--------|
| Query 10K Hamiltonians | ~50ms | N/A |
| Load 10K M(H) curves | ~450ms | ~60s |
| Single M(H) curve | ~2ms | ~60ms |
| INS slice (100x100) | ~5ms (full load first) | ~4ms |
| **Best for** | Bulk ML training | Interactive exploration |

---

## 5. Query Examples

### Server-Side Filtering

```python
from tiled.queries import Key

# All Hamiltonians
all_h = client  # 10,000

# Ferromagnetic (Ja > 0)
fm = client.search(Key("Ja_meV") > 0)  # ~5,000

# Antiferromagnetic with easy-axis anisotropy
afm_easy_axis = client.search(Key("Ja_meV") < 0).search(Key("Dc_meV") < 0)

# Specific parameter range
subset = client.search(
    (Key("Ja_meV") >= 0.5) &
    (Key("Jb_meV") >= 0.5) &
    (Key("Dc_meV") < -0.5)
)
```

### Mode A Bulk Loading

```python
# Load all powder M(H) curves at 30T
X, h_grid, Theta, manifest = build_mh_dataset(
    client, axis="powder", Hmax_T=30
)

# Load with physics filter
X_fm, _, Theta_fm, _ = build_mh_dataset(
    client, axis="powder", Hmax_T=30, Ja_min=0.5
)

# Load INS spectra
from query_manifest import build_ins_dataset
S, q_grid, w_grid, Theta_ins, manifest_ins = build_ins_dataset(
    client, Ei_meV=12
)
```

---

## 6. Configuration

### config.yml

```yaml
vdp:
  service_dir: "/sdf/data/.../proj-vdp/tiled_poc"
  data_dir: "/sdf/data/.../vdp"
  schema_version: "schema_v1"

  dataset_paths:
    mh_curve: "/curve/M_parallel"
    gs_state: "/gs/spin_dir"
    ins_powder: "/ins/broadened"

  default_shapes:
    mh_curve: [200]
    gs_state: [3, 8]
    ins_powder: [600, 400]
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TILED_URL` | `http://localhost:8005` | Server URL |
| `TILED_API_KEY` | `secret` | Authentication |
| `VDP_MAX_HAMILTONIANS` | `10` | Registration limit |
| `CATALOG_DB` | `catalog.db` | Database filename |

---

## 7. Summary

The VDP architecture transforms 110K HDF5 files into a queryable, dual-mode catalog:

1. **Raw Data**: Parquet manifests define the schema; HDF5 files store arrays
2. **Registration**: bulk_register.py loads manifests → SQLite in single transaction
3. **Catalog**: Hierarchical containers (Hamiltonians) with array children (artifacts)
4. **Mode A**: Query metadata → extract paths → direct HDF5 (fast, for ML)
5. **Mode B**: HTTP adapters → chunked arrays (interactive, for visualization)

Both modes access the **same underlying HDF5 files** through different interfaces optimized for their use cases.
