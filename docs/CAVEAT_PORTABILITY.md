# V6a Portability Notes

## What "Standalone" Means

The V6a service is standalone in the sense that:

- **All configuration is in one file** (`config.yml`)
- **No environment variables required** (no `$PROJ_VDP`, etc.)
- **Can run from any working directory** - just pass the full path to config.yml

## Moving the Service

If you move `tiled_poc_v6a/` to a new location, update these paths in `config.yml`:

```yaml
# 1. Tiled server paths (where catalog.db and storage/ live)
trees:
  - path: /
    tree: catalog
    args:
      uri: "sqlite:////new/location/tiled_poc_v6a/catalog.db"
      writable_storage: "/new/location/tiled_poc_v6a/storage"

# 2. Python scripts path
vdp:
  service_dir: "/new/location/tiled_poc_v6a"
```

Note: SQLite absolute paths require 4 slashes: `sqlite:////absolute/path`

## Data Paths (Usually Don't Change)

These paths point to the HDF5 data files. They typically stay the same unless you also move the data:

```yaml
trees:
  - args:
      readable_storage:
        - "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp/data/schema_v1"

vdp:
  data_dir: "/sdf/data/lcls/ds/prj/prjmaiqmag01/results/vdp"
```

## Quick Reference

| Path in config.yml | What it controls | Update when moving service? |
|--------------------|------------------|----------------------------|
| `trees.args.uri` | catalog.db location | Yes |
| `trees.args.writable_storage` | storage/ directory | Yes |
| `vdp.service_dir` | Service directory for Python scripts | Yes |
| `trees.args.readable_storage` | HDF5 data location | Only if data moves |
| `vdp.data_dir` | VDP data root | Only if data moves |

## Running After Moving

```bash
# From any directory:
uv run --with 'tiled[server]' tiled serve config \
  /new/location/tiled_poc_v6a/config.yml --api-key secret
```
