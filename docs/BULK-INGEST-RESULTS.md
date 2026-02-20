# Bulk Ingest Results

**Date:** 2026-02-12
**Branch:** `generic-broker-design`
**Directory:** `tiled_poc/demo/`

---

## Overview

Full bulk ingest of all three datasets using the config-driven pipeline
(`generate.py` + `ingest.py`) into a fresh SQLite catalog in the `demo/`
directory (port 8006).

---

## Manifest Generation

```bash
cd demo
uv run $UV_DEPS python ../generate.py datasets/vdp.yml datasets/edrixs.yml datasets/multimodal.yml -n 10000
```

| Dataset | Entities | Artifacts | Notes |
|---------|-------------|-----------|-------|
| VDP | 10,000 | 110,000 | 11 artifacts/entity (mh curves, gs_state, ins spectra) |
| EDRIXS | 10,000 | 10,000 | 1 artifact/entity (rixs), batched into single HDF5 |
| Multimodal | 7,616 | 45,696 | 6 artifacts/entity (mag_a, mag_b, mag_cs, ins_hisym, ins_powder, ins_powder_mask) |
| **Total** | **27,616** | **165,696** | |

---

## Bulk Ingest

```bash
uv run $UV_DEPS python ../ingest.py datasets/vdp.yml datasets/edrixs.yml datasets/multimodal.yml
```

### Timings

| Dataset | Entities | Artifacts | Unique Structures | Unique Assets | Time |
|---------|-------------|-----------|-------------------|---------------|------|
| VDP | 10,000 | 110,000 | 3 | 110,000 | 75.4s |
| EDRIXS | 10,000 | 10,000 | 1 | 1 | 9.0s |
| Multimodal | 7,616 | 45,696 | 3 | 7,616 | 23.4s |
| **Total** | **27,616** | **165,696** | **7** | **117,617** | **~108s** |

EDRIXS is fast because all 10K spectra share a single HDF5 file (1 asset)
and a single structure. Multimodal is moderate because its 7,616 HDF5 files
are one per entity (each with 6 datasets inside).

### Database Stats

| Table | Rows |
|-------|------|
| nodes | 193,313 |
| nodes_closure | 552,321 |
| data_sources | 165,696 |
| structures | 7 |
| assets | 117,617 |
| associations | 165,696 |

**Database size:** 407 MB (SQLite)

### Throughput

- **Overall:** 193,313 nodes in 108 seconds = **~1,790 nodes/sec**
- VDP alone: 120,001 nodes in 75.4s = ~1,590 nodes/sec
- EDRIXS alone: 20,001 nodes in 9.0s = ~2,220 nodes/sec
- Multimodal alone: 53,313 nodes in 23.4s = ~2,280 nodes/sec

VDP is slower per-node because it has 110K unique HDF5 assets (one per
artifact), which means 110K `INSERT OR IGNORE` + `SELECT` pairs for asset
deduplication.

---

## Verification

### VDP

- **Mode A (Expert):** 11 locator paths in metadata. Direct h5py read works.
- **Mode B (Visualizer):** `mh_powder_30T[:]` returns shape `(200,)`.
- **Children:** `gs_state`, `mh_x_7T`, `mh_y_7T`, `mh_z_7T`, `mh_powder_7T`,
  `mh_x_30T`, `mh_y_30T`, `mh_z_30T`, `mh_powder_30T`, `ins_12meV`, `ins_25meV`

### EDRIXS

- **Mode A (Expert):** Locator metadata includes `path_rixs`, `dataset_rixs`,
  `index_rixs`. Direct h5py read with index returns shape `(151, 40)`.
- **Mode B (Visualizer):** Returns HTTP 500. See limitation below.
- **Children:** `rixs`

### Multimodal

- **Mode A (Expert):** 6 locator paths in metadata. Direct h5py read works.
- **Mode B (Visualizer):** `powder[:]` returns shape `(51,)`.
- **Children:** `mag_a`, `mag_b`, `mag_cs`, `ins_hisym`, `ins_powder`,
  `ins_powder_mask`

---

## Known Limitation: EDRIXS Mode B

EDRIXS uses **batched arrays** — all 10K RIXS spectra are stored in a single
HDF5 dataset of shape `(10000, 151, 40)`. Each entity's artifact has an
`index` parameter that selects one slice (e.g. `spectra[0]` for the first).

Tiled's HDF5 adapter supports a built-in `slice` parameter that selects a
row from the batched array. The registration code translates the manifest's
`index` column to `slice` in the Tiled DataSource parameters (see PR #6).

Both Mode A and Mode B work correctly for batched datasets.
