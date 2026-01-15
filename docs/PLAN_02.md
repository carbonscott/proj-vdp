# Implementation Plan: tiled_clean_poc (Tiled-First Hierarchical Design)

## Overview

Create `/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_clean_poc/` - a clean Tiled-first implementation with hierarchical containers (Hamiltonians as parents, artifacts as children).

**Key difference from tiled_poc:** Hierarchical structure eliminates metadata duplication by storing physics parameters (Ja, Jb, Jc, Dc) once per Hamiltonian container rather than 11 times per artifact.

---

## Files to Create

```
tiled_clean_poc/
├── config_clean.yml           # Server config (port 8003)
├── register_clean_catalog.py  # Hierarchical registration script
├── demo_clean.py              # Demo/verification script
└── README.md                  # Quick-start documentation
```

---

## Step 1: Create Directory and Config

Create `config_clean.yml`:
- Server on port 8003 (different from tiled_poc's 8002)
- SQLite database: `clean_catalog.db`
- readable_storage pointing to existing HDF5 files

---

## Step 2: Registration Script (`register_clean_catalog.py`)

### Architecture

```
/                           <- Root
  /H_636ce3e4/              <- Container (Hamiltonian)
      metadata: {Ja_meV, Jb_meV, Jc_meV, Dc_meV, spin_s, g_factor}

      gs_state              <- Array child
      mh_x_7T               <- Array child
      mh_y_7T               <- Array child
      mh_z_7T               <- Array child
      mh_powder_7T          <- Array child
      mh_x_30T              <- Array child
      mh_y_30T              <- Array child
      mh_z_30T              <- Array child
      mh_powder_30T         <- Array child
      ins_12meV             <- Array child
      ins_25meV             <- Array child
```

### Key Functions

1. **`make_hamiltonian_key(huid)`**: `H_{first 8 chars of huid}`
2. **`make_artifact_key(row)`**: Human-readable names:
   - `gs_state` -> `"gs_state"`
   - `mh_curve` -> `"mh_{axis}_{Hmax_T}T"` (e.g., `"mh_powder_30T"`)
   - `ins_powder` -> `"ins_{Ei_meV}meV"` (e.g., `"ins_12meV"`)

### Registration Flow (Confirmed API from Tiled source)

```python
for ham_row in hamiltonians:
    huid = str(ham_row["huid"])

    # 1. Create Hamiltonian container using create_container()
    #    (Confirmed from tiled/client/container.py:783-814)
    h_container = client.create_container(
        key=f"H_{huid[:8]}",
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

    # 2. Register artifacts as children using container.new()
    #    (Confirmed from tiled/client/container.py:669-777)
    for art_row in artifacts_for_hamiltonian:
        h_container.new(
            structure_family=StructureFamily.array,
            data_sources=[data_source],  # External HDF5 reference
            key=make_artifact_key(art_row),  # e.g., "mh_powder_30T"
            metadata={
                "auid": str(art_row["auid"]),
                "type": art_row["type"],
                # Type-specific only (NO physics params!)
                "axis": ..., "Hmax_T": ..., "Ei_meV": ...
            },
        )
```

### Artifact Metadata (Normalized)

**On container (Hamiltonian):**
- `huid`, `Ja_meV`, `Jb_meV`, `Jc_meV`, `Dc_meV`, `spin_s`, `g_factor`

**On children (artifacts) - type-specific only:**
- `auid`, `type`, `shape`, `dtype`
- mh_curve: `axis`, `Hmax_T`
- ins_powder: `Ei_meV`
- gs_state: (none extra)

---

## Step 3: Demo Script (`demo_clean.py`)

Verify hierarchical access patterns:

```python
# Browse containers
for h_key in client.keys():
    h = client[h_key]
    print(f"{h_key}: {h.metadata}")
    print(f"  Children: {list(h.keys())}")

# Query by physics params (searches containers)
ferromagnetic = client.search(Key("Ja_meV") > 0)

# Access specific artifact via path
mh_data = client["H_636ce3e4"]["mh_powder_30T"][:]

# Multi-modal access (natural with hierarchy)
for h in client.values():
    params = h.metadata  # Physics params once
    mh = h["mh_powder_30T"][:]
    ins = h["ins_12meV"][:]
```

---

## Step 4: Incremental Testing

1. **Start small**: Register first 10 Hamiltonians (110 artifacts)
2. **Verify structure**: Check hierarchical navigation works
3. **Test queries**: Both container-level and cross-container
4. **Scale up**: Increase to 100, 1000, then full 10K

---

## Implementation Details

### Data Sources (same as tiled_poc)

```python
asset = Asset(
    data_uri=f"file://localhost{h5_full_path}",
    is_directory=False,
    parameter="data_uris",
)

structure = ArrayStructure.from_array(np.empty(shape, dtype=np.float64))

data_source = DataSource(
    mimetype="application/x-hdf5",
    assets=[asset],
    structure_family=StructureFamily.array,
    structure=structure,
    parameters={"dataset": dataset_path},  # e.g., "/curve/M_parallel"
    management=Management.external,
)
```

### HDF5 Dataset Paths

| Type | Dataset Path | Shape |
|------|--------------|-------|
| gs_state | `/gs/spin_dir` | (3, 8) |
| mh_curve | `/curve/M_parallel` | (200,) |
| ins_powder | `/ins/broadened` | (600, 400) |

### Source Data

- Manifests: `/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1/manifest_*.parquet`
- HDF5 files: `/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1/artifacts/`

---

## Verification Checklist

1. **Hierarchical structure**: `len(client)` = 10 containers (for 10 Hamiltonians)
2. **Children accessible**: `list(client["H_xxx"].keys())` returns 11 artifact names
3. **Keys readable**: `"H_636ce3e4/mh_powder_30T"` pattern
4. **Metadata normalized**: Physics params only on containers
5. **Queries work**: `client.search(Key("Ja_meV") > 0)` finds containers
6. **Data accessible**: `client["H_xxx"]["mh_powder_30T"][:]` returns array

---

## Commands to Run

```bash
# Navigate to directory
cd /sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/proj-vdp/tiled_clean_poc

# Start server (terminal 1)
UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE \
uv run --with 'tiled[server]' tiled serve config config_clean.yml --api-key secret

# Register (terminal 2) - start with 10 Hamiltonians
UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE \
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
python register_clean_catalog.py

# Run demo
UV_CACHE_DIR=/sdf/data/lcls/ds/prj/prjmaiqmag01/results/cwang31/.UV_CACHE \
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
python demo_clean.py
```

---

## Confirmed Tiled API (from source exploration)

**Container creation** (`tiled/client/container.py:783-814`):
```python
h_container = client.create_container(key="H_xxx", metadata={...})
```

**Child array creation** (`tiled/client/container.py:669-777`):
```python
h_container.new(
    structure_family=StructureFamily.array,
    data_sources=[data_source],
    key="mh_powder_30T",
    metadata={...}
)
```

**Hierarchical navigation**:
```python
client["H_xxx"]["mh_powder_30T"][:]  # Access nested data
client["H_xxx/mh_powder_30T"][:]     # Slash syntax also works
```
