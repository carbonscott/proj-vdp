# The Locator and Manifest Contract

**Date:** 2026-02-12
**Status:** Draft
**Related:** `docs/DESIGN-GENERIC-BROKER.md`

---

## 1. The Locator

A **locator** is the minimal information needed to read one artifact's data
from storage. Every artifact registered in Tiled carries a locator in its
parent Hamiltonian's metadata.

A locator has three fields:

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Path to the HDF5 file (relative to data directory) |
| `dataset` | string | HDF5 internal dataset path (e.g., `/curve/M_parallel`) |
| `index` | int or null | Row index for batched files; null for single-entity files |

### Why `dataset` is part of the locator

Different artifacts can live in the same HDF5 file under different internal
paths. Without `dataset` in the locator, the broker would need a mapping
from artifact type to HDF5 path — which is exactly the kind of hardcoding
the generic broker eliminates.

The `dataset` field makes each locator fully self-contained: given `(file,
dataset, index)`, any consumer can load the data without knowing anything
about the dataset's conventions.

### Consumer code

The locator yields a uniform data access pattern regardless of storage layout:

```python
import h5py

def load_artifact(locator, data_dir):
    """Load one artifact using its locator."""
    path = os.path.join(data_dir, locator["file"])
    with h5py.File(path, "r") as f:
        ds = f[locator["dataset"]]
        if locator["index"] is not None:
            return ds[locator["index"]]   # one slice from a batched file
        else:
            return ds[:]                  # entire dataset
```

### Concrete examples

**VDP — one artifact per file (no batching):**

Each VDP artifact is a separate small HDF5 file (~1 KB). The `index` is
always null.

| Hamiltonian | Artifact | `file` | `dataset` | `index` |
|-------------|----------|--------|-----------|---------|
| H_636ce3e4 | mh_powder_30T | `artifacts/c4/636ce3e4-abcd.h5` | `/curve/M_parallel` | null |
| H_636ce3e4 | mh_x_7T | `artifacts/c4/636ce3e4-efgh.h5` | `/curve/M_parallel` | null |
| H_636ce3e4 | gs_state | `artifacts/c4/636ce3e4-ijkl.h5` | `/gs/spin_dir` | null |
| H_636ce3e4 | ins_12meV | `artifacts/9e/9e95715f-mnop.h5` | `/ins/broadened` | null |

```python
# Reading VDP mh_curve
with h5py.File("artifacts/c4/636ce3e4-abcd.h5") as f:
    curve = f["/curve/M_parallel"][:]     # shape (200,)
```

**NiPS3 EDRIXS — many Hamiltonians batched in one file:**

Tom's EDRIXS data stores 10,000 spectra in a single file. Each Hamiltonian's
spectrum is one row (accessed by index).

| Hamiltonian | Artifact | `file` | `dataset` | `index` |
|-------------|----------|--------|-----------|---------|
| H_rank0000_0000 | rixs | `NiPS3_combined_2.h5` | `/spectra` | 0 |
| H_rank0000_0001 | rixs | `NiPS3_combined_2.h5` | `/spectra` | 1 |
| H_rank0000_0002 | rixs | `NiPS3_combined_2.h5` | `/spectra` | 2 |
| ... | ... | ... | ... | ... |
| H_rank0000_9999 | rixs | `NiPS3_combined_2.h5` | `/spectra` | 9999 |

```python
# Reading NiPS3 spectrum #42
with h5py.File("NiPS3_combined_2.h5") as f:
    spectrum = f["/spectra"][42]           # shape (151, 40)
```

**NiPS3 Multimodal — multiple artifacts per Hamiltonian, one file each:**

Tom's Multimodal data stores all artifacts for one Hamiltonian in a single
file, with different HDF5 dataset paths for each artifact type.

| Hamiltonian | Artifact | `file` | `dataset` | `index` |
|-------------|----------|--------|-----------|---------|
| H_00000401 | powder | `401.h5` | `/powder` | null |
| H_00000401 | hisym | `401.h5` | `/hisym` | null |
| H_00000401 | mag_a | `401.h5` | `/Ma` | null |
| H_00000401 | mag_b | `401.h5` | `/Mb` | null |

```python
# Reading NiPS3 powder spectrum
with h5py.File("401.h5") as f:
    powder = f["/powder"][:]              # shape (512, 256)

# Reading magnetization along a-axis
with h5py.File("401.h5") as f:
    mag = f["/Ma"][:]                     # shape (51,)
```

### How locators are stored in Tiled

Locators are stored as metadata on the parent Hamiltonian container, using
the artifact type as a suffix:

```json
{
  "huid": "636ce3e4-...",
  "Ja_meV": 1.5,
  "Jb_meV": 2.0,
  "path_mh_powder_30T": "artifacts/c4/636ce3e4-abcd.h5",
  "dataset_mh_powder_30T": "/curve/M_parallel",
  "path_gs_state": "artifacts/c4/636ce3e4-ijkl.h5",
  "dataset_gs_state": "/gs/spin_dir",
  "path_rixs": "NiPS3_combined_2.h5",
  "dataset_rixs": "/spectra",
  "index_rixs": 42
}
```

The naming convention is:
- `path_{type}` — file path
- `dataset_{type}` — HDF5 dataset path
- `index_{type}` — batch index (only present for batched files)

---

## 2. The Manifest Contract

The manifest is the **interface boundary between the data provider and the
broker**. Whoever generates the data also provides a Parquet manifest. The
broker reads it generically.

### Responsibility boundary

```
Data Provider                    Broker                       User
(simulator, experiment)          (this repo)                  (scientist, ML pipeline)
───────────────────────         ─────────────────────        ─────────────────────────
Generate HDF5 files        →    Read manifest            →   Query Tiled metadata
Generate manifest Parquet  →    Register into Tiled      →   Get locators
  with standard columns:        (generic: iterates over      Load data via h5py
  huid, type, file,              all columns, zero            or Tiled HTTP
  dataset, index                 knowledge of parameter
                                 names or artifact types)
```

The broker has **zero hardcoded parameter names or artifact types**. It does
not know that VDP has `Ja_meV` or that NiPS3 has `F2_dd`. It just reads all
columns and stores them as Tiled metadata.

### What the data provider must ensure

The data provider's manifest generator is responsible for:

1. **`type` values are unique per Hamiltonian.** The `type` column becomes
   the Tiled child key. Two artifacts under the same Hamiltonian cannot share
   a type. For VDP, this means `mh_powder_30T` instead of `mh_curve`.

2. **`file` + `dataset` + `index` correctly locate the data.** The locator
   must be sufficient to load exactly one artifact array.

3. **All physics parameters are columns in the Hamiltonian manifest.** The
   broker reads them all dynamically. There is no config file listing which
   parameters exist.

4. **Column names follow the standard.** The required columns are listed
   below; all other columns are free-form and become metadata as-is.

### Hamiltonian manifest format

A Parquet file with one row per Hamiltonian:

| Column | Required | Description |
|--------|----------|-------------|
| `huid` | Yes | Unique Hamiltonian identifier (string) |
| *(all other columns)* | Dynamic | Become Tiled metadata as-is |

Example (VDP):

| huid | Ja_meV | Jb_meV | Jc_meV | Dc_meV | spin_s | g_factor |
|------|--------|--------|--------|--------|--------|----------|
| 636ce3e4-... | 1.5 | 2.0 | -0.3 | 0.1 | 2.5 | 2.0 |

Example (NiPS3 EDRIXS):

| huid | F2_dd | F2_dp | F4_dd | G1_dp | G3_dp |
|------|-------|-------|-------|-------|-------|
| rank0000_0000 | 100.0 | 50.0 | 200.0 | 30.0 | 15.0 |

### Artifact manifest format

A Parquet file with one row per artifact (one logical entity):

| Column | Required | Description |
|--------|----------|-------------|
| `huid` | Yes | Foreign key to parent Hamiltonian |
| `type` | Yes | Artifact type — becomes Tiled child key (must be unique per huid) |
| `file` | Yes | Path to HDF5 file (relative to data directory) |
| `dataset` | Yes | HDF5 internal dataset path |
| `index` | No | Row index for batched files (null for single-entity files) |
| *(all other columns)* | Dynamic | Become artifact metadata as-is |

Example (VDP — exploded from current format):

| huid | type | file | dataset | index |
|------|------|------|---------|-------|
| 636ce3e4 | mh_powder_30T | artifacts/c4/636ce3e4-abcd.h5 | /curve/M_parallel | |
| 636ce3e4 | mh_x_7T | artifacts/c4/636ce3e4-efgh.h5 | /curve/M_parallel | |
| 636ce3e4 | gs_state | artifacts/c4/636ce3e4-ijkl.h5 | /gs/spin_dir | |
| 636ce3e4 | ins_12meV | artifacts/9e/9e95715f-mnop.h5 | /ins/broadened | |

Example (NiPS3 EDRIXS — batched):

| huid | type | file | dataset | index |
|------|------|------|---------|-------|
| rank0000_0000 | rixs | NiPS3_combined_2.h5 | /spectra | 0 |
| rank0000_0001 | rixs | NiPS3_combined_2.h5 | /spectra | 1 |
| rank0000_0002 | rixs | NiPS3_combined_2.h5 | /spectra | 2 |

### What changes for VDP

The current VDP artifact manifest uses different column names and a
non-unique `type` column:

| Current column | New standard | Notes |
|----------------|-------------|-------|
| `path_rel` | `file` | Rename only |
| *(not present)* | `dataset` | Currently hardcoded in `config.yml` |
| `type` = `mh_curve` | `type` = `mh_powder_30T` | Combine `type` + `axis` + `Hmax_T` into unique key |
| `type` = `ins_powder` | `type` = `ins_12meV` | Combine `type` + `Ei_meV` into unique key |
| `type` = `gs_state` | `type` = `gs_state` | Already unique |

The VDP manifest generator (Julia side) needs a small update to produce
these columns. The extra VDP-specific columns (`axis`, `Hmax_T`, `Ei_meV`,
`n_hpts`, etc.) can remain in the manifest — they will become artifact
metadata automatically.

### Adding a new dataset

To register a new dataset with the generic broker:

1. Write a manifest generation script (~50 lines of Python) that produces
   Hamiltonian and Artifact Parquet files with the standard columns.
2. Place the HDF5 files and manifests in a data directory.
3. Update `config.yml` to point to the manifest location.
4. Run `bulk_register.py` or `register_catalog.py`.

No broker code changes are needed.
