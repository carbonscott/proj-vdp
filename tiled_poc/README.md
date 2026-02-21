# Generic Broker for Tiled Catalog Registration

A **config-driven** system for registering HDF5 simulation datasets into a [Tiled](https://blueskyproject.io/tiled/) catalog. Users describe their data in a YAML file; the broker handles inspection, manifest generation, and registration.

## Onboarding Workflow

```
1. Inspect       2. Review YAML     3. Generate       4. Ingest & Serve
   broker.inspect → draft YAML → user confirms → broker.generate → tiled serve
   (auto-scans)    (~2 min edit)                  (Parquet manifests)
```

### Step 1: Inspect a dataset

Point the inspector at a directory of HDF5 files. It scans the structure and produces a **draft YAML** with auto-detected parameters, artifacts, and shared axes:

```bash
cd tiled_poc

uv run --with h5py --with numpy \
  python -m broker.inspect /path/to/data/ --output datasets/draft_mydata.yml
```

The draft YAML includes `# TODO` markers for the two fields only the user can provide (`label` and `key_prefix`), plus comments showing parameter ranges, artifact shapes, and consistency results.

### Step 2: Review and finalize the YAML

Fill in identity fields and confirm the auto-detected classifications:

```yaml
label: edrixs_sbi              # your dataset name
key_prefix: edrixs              # short prefix for Tiled keys

data:
  directory: /path/to/data
  file_pattern: "*/simulations.h5"
  layout: batched               # per_entity | batched | grouped

parameters:
  location: group
  group: /params

artifacts:
  - type: rixs_spectrum
    dataset: /spectra

shared:
  - type: eloss
    dataset: /eloss
```

### Step 3: Generate manifests

```bash
uv run --with h5py --with numpy --with pandas --with pyarrow --with 'ruamel.yaml' \
  python -m broker.generate datasets/edrixs_sbi.yml
```

Produces `manifests/<label>/entities.parquet` and `artifacts.parquet`.

### Step 4: Ingest and serve

```bash
# Start server
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret

# Register (via existing bulk_register or http_register)
uv run --with 'tiled[server]' --with pandas --with pyarrow --with h5py \
  --with canonicaljson --with 'ruamel.yaml' \
  python scripts/bulk_register.py -n 10000
```

## Supported Data Layouts

| Layout | Description | Example |
|--------|-------------|---------|
| `per_entity` | One HDF5 file per entity, scalars at root are parameters | NiPS3 Multimodal (7,616 files) |
| `batched` | Entities stacked along axis-0, parameters in a group | EDRIXS SBI (5 files × 2,000) |
| `grouped` | One HDF5 group per entity inside a file | SUNNY EXP mesh (12,800 groups) |

### What the inspector auto-discovers

| Information | How |
|---|---|
| File list and glob pattern | `Path.rglob("*.h5")` |
| Layout type | Shape heuristics: scalars + many files → per_entity; shared axis-0 → batched |
| Parameters | Scalars at root, or arrays under a `/params/` group |
| Artifact shapes and dtypes | Read from first HDF5 file |
| Shared axis properties | Detected by axis-0 mismatch; verified identical across files |
| Provenance | HDF5 attributes at root and group level |
| Consistency | Cross-file structure and shared axis value comparison |

### What the user must provide

| Field | Why |
|---|---|
| `label` | Only the user knows the semantic dataset name |
| `key_prefix` | Must be chosen to avoid collisions across datasets |
| Artifact vs axis | The inspector can't distinguish output observables from coordinate grids in per-entity files |

### Batched slicing

For batched datasets, the broker uses Tiled's **native** `slice` parameter on `HDF5ArrayAdapter`. At registration time, each entity's artifact gets `{"dataset": "/spectra", "slice": "42"}` in the DataSource parameters. Tiled lazily loads only that slice — no custom adapter needed.

## Datasets Tested

| Dataset | Layout | Entities | Params | Artifacts | Status |
|---|---|---|---|---|---|
| EDRIXS SBI (Sam) | batched (5 × 2K) | 10,000 | 12 | rixs_spectrum (151×40) | Manifests generated |
| NiPS3 Multimodal | per_entity (7.6K files) | 7,616 | 9 | hisym, powder, powder_mask, mag_a/b/cs | Manifests generated |
| SUNNY 10K | batched (1 × 10K) | 10,000 | 9 | sqe_hisym (384×384) | Manifests generated |
| SUNNY EXP mesh | grouped (1 file) | 12,800 | 9 | sqe_exp (2100×384) | YAML ready |
| EDRIXS (Tlinker) | batched (2 × 10K) | 20,000 | 12 | spectra (151×40) | Inspected |
| VDP | per_entity (110K files) | 10,000 | 4 | gs_state, mh_curves, ins_powder | Legacy manifests |

## Directory Structure

```
tiled_poc/
├── config.yml              # Tiled server configuration
├── broker/                 # Generic broker package (NEW)
│   ├── __init__.py
│   ├── inspect.py          # HDF5 inspection engine + draft YAML emitter
│   ├── generate.py         # Generic manifest generator (per_entity/batched/grouped)
│   └── schema.py           # YAML contract validation
├── datasets/               # Per-dataset YAML configs and generated manifests (NEW)
│   ├── edrixs_sbi.yml
│   ├── nips3_multimodal.yml
│   ├── sunny_10k.yml
│   ├── draft_*.yml         # Auto-generated drafts from inspector
│   └── manifests/          # Generated Parquet manifests
├── scripts/                # VDP-specific registration (existing)
│   ├── config.py
│   ├── utils.py
│   ├── register_catalog.py
│   ├── bulk_register.py
│   └── query_manifest.py
├── examples/               # Demo scripts
│   ├── demo_dual_mode.py
│   ├── demo_mh_dataset.py
│   └── demo_mh_dataset_with_query.py
└── tests/                  # Test suite
    ├── conftest.py
    ├── test_config.py
    ├── test_utils.py
    ├── test_registration.py
    └── test_data_retrieval.py
```

## Dual-Mode Data Access

Both modes access the same underlying data:

- **Mode A (Expert):** Query entity metadata for HDF5 paths (`path_*`, `dataset_*`, `index_*`), load directly with h5py. Best for ML pipelines and bulk loading.
- **Mode B (Visualizer):** Access arrays as Tiled children via HTTP (`client["edrixs_000042"]["rixs_spectrum"][:]`). Supports chunked slicing for large arrays.

## VDP-Specific Registration (Legacy)

The original VDP registration scripts remain in `scripts/` for backward compatibility. See `CLAUDE.md` for VDP-specific run instructions.

## Running Tests

```bash
# Unit tests (no server required)
uv run --with pytest pytest tests/test_config.py tests/test_utils.py -v

# Integration tests (requires running server with data)
uv run --with pytest --with 'ruamel.yaml' pytest tests/ -v
```
