# HANDOFF_03: Discovery-Only Tiled Architecture

**Date:** January 9, 2026
**Author:** Auto-generated from discussion with Claude
**For:** Intern implementing V5 discovery-only Tiled catalog

---

## 1. Executive Summary

### What You're Building

Create `tiled_poc_v5/` — a **discovery-only Tiled implementation** where Tiled serves as a queryable manifest API, returning filtered DataFrames (paths + physics parameters) that ML users can use directly.

### Why This Approach?

We evolved through three approaches:

| Version | Approach | Result |
|---------|----------|--------|
| V3 | Tiled serves arrays via HTTP | 23s for 200 curves (too slow) |
| V4 | Hybrid (Tiled query + direct HDF5) | 0.5s but over-engineered |
| **V5** | **Discovery-only (returns manifest)** | **Simple, same performance as Julia** |

### The Key Insight

Julia domain experts already have fast, working code (`mh_dataset.jl`). Tiled's value is **NOT serving array data** — it's providing:

1. **HTTP API with authentication** — remote access without filesystem
2. **Queryable metadata** — server-side filtering by physics parameters
3. **Gateway for non-experts** — ML users don't need to know file structure

---

## 2. Architecture

### Discovery-Only Tiled

```
┌─────────────────────────────────────────────────────────────┐
│                      Tiled Server                           │
│                  "Queryable Manifest API"                   │
│                                                             │
│   Input:  Physics query                                     │
│           (Ja > 0, axis="powder", Hmax_T=30)               │
│                                                             │
│   Output: Filtered manifest (DataFrame)                     │
│   ┌──────────────────────────────────────────────────────┐ │
│   │ huid       │ Ja    │ Jb    │ Jc    │ Dc    │ path    │ │
│   │────────────│───────│───────│───────│───────│─────────│ │
│   │ 636ce3e4.. │  0.51 │  0.74 │ -0.73 │ -0.11 │ art/... │ │
│   │ a1b2c3d4.. │  0.32 │  0.45 │ -0.12 │ -0.05 │ art/... │ │
│   └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ DataFrame (paths + params)
┌─────────────────────────────────────────────────────────────┐
│                     ML Pipeline                             │
│             (doesn't need physics expertise)                │
│                                                             │
│   for path in manifest_df["path_rel"]:                      │
│       X.append(h5py.File(path)["curve/M_parallel"][:])      │
└─────────────────────────────────────────────────────────────┘
```

### What Tiled Does vs. Doesn't Do

```
What we DON'T need Tiled for:
├── Serving array data (direct HDF5 is 50x faster)
├── Local file access (users already have filesystem)
└── Complex hierarchical catalog (manifest is simpler)

What we DO need Tiled for:
├── Multi-institutional collaboration (HTTP API)
├── Authentication & access control
├── Discoverable metadata (query without loading data)
└── Gateway for non-experts (simple Python API)
```

---

## 3. Why This Scales

### Scaling to Larger Datasets

| Dataset Size | Full Tiled (V3) | Discovery-Only (V5) |
|--------------|-----------------|---------------------|
| 10K Hamiltonians | 23s for 200 curves | 0.5s |
| 100K Hamiltonians | Would be 10+ minutes | Still ~0.5s per batch |
| 1M Hamiltonians | Impractical | Linear with query result size |

**Why:** Discovery-only only touches data you actually need. The query returns paths, you load exactly those files.

### Scaling to Multiple Modalities

**Current:** Single modality (VDP magnetization)
```
Tiled Catalog
└── H_001: {Ja, Jb, Jc, Dc, paths...}
```

**Future:** Multi-modal (magnetization + neutron scattering + X-ray)
```
Tiled Catalog
├── vdp/
│   └── H_001: {Ja, Jb, Jc, Dc, mh_paths, ins_paths}
├── neutron/
│   └── sample_A: {temperature, field, paths...}
└── xray/
    └── scan_001: {energy, angle, paths...}
```

**Discovery-only enables:**
- Same query API across modalities
- Each modality stores only metadata + paths
- Cross-modal queries: "Find all data for Ja > 0 with neutron AND magnetization"

### Sharing with Non-Experts (ML Users)

**The expert workflow (Julia):**
```julia
# Expert needs to know: file structure, manifest format, HDF5 paths
df_art = read_parquet_df(art_path)
df_mh = filter(row -> row.type == "mh_curve" && row.axis == axis, df_art)
# ... 170 lines of code
```

**The non-expert workflow (Discovery API):**
```python
# ML user just needs: what parameters, what data shape
manifest = query_manifest(client, axis="powder", Hmax_T=30, Ja_min=0)
X, Theta = load_from_manifest(manifest)
# Done. 3 lines.
```

**What the ML user DOESN'T need to know:**
- Where files are stored
- HDF5 internal structure
- Manifest parquet format
- UUID naming conventions
- Which Julia scripts to run

**What they DO get:**
- A DataFrame with paths + physics parameters
- Simple function to load data
- Same performance as expert Julia code

---

## 4. Future Direction: Remote Data Access

**Current state (local users):**
```python
manifest = query_manifest(client, axis="powder", Hmax_T=30)
# Returns: DataFrame with local filesystem paths
# ┌─────────────────────────────────────────────────────────┐
# │ huid     | Ja   | path_rel                              │
# │ 636ce3e4 | 0.51 | artifacts/63/636ce3e4.../mh_pow_30.h5 │
# └─────────────────────────────────────────────────────────┘
```

**Future possibility (remote users):**
```python
manifest = query_manifest(client, axis="powder", Hmax_T=30)
# Returns: DataFrame with download/streaming URLs
# ┌───────────────────────────────────────────────────────────────────┐
# │ huid     | Ja   | download_url                                    │
# │ 636ce3e4 | 0.51 | https://data.facility.org/vdp/636ce3e4/mh.h5   │
# │          |      | OR: s3://vdp-bucket/artifacts/636ce3e4/mh.h5    │
# └───────────────────────────────────────────────────────────────────┘
```

**How this could work:**
1. Catalog stores both `path_rel` (local) and `remote_url` (cloud/HTTP)
2. `query_manifest()` returns appropriate column based on user's access
3. Remote users get signed URLs or S3 paths
4. Same `load_from_manifest()` function works with `fsspec` for remote files

**Why this is a natural extension:**
- Discovery-only already separates "finding data" from "loading data"
- Adding remote URLs is just another column in the manifest
- No changes to the core architecture needed

*Note: This is a future direction — current implementation focuses on local filesystem access.*

---

## 5. Value Proposition Summary

| Audience | Julia Direct | Discovery-Only Tiled |
|----------|--------------|---------------------|
| Domain experts (local) | Preferred | Works, but why bother |
| ML users (local) | Steep learning curve | Simple API |
| Remote collaborators | No access | HTTP API + future: download URLs |
| Multi-institution | File sharing nightmare | Centralized discovery |
| Multi-modal datasets | Custom code per modality | Unified query API |

---

## 6. Implementation Steps

### Step 1: Create Directory Structure

```bash
mkdir -p /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc_v5
cd /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc_v5
```

### Step 2: Create Config File (`config.yml`)

```yaml
# Tiled Server Configuration for V5 Discovery-Only
uvicorn:
  host: "127.0.0.1"
  port: 8004  # Different port from v3 (8002) and v4 (8003)

trees:
  - path: /
    tree: catalog
    args:
      uri: "sqlite:///catalog.db"
      init_if_not_exists: true
      writable_storage: "storage"
```

### Step 3: Create Registration Script (`register_catalog.py`)

**Key difference from V3/V4:** Register metadata + paths ONLY (no arrays).

```python
#!/usr/bin/env python
"""
V5 Discovery-Only Registration.

Registers Hamiltonians with metadata + artifact paths.
NO array registration — Tiled only serves as discovery API.
"""

import os
import pandas as pd
from tiled.client import from_uri

# Configuration
TILED_URL = "http://localhost:8004"
API_KEY = "secret"
VDP_DATA = os.environ.get("VDP_DATA", "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp")
BASE_DIR = f"{VDP_DATA}/data/schema_v1"
MANIFEST_HAM = f"{BASE_DIR}/manifest_hamiltonians_20251205-130253.parquet"
MANIFEST_ART = f"{BASE_DIR}/manifest_artifacts_20251205-130253.parquet"


def make_path_key(art_row):
    """Generate path key from artifact attributes."""
    t = art_row["type"]
    if t == "gs_state":
        return "path_gs_state"
    elif t == "mh_curve":
        return f"path_mh_{art_row['axis']}_{int(art_row['Hmax_T'])}T"
    elif t == "ins_powder":
        return f"path_ins_{int(art_row['Ei_meV'])}meV"
    return None


def register_discovery_catalog(client, ham_df, art_df, max_hamiltonians=None):
    """Register Hamiltonians with metadata + paths (no arrays)."""

    if max_hamiltonians:
        ham_df = ham_df.head(max_hamiltonians)

    # Group artifacts by huid for efficient lookup
    art_grouped = art_df.groupby("huid")

    for i, (_, ham_row) in enumerate(ham_df.iterrows()):
        huid = ham_row["huid"]
        h_key = f"H_{huid[:8]}"

        # Skip if already exists
        if h_key in client.keys():
            continue

        # Build metadata with physics params
        metadata = {
            "huid": huid,
            "Ja_meV": float(ham_row["Ja_meV"]),
            "Jb_meV": float(ham_row["Jb_meV"]),
            "Jc_meV": float(ham_row["Jc_meV"]),
            "Dc_meV": float(ham_row["Dc_meV"]),
            "spin_s": float(ham_row.get("spin_s", 2.5)),
            "g_factor": float(ham_row.get("g_factor", 2.0)),
        }

        # Add artifact paths to metadata
        if huid in art_grouped.groups:
            for _, art_row in art_grouped.get_group(huid).iterrows():
                path_key = make_path_key(art_row)
                if path_key:
                    metadata[path_key] = art_row["path_rel"]

        # Register container with metadata only (no arrays!)
        client.create_container(key=h_key, metadata=metadata)

        if (i + 1) % 100 == 0:
            print(f"Registered {i + 1} / {len(ham_df)} Hamiltonians")

    print(f"Done! Registered {len(ham_df)} Hamiltonians (metadata + paths only)")


def main():
    max_hamiltonians = int(os.environ.get("VDP_MAX_HAMILTONIANS", 10))

    print(f"Loading manifests...")
    ham_df = pd.read_parquet(MANIFEST_HAM)
    art_df = pd.read_parquet(MANIFEST_ART)
    print(f"  Hamiltonians: {len(ham_df)}")
    print(f"  Artifacts: {len(art_df)}")

    print(f"\nConnecting to {TILED_URL}...")
    client = from_uri(TILED_URL, api_key=API_KEY)

    print(f"\nRegistering up to {max_hamiltonians} Hamiltonians...")
    register_discovery_catalog(client, ham_df, art_df, max_hamiltonians)


if __name__ == "__main__":
    main()
```

### Step 4: Create Query Functions (`query_manifest.py`)

```python
#!/usr/bin/env python
"""
V5 Discovery API: Query Tiled, get manifest DataFrame.

Usage:
    from query_manifest import query_manifest, load_from_manifest

    # Get filtered manifest
    manifest = query_manifest(client, axis="powder", Hmax_T=30, Ja_min=0)

    # Load data directly (no Tiled)
    X, Theta = load_from_manifest(manifest)
"""

import os
import h5py
import numpy as np
import pandas as pd
from tiled.queries import Key

# Configuration
VDP_DATA = os.environ.get("VDP_DATA", "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp")
BASE_DIR = f"{VDP_DATA}/data/schema_v1"

# HDF5 dataset paths by artifact type
DATASET_PATHS = {
    "mh_curve": "/curve/M_parallel",
    "gs_state": "/gs/spin_dir",
    "ins_powder": "/ins/broadened",
}


def query_manifest(client, *, artifact_type="mh_curve", axis=None, Hmax_T=None,
                   Ei_meV=None, Ja_min=None, Ja_max=None, Jb_min=None, Jb_max=None,
                   Jc_min=None, Jc_max=None, Dc_min=None, Dc_max=None):
    """
    Query Tiled and return filtered manifest as DataFrame.

    Args:
        client: Tiled client connected to V5 catalog
        artifact_type: "mh_curve", "gs_state", or "ins_powder"
        axis: For mh_curve - "powder", "x", "y", "z"
        Hmax_T: For mh_curve - 7 or 30
        Ei_meV: For ins_powder - 12 or 25
        Ja_min/Ja_max: Filter by Ja_meV range
        (similar for Jb, Jc, Dc)

    Returns:
        DataFrame with columns: huid, Ja_meV, Jb_meV, Jc_meV, Dc_meV,
                               spin_s, g_factor, path_rel
    """
    # Build Tiled query from physics parameters
    results = client
    if Ja_min is not None:
        results = results.search(Key("Ja_meV") >= Ja_min)
    if Ja_max is not None:
        results = results.search(Key("Ja_meV") <= Ja_max)
    if Jb_min is not None:
        results = results.search(Key("Jb_meV") >= Jb_min)
    if Jb_max is not None:
        results = results.search(Key("Jb_meV") <= Jb_max)
    if Jc_min is not None:
        results = results.search(Key("Jc_meV") >= Jc_min)
    if Jc_max is not None:
        results = results.search(Key("Jc_meV") <= Jc_max)
    if Dc_min is not None:
        results = results.search(Key("Dc_meV") >= Dc_min)
    if Dc_max is not None:
        results = results.search(Key("Dc_meV") <= Dc_max)

    # Determine path key based on artifact type
    if artifact_type == "mh_curve":
        path_key = f"path_mh_{axis}_{int(Hmax_T)}T"
    elif artifact_type == "gs_state":
        path_key = "path_gs_state"
    elif artifact_type == "ins_powder":
        path_key = f"path_ins_{int(Ei_meV)}meV"
    else:
        raise ValueError(f"Unknown artifact_type: {artifact_type}")

    # Extract manifest rows from query results
    rows = []
    for h_key in results.keys():
        meta = results[h_key].metadata
        path_rel = meta.get(path_key)
        if path_rel is None:
            continue  # Skip if this artifact type doesn't exist

        rows.append({
            "huid": meta["huid"],
            "h_key": h_key,
            "Ja_meV": meta["Ja_meV"],
            "Jb_meV": meta["Jb_meV"],
            "Jc_meV": meta["Jc_meV"],
            "Dc_meV": meta["Dc_meV"],
            "spin_s": meta.get("spin_s", 2.5),
            "g_factor": meta.get("g_factor", 2.0),
            "path_rel": path_rel,
        })

    return pd.DataFrame(rows)


def load_from_manifest(manifest_df, *, artifact_type="mh_curve", clamp_H0=True,
                       base_dir=BASE_DIR):
    """
    Load data directly from manifest paths (no Tiled involved).

    Args:
        manifest_df: DataFrame from query_manifest() with path_rel column
        artifact_type: "mh_curve", "gs_state", or "ins_powder"
        clamp_H0: For mh_curve - set M(H=0) to zero
        base_dir: Base directory for HDF5 files

    Returns:
        X: (n_samples, ...) array data
        Theta: (n_samples, 6) parameters [Ja, Jb, Jc, Dc, spin_s, g_factor]
    """
    dataset_path = DATASET_PATHS[artifact_type]

    X_list = []
    Theta_list = []

    for _, row in manifest_df.iterrows():
        path = os.path.join(base_dir, row["path_rel"])
        if not os.path.exists(path):
            continue

        with h5py.File(path, "r") as f:
            data = f[dataset_path][:]

        # Normalize for mh_curve
        if artifact_type == "mh_curve":
            spin_s = row.get("spin_s", 2.5)
            g_factor = row.get("g_factor", 2.0)
            Msat = g_factor * spin_s

            if clamp_H0:
                data = data.copy()
                data[0] = 0.0

            data = data / Msat

        X_list.append(data)
        Theta_list.append([
            row["Ja_meV"],
            row["Jb_meV"],
            row["Jc_meV"],
            row["Dc_meV"],
            row.get("spin_s", 2.5),
            row.get("g_factor", 2.0),
        ])

    if not X_list:
        raise ValueError("No data loaded from manifest")

    X = np.stack(X_list, dtype=np.float32)
    Theta = np.array(Theta_list, dtype=np.float32)

    return X, Theta


# Convenience function matching Julia's build_mh_dataset() signature
def build_mh_dataset(client, *, axis="powder", Hmax_T=30, clamp_H0=True, **filters):
    """
    Build M(H) dataset - Julia-equivalent API.

    Args:
        client: Tiled client
        axis: "powder", "x", "y", "z"
        Hmax_T: 7 or 30
        clamp_H0: Set M(H=0) to zero
        **filters: Physics filters (Ja_min, Ja_max, etc.)

    Returns:
        X: (n_curves, n_points) normalized magnetization
        h_grid: (n_points,) reduced field [0, 1]
        Theta: (n_curves, 6) parameters
        manifest: DataFrame with metadata
    """
    manifest = query_manifest(
        client, artifact_type="mh_curve", axis=axis, Hmax_T=Hmax_T, **filters
    )
    X, Theta = load_from_manifest(manifest, artifact_type="mh_curve", clamp_H0=clamp_H0)
    h_grid = np.linspace(0, 1, X.shape[1], dtype=np.float32)

    return X, h_grid, Theta, manifest
```

---

## 7. Demo Notebook

Create `demo_discovery.py` as a marimo notebook (see separate file).

**Key cells:**
1. Introduction - Discovery-only architecture diagram
2. Connect to Tiled server
3. Query examples showing manifest DataFrame
4. Load data directly from paths
5. Visualization of M(H) curves
6. PyTorch DataLoader integration
7. Comparison with Julia workflow

---

## 8. Running the Demo

### Terminal 1 - Start V5 server:
```bash
export PROJ_VDP=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE

cd $PROJ_VDP/tiled_poc_v5
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
```

### Terminal 2 - Register data:
```bash
cd $PROJ_VDP/tiled_poc_v5

# Register 10 Hamiltonians (default)
uv run --with 'tiled[server]' --with pandas --with pyarrow \
    python register_catalog.py

# Register more Hamiltonians
VDP_MAX_HAMILTONIANS=1000 uv run --with 'tiled[server]' --with pandas --with pyarrow \
    python register_catalog.py
```

### Run demo notebook:
```bash
cd $PROJ_VDP/tiled_poc_v5
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
    --with marimo --with matplotlib --with torch \
    marimo run demo_discovery.py
```

---

## 9. Success Criteria

1. **Simplicity**: You can understand and implement this in < 1 day
2. **Performance**: Same as Julia/V4 (~0.5s for 200 curves)
3. **Clear separation**:
   - Tiled: discovery (query → manifest DataFrame)
   - Client: data loading (paths → HDF5 → arrays)
4. **Demo works**: Marimo notebook runs end-to-end
5. **Catalog is lightweight**: Only metadata, no arrays registered

---

## 10. Reference Documents

| Document | Path | Purpose |
|----------|------|---------|
| V4 Implementation | `proj-vdp/tiled_poc_v4/` | Previous hybrid approach |
| V3 Implementation | `proj-vdp/tiled_poc/` | Original Tiled-only approach |
| Julia loader | `$VDP_DATA/mh_dataset.jl` | Reference implementation |
| Julia viewer | `$VDP_DATA/syntheticdb_view.jl` | Expert visualization tool |
| Science background | `proj-vdp/tiled_retro/SCIENCE_BACKGROUND.md` | Physics context |

---

## 11. Questions?

If you get stuck:
1. Check the existing V4 implementation for patterns
2. Look at the Julia `mh_dataset.jl` for the data loading logic
3. Consult Tiled documentation: https://blueskyproject.io/tiled/
4. Ask for help with specific error messages

Good luck!
