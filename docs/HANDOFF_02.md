# HANDOFF_02: Implementing tiled_clean_poc (Tiled-First Design)

**Date:** January 8, 2026
**Author:** Auto-generated from discussion with Claude
**For:** Intern implementing clean Tiled-first catalog

---

## 1. Project Overview

### What You're Building

Create `tiled_clean_poc/` — a **clean Tiled-first implementation** that demonstrates the ideal architecture for the VDP synthetic magnetics database. This will sit alongside the existing `tiled_poc/` (retrofit design) as a reference implementation.

### Why This Matters

The current `tiled_poc` was built by retrofitting Tiled onto an existing UUID-based system. While functional, it has inefficiencies:
- Opaque keys (`mh_curve_cfbc55c6`)
- Duplicated metadata (physics params repeated 11× per Hamiltonian)
- Flat structure (110K sibling entries)

A Tiled-first design eliminates these issues and serves as a template for future projects.

### Location

```
/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/
├── tiled_poc/           ← Existing retrofit implementation
└── tiled_clean_poc/     ← NEW: Your clean implementation
```

---

## 2. Key Differences: Retrofit vs Clean

| Aspect | tiled_poc (Retrofit) | tiled_clean_poc (Clean) |
|--------|---------------------|-------------------------|
| **Catalog structure** | Flat (110K siblings) | Hierarchical (10K containers) |
| **Keys** | `mh_curve_cfbc55c6` | `H_0001/mh_powder_30T` |
| **Metadata** | Duplicated 11× per Hamiltonian | Once per container |
| **Physics params** | On every artifact | On Hamiltonian container only |
| **File organization** | 110K UUID-named files | Could consolidate to 10K files |
| **SQLite size** | 180 MB | ~100 MB (estimated) |

---

## 3. Target Architecture

### Hierarchical Catalog Structure

```
Tiled Catalog (tree):

/                                    ← Root container
  /H_0001/                           ← Hamiltonian container
      metadata: {Ja_meV: 0.509, Jb_meV: 0.745, Jc_meV: -0.734, Dc_meV: -0.109}

      gs_state                       ← Array (shape: 3×8)
      mh_x_7T                        ← Array (shape: 200)
      mh_y_7T
      mh_z_7T
      mh_powder_7T
      mh_x_30T
      mh_y_30T
      mh_z_30T
      mh_powder_30T
      ins_12meV                      ← Array (shape: 600×400)
      ins_25meV

  /H_0002/                           ← Another Hamiltonian
      metadata: {Ja_meV: -0.506, ...}
      gs_state
      mh_x_7T
      ...
```

### Key Design Principles

1. **Hamiltonians are containers** — Physics params (Ja, Jb, Jc, Dc) stored once on the container
2. **Artifacts are children** — Each artifact is a child of its parent Hamiltonian
3. **Descriptive keys** — Human-readable names like `mh_powder_30T` instead of UUIDs
4. **No metadata duplication** — Artifacts only store artifact-specific metadata (axis, Hmax, Ei)

---

## 4. Data Source

You'll read from the same source data as `tiled_poc`:

```
Source manifests:
  /sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1/
    manifest_hamiltonians_*.parquet   (10K rows)
    manifest_artifacts_*.parquet      (110K rows)

Source HDF5 files:
  /sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1/artifacts/
    (110,000 files, 111 GB total)
```

### Manifest Structure

**Hamiltonian manifest columns:**
- `huid` — Unique ID (used to link to artifacts)
- `Ja_meV`, `Jb_meV`, `Jc_meV`, `Dc_meV` — Physics parameters
- `spin_s`, `g_factor` — Spin properties

**Artifact manifest columns:**
- `auid` — Artifact unique ID
- `huid` — Parent Hamiltonian ID
- `type` — `gs_state`, `mh_curve`, or `ins_powder`
- `axis` — For mh_curve: `x`, `y`, `z`, `powder`
- `Hmax_T` — For mh_curve: `7.0` or `30.0`
- `Ei_meV` — For ins_powder: `12.0` or `25.0`
- `path_rel` — Relative path to HDF5 file

---

## 5. Implementation Steps

### Step 1: Create Directory Structure

```bash
mkdir -p /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_clean_poc
cd /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_clean_poc
```

### Step 2: Create Config File (`config_clean.yml`)

```yaml
# Tiled Server Configuration for Clean POC
uvicorn:
  host: "127.0.0.1"
  port: 8003  # Different port from tiled_poc

trees:
  - path: /
    tree: catalog
    args:
      uri: "sqlite:///clean_catalog.db"
      init_if_not_exists: true
      writable_storage: "storage"
      readable_storage:
        - "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1"
```

### Step 3: Create Registration Script (`register_clean_catalog.py`)

```python
#!/usr/bin/env python
"""
Register VDP artifacts using Tiled-first hierarchical design.

Architecture:
  /H_xxxx/           ← Container with Hamiltonian metadata
      gs_state       ← Child array
      mh_x_7T        ← Child array
      ...
"""

import pandas as pd
from tiled.client import from_uri
from tiled.structures.array import ArrayStructure
from tiled.structures.core import StructureFamily

# Configuration
TILED_URL = "http://localhost:8003"
API_KEY = "secret"
BASE_DIR = "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1"


def make_artifact_key(row):
    """Generate human-readable key from artifact metadata."""
    t = row["type"]
    if t == "gs_state":
        return "gs_state"
    elif t == "mh_curve":
        return f"mh_{row['axis']}_{int(row['Hmax_T'])}T"
    elif t == "ins_powder":
        return f"ins_{int(row['Ei_meV'])}meV"
    else:
        raise ValueError(f"Unknown type: {t}")


def make_hamiltonian_key(huid):
    """Generate container key from huid."""
    return f"H_{huid[:8]}"


def register_hierarchical(client, ham_df, art_df):
    """Register all Hamiltonians and their artifacts."""

    for i, ham_row in ham_df.iterrows():
        huid = ham_row["huid"]
        h_key = make_hamiltonian_key(huid)

        # Create Hamiltonian container with physics params
        h_container = client.new(
            structure_family=StructureFamily.container,
            key=h_key,
            metadata={
                "huid": huid,
                "Ja_meV": float(ham_row["Ja_meV"]),
                "Jb_meV": float(ham_row["Jb_meV"]),
                "Jc_meV": float(ham_row["Jc_meV"]),
                "Dc_meV": float(ham_row["Dc_meV"]),
                "spin_s": float(ham_row.get("spin_s", 2.5)),
                "g_factor": float(ham_row.get("g_factor", 2.0)),
            }
        )

        # Get artifacts for this Hamiltonian
        artifacts = art_df[art_df["huid"] == huid]

        for _, art_row in artifacts.iterrows():
            art_key = make_artifact_key(art_row)

            # Artifact-specific metadata only (no physics params!)
            art_metadata = {"auid": art_row["auid"], "type": art_row["type"]}

            if art_row["type"] == "mh_curve":
                art_metadata["axis"] = art_row["axis"]
                art_metadata["Hmax_T"] = float(art_row["Hmax_T"])
                dataset_path = "/curve/M_parallel"
                shape = (200,)
            elif art_row["type"] == "ins_powder":
                art_metadata["Ei_meV"] = float(art_row["Ei_meV"])
                dataset_path = "/ins/broadened"
                shape = (600, 400)
            elif art_row["type"] == "gs_state":
                dataset_path = "/gs/spin_dir"
                shape = (3, 8)

            # Register artifact as child of container
            # TODO: Use h_container.new() to create child
            # See Tiled documentation for container.new() API

        if (i + 1) % 100 == 0:
            print(f"Registered {i + 1} / {len(ham_df)} Hamiltonians")


def main():
    # Load manifests
    ham_df = pd.read_parquet(f"{BASE_DIR}/manifest_hamiltonians_20251205-130253.parquet")
    art_df = pd.read_parquet(f"{BASE_DIR}/manifest_artifacts_20251205-130253.parquet")

    print(f"Loaded {len(ham_df)} Hamiltonians, {len(art_df)} artifacts")

    # Connect to Tiled
    client = from_uri(TILED_URL, api_key=API_KEY)

    # Register
    register_hierarchical(client, ham_df, art_df)

    print("Done!")


if __name__ == "__main__":
    main()
```

### Step 4: Implement Container Child Registration

**Key challenge:** The `client.new()` API for creating child entries inside a container.

Check the Tiled documentation for:
- Creating containers: `client.new(structure_family=StructureFamily.container, ...)`
- Creating children: `container.new(...)` or similar API

Reference the existing `register_vdp_catalog.py` for the flat registration pattern, then adapt for hierarchical.

### Step 5: Test Incrementally

```bash
# Start server
UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE \
uv run --with 'tiled[server]' tiled serve config config_clean.yml --api-key secret

# In another terminal, test registration with a small subset first
# Modify script to only register first 10 Hamiltonians for testing
```

### Step 6: Verify Query Patterns

```python
from tiled.client import from_uri
from tiled.queries import Key

client = from_uri("http://localhost:8003", api_key="secret")

# Query containers by physics params
ferromagnetic = client.search(Key("Ja_meV") > 0)
print(f"Found {len(ferromagnetic)} ferromagnetic Hamiltonians")

# Browse a container
h = client["H_636ce3e4"]
print(f"Metadata: {h.metadata}")
print(f"Children: {list(h.keys())}")

# Access specific artifact
mh_data = h["mh_powder_30T"][:]
print(f"M(H) shape: {mh_data.shape}")

# Multi-modal access (clean!)
for h in client.values():
    mh = h["mh_powder_30T"][:]
    ins = h["ins_12meV"][:]
    params = h.metadata  # Physics params on container
```

---

## 6. Success Criteria

Your implementation is complete when:

1. **Catalog structure is hierarchical**
   - 10K Hamiltonian containers
   - Each with 11 child artifacts

2. **Keys are human-readable**
   - `H_636ce3e4/mh_powder_30T` not `mh_curve_cfbc55c6`

3. **Metadata is normalized**
   - Physics params (Ja, Jb, Jc, Dc) only on containers
   - Artifacts have only artifact-specific metadata

4. **Queries work at both levels**
   - Query containers: `client.search(Key("Ja_meV") > 0)`
   - Access children: `client["H_xxxx"]["mh_powder_30T"][:]`

5. **Performance is comparable**
   - Queries: < 10 ms
   - Data retrieval: similar to tiled_poc

---

## 7. Potential Challenges

### Challenge 1: Container Child API
The Tiled API for creating children inside containers may differ from top-level registration. Check:
- `tiled.client.container.Container.new()`
- Tiled source code or documentation

### Challenge 2: Query Inheritance
When querying containers, can you also filter by child properties? Test whether:
```python
# Does this work? Or only container metadata?
client.search(Key("type") == "ins_powder")
```

### Challenge 3: Performance at Scale
Test with small subset first (100 Hamiltonians), then scale up.

---

## 8. Reference Documents

Read these for full context:

| Document | Path | Purpose |
|----------|------|---------|
| **ARCH_DIFF.md** | `proj-vdp/tiled_poc/ARCH_DIFF.md` | **START HERE** - Complete architecture comparison, terminology, query mechanics |
| **DATABASE_DESIGN.md** | `proj-vdp/tiled_poc/DATABASE_DESIGN.md` | SQLite schema, table relationships |
| **SCIENCE_BACKGROUND.md** | `proj-vdp/tiled_poc/SCIENCE_BACKGROUND.md` | Physics context (what the data means) |
| **README.md** | `proj-vdp/tiled_poc/README.md` | Quick start for existing tiled_poc |
| **register_vdp_catalog.py** | `proj-vdp/tiled_poc/register_vdp_catalog.py` | Reference implementation (flat design) |

Full paths:
```
/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc/ARCH_DIFF.md
/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc/DATABASE_DESIGN.md
/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc/SCIENCE_BACKGROUND.md
/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc/README.md
/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_poc/register_vdp_catalog.py
```

---

## 9. Environment Setup

```bash
# All commands use uv with custom cache
export UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE

# Install dependencies
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py python your_script.py

# Start server
uv run --with 'tiled[server]' tiled serve config config_clean.yml --api-key secret
```

---

## 10. Questions?

If you get stuck:
1. Check the ARCH_DIFF.md document — it explains the full design rationale
2. Look at the existing `register_vdp_catalog.py` for API patterns
3. Consult Tiled documentation: https://blueskyproject.io/tiled/
4. Ask for help with specific error messages

Good luck!
