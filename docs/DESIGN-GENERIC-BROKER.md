# Design: Generic Data Broker Service

**Date:** 2026-02-12
**Status:** Draft
**Branch:** `generic-broker-design`
**Related:** Issue #1 (Abstract multi-Hamiltonian file structure at registration level)

---

## 1. Problem

The current Tiled POC hardcodes dataset-specific details throughout the codebase:
parameter names (`Ja_meV` vs `F2_dd`), artifact types (`mh_curve` vs `rixs`),
directory layouts, and HDF5 internal paths. Adding a new dataset (like NiPS3 after
VDP) requires forking the entire codebase and doing a find-and-replace.

Additionally, datasets have different physical storage layouts:

| Dataset | Files | Layout |
|---------|-------|--------|
| VDP (Daniel) | 110K small HDF5 files | 1 artifact per file |
| NiPS3 (Tom) | 32 large HDF5 files | 3,125 Hamiltonians batched per file |

The broker should not care about these differences.

## 2. Core Abstraction: The Locator

After registration, every record in Tiled represents **exactly one logical entity**
(one Hamiltonian with its artifacts), regardless of physical storage.

Each artifact's metadata includes a **locator** — a uniform accessor:

```
(file, dataset, index)
```

- `file` — path to the HDF5 file
- `dataset` — HDF5 internal dataset path (e.g., `/RIXS`, `/curve/M_parallel`)
- `index` — row position within a batched file (`null` if the file contains one entity)

### Examples

```
VDP mh_curve:     file=artifacts/c4/uuid.h5,  dataset=/curve/M_parallel,  index=null  → f[dataset][:]
NiPS3 RIXS:       file=NiPS3_rank0000.h5,     dataset=/RIXS,             index=42    → f[dataset][42]
```

The consumer code is uniform:

```python
with h5py.File(locator["file"]) as f:
    if locator["index"] is not None:
        data = f[locator["dataset"]][locator["index"]]
    else:
        data = f[locator["dataset"]][:]
```

### What the locator is NOT

The locator does not include storage-level details like ZARR chunk indices. Chunking
is a storage optimization handled transparently by h5py/zarr. The broker's job is to
locate one complete artifact — what the user does with its dimensions afterward is
their responsibility.

### Layering

```
User code:        "Give me Hamiltonian #42's RIXS spectrum"
                            |
Tiled broker:     metadata query -> locator (file, index, dataset)
                            |
Storage layer:    h5py/zarr reads the right bytes (chunking invisible)
                            |
Returns:          numpy array — one complete artifact
```

## 3. The Manifest Contract

The manifest is the **contract between the simulator and the broker**. Whoever
generates the data also provides a manifest. The broker reads it generically.

### Hamiltonian Manifest

A Parquet file with one row per Hamiltonian:

| Column | Required | Description |
|--------|----------|-------------|
| `huid` | Yes | Unique Hamiltonian identifier |
| *(all other columns)* | Dynamic | Become Tiled metadata as-is |

The broker does NOT hardcode column names. It reads all columns dynamically:

```python
skip = {"huid"}
for col in ham_df.columns:
    if col not in skip:
        metadata[col] = row[col]
```

VDP manifests will have `Ja_meV, Jb_meV, Jc_meV, Dc_meV, spin_s, g_factor`.
NiPS3 manifests will have `F2_dd, F2_dp, F4_dd, ...`. The broker treats them
identically — they're just metadata keys.

### Artifact Manifest

A Parquet file with one row per artifact (one logical entity):

| Column | Required | Description |
|--------|----------|-------------|
| `huid` | Yes | Foreign key to parent Hamiltonian |
| `type` | Yes | Artifact type (becomes Tiled child key) |
| `file` | Yes | Path to HDF5 file |
| `dataset` | Yes | HDF5 internal dataset path (e.g., `/RIXS`, `/curve/M_parallel`) |
| `index` | No | Row index for batched files (`null` for single-entity files) |
| *(all other columns)* | Dynamic | Become artifact metadata as-is |

This is where the batched-vs-single abstraction lives. The manifest **explodes**
batched files into individual rows at manifest-generation time:

```
# NiPS3: 32 files x 3,125 per file = 100,000 artifact rows
huid=rank0000_0000, type=rixs, file=NiPS3_rank0000.h5, dataset=/RIXS, index=0
huid=rank0000_0001, type=rixs, file=NiPS3_rank0000.h5, dataset=/RIXS, index=1
...
huid=rank0000_3124, type=rixs, file=NiPS3_rank0000.h5, dataset=/RIXS, index=3124
huid=rank0001_0000, type=rixs, file=NiPS3_rank0001.h5, dataset=/RIXS, index=0
...

# VDP: 110K files, one row each
huid=636ce3e4, type=mh_curve, file=artifacts/c4/uuid.h5, dataset=/curve/M_parallel, index=null
huid=636ce3e4, type=ins_powder, file=artifacts/c4/uuid2.h5, dataset=/ins/broadened, index=null
...
```

The broker reads these rows uniformly. It never needs to know about the underlying
file layout.

## 4. Generic Registration

The registration script reads manifests and populates Tiled. It has **zero
hardcoded parameter names or artifact types**.

### Pseudocode

```python
def register(ham_df, art_df, client):
    skip_ham = {"huid"}
    skip_art = {"huid", "type", "file", "dataset", "index"}

    for _, ham_row in ham_df.iterrows():
        # Build metadata from ALL manifest columns (dynamic)
        metadata = {col: ham_row[col] for col in ham_df.columns if col not in skip_ham}

        # Attach artifact locators to Hamiltonian metadata
        arts = art_df[art_df["huid"] == ham_row["huid"]]
        for _, art_row in arts.iterrows():
            art_key = art_row["type"]
            metadata[f"path_{art_key}"] = art_row["file"]
            metadata[f"dataset_{art_key}"] = art_row["dataset"]
            if art_row.get("index") is not None:
                metadata[f"index_{art_key}"] = int(art_row["index"])

        # Create Tiled container with all metadata
        container = client.create_container(
            key=f"H_{ham_row['huid'][:8]}",
            metadata=metadata,
        )

        # Optionally register arrays as Tiled children (Mode B)
        for _, art_row in arts.iterrows():
            array = load_artifact(art_row)  # uses locator
            container.write_array(array, key=art_row["type"])
```

### What changes from current implementation

| Current (hardcoded) | Generic (config-driven) |
|---------------------|------------------------|
| `metadata["Ja_meV"] = row["Ja_meV"]` | `for col in df.columns: metadata[col] = row[col]` |
| `if type == "mh_curve": shape = (200,)` | Shape read from HDF5 at registration time |
| `elif type == "ins_powder": ...` | No type-specific branches needed |
| `make_artifact_key()` with hardcoded types | `key = art_row["type"]` directly |
| `config.yml` lists specific dataset_paths | Paths come from artifact manifest's `dataset` column |

## 5. Dual-Mode Access (unchanged)

The dual-mode architecture from V6 remains:

- **Mode A (Expert):** Query Tiled metadata for locators, load directly via h5py.
  Fast for bulk ML workloads. The locator `(file, dataset, index)` is in metadata.

- **Mode B (Visualizer):** Access arrays via Tiled HTTP adapters. Convenient for
  interactive exploration. For batched files, a small custom adapter handles the
  `index` field (~30 lines of code).

## 6. Coexistence of Multiple Datasets

Tiled's metadata is free-form JSON. Different datasets can coexist in the same
catalog with different metadata keys:

```python
# Query VDP data
client.search(Key("Ja_meV") > 0.5)

# Query NiPS3 data
client.search(Key("F2_dd") > 100)

# Filter by dataset type using Tiled specs
client.search(Spec("VDP"))
client.search(Spec("NiPS3"))
```

Each Hamiltonian container can optionally carry a `specs` tag identifying its
dataset of origin.

## 7. Responsibility Boundaries

```
Simulator (Julia/Python)          Broker (this repo)            User
─────────────────────────        ─────────────────────         ──────────
Generate HDF5 files        →     Read manifests           →    Query Tiled
Generate manifest Parquets →     Register into Tiled      →    Get locators
  (one row per entity,           (generic, no hardcoded   →    Load via h5py
   includes locator info)          param names)                 or Tiled HTTP
```

The manifest is the **interface boundary**. Simulator authors define their own
parameter names and file layouts. The broker ingests them generically. Users
query on whatever metadata keys exist.

## 8. What Needs to Change

### Manifest generation (simulator side)

- VDP: Already generates Parquet manifests. Needs to add `file`, `dataset`,
  `index` columns in the standardized format (minor refactor of Julia scripts).
- NiPS3: Claire's `create_manifest.py` already generates manifests. Needs the
  same column standardization.

### Registration scripts (broker side)

| File | Change | Effort |
|------|--------|--------|
| `scripts/config.py` | Make manifest path/glob configurable via `config.yml` | Small |
| `scripts/utils.py` | Remove hardcoded artifact type branches; key = `art_row["type"]` | Small |
| `scripts/bulk_register.py` | Replace hardcoded param lists with dynamic column reading | Medium |
| `scripts/register_catalog.py` | Same as above | Medium |
| `scripts/query_manifest.py` | Already generic (uses `Key()` queries) — minimal changes | Small |
| `config.yml` | Remove `dataset_paths` and `default_shapes` (come from manifest) | Small |

### New code needed

| Component | Description | Effort |
|-----------|-------------|--------|
| `SlicedHDF5Adapter` | Custom Tiled adapter for Mode B on batched files | ~30 lines |
| Manifest validation | Optional: validate manifest has required columns | ~20 lines |

## 9. What Does NOT Change

- Tiled server setup and configuration
- Dual-mode access pattern (Mode A / Mode B)
- Hierarchical catalog structure (Hamiltonians as containers, artifacts as children)
- Query API (`Key()` searches on metadata)
- PostgreSQL / SQLite backend choice
- K8S deployment

## 10. Migration Path

1. **Standardize the manifest format** (this document defines it)
2. **Refactor registration scripts** to read columns dynamically
3. **Test with VDP data** using the new generic scripts (should produce identical catalog)
4. **Test with NiPS3 data** using the same scripts + NiPS3 config/manifests
5. **Merge Claire's branch** — only `utils.py` additive changes needed; her separate
   `tiled_poc_cfitussi/` directory can be archived once the generic broker handles NiPS3
