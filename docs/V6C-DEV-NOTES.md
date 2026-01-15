# V6c Bulk Registration Development Notes

Development notes for the SQLAlchemy bulk registration experiment.

## Problem Statement

Tiled's catalog uses a **closure table** (`nodes_closure`) to enable efficient ancestor/descendant queries. A database trigger automatically maintains this table on every node insert:

```sql
CREATE TRIGGER update_closure_table_when_inserting
AFTER INSERT ON nodes
BEGIN
    INSERT INTO nodes_closure(ancestor, descendant, depth)
    SELECT NEW.id, NEW.id, 0;
    INSERT INTO nodes_closure(ancestor, descendant, depth)
    SELECT p.ancestor, c.descendant, p.depth+c.depth+1
    FROM nodes_closure p, nodes_closure c
    WHERE p.descendant=NEW.parent and c.ancestor=NEW.id;
END
```

**Impact on bulk registration:**
- Each node insert triggers 2 sub-queries with a Cartesian join
- Per Cybertec benchmarks, row-level triggers cause ~13x slowdown
- 10K Hamiltonians × 11 artifacts = 120K trigger executions
- Estimated HTTP registration time: **~33 minutes**

## Solution: Trigger Disable/Rebuild Pattern

Bypass the per-row trigger overhead by:

1. **Disable** the closure table trigger before bulk insert
2. **Bulk insert** all tables in a single transaction
3. **Rebuild** the closure table with set-based SQL
4. **Re-enable** the trigger for future incremental updates

This is a standard pattern for bulk loading hierarchical data.

## Implementation

### Files Created

```
$PROJ_VDP/tiled_poc_v6c/
├── config.yml          # Tiled server config (port 8004)
├── bulk_register.py    # Bulk registration script
└── catalog.db          # SQLite database (created by script)
```

### Key Techniques

**1. Initialize schema via Tiled, then use raw SQLAlchemy:**
```python
from tiled.catalog import from_uri as catalog_from_uri

# Let Tiled create schema with triggers
catalog_from_uri(uri, init_if_not_exists=True, ...)

# Then use raw SQLAlchemy for bulk operations
engine = create_engine(f"sqlite:///{db_path}")
```

**2. Structure ID computation (for deduplication):**
```python
import hashlib
import canonicaljson

def compute_structure_id(structure):
    canonical = canonicaljson.encode_canonical_json(structure)
    return hashlib.md5(canonical).hexdigest()
```

**3. Closure table rebuild SQL (for 2-level hierarchy):**
```sql
-- Self-references (depth=0)
INSERT INTO nodes_closure (ancestor, descendant, depth)
SELECT id, id, 0 FROM nodes;

-- Parent-child (depth=1)
INSERT INTO nodes_closure (ancestor, descendant, depth)
SELECT parent, id, 1 FROM nodes WHERE parent IS NOT NULL;

-- Grandparent (depth=2)
INSERT INTO nodes_closure (ancestor, descendant, depth)
SELECT gp.parent, n.id, 2
FROM nodes n
JOIN nodes gp ON n.parent = gp.id
WHERE gp.parent IS NOT NULL;
```

**4. Chunk format for multi-dimensional arrays:**
```python
# Chunks must be list of lists, one per dimension
# For shape [600, 400]:
chunks = [[600], [400]]  # NOT [[600, 400]]
```

## Performance Results

### Registration Benchmarks

| Dataset | Nodes | HTTP (est.) | SQLAlchemy | Speedup |
|---------|-------|-------------|------------|---------|
| 10 Hamiltonians | 121 | ~2s | 0.1s | 20x |
| 1K Hamiltonians | 12,001 | ~3.3 min | 5.0s | 40x |
| **10K Hamiltonians** | **120,001** | **~33 min** | **53.3s** | **37x** |

**Rate:** ~2,250 nodes/sec (consistent across dataset sizes)

### Database Statistics (10K Hamiltonians)

| Table | Rows |
|-------|------|
| nodes | 120,001 |
| nodes_closure | 350,001 |
| data_sources | 110,000 |
| structures | 3 |
| assets | 110,000 |
| associations | 110,000 |

### Retrieval Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| Count Hamiltonians | 12 ms | Fast DB query |
| List 200 keys | 51 ms | Pagination |
| Access metadata | 20 ms | Single node |
| List 11 artifacts | 33 ms | Child enumeration |
| Query `Ja_meV > 0.5` | 21 ms | Metadata search |
| Read mh_powder_30T (cold) | **1,231 ms** | First HDF5 open |
| Read mh_powder_30T (warm) | 57 ms | Cached |
| Read ins_12meV (600x400) | 125 ms | Larger array |
| Build 100-curve dataset | 17,304 ms | 173 ms/curve |

## Key Findings

1. **Database queries are fast** - metadata access, counting, searching all under 50ms
2. **HDF5 I/O is the bottleneck** - cold reads ~1.2s, warm reads ~57ms
3. **Per-curve loading is slow** - each Hamiltonian's data is in a separate file
4. **Closure table rebuild works correctly** - verified hierarchy traversal
5. **Trigger re-enabled** - incremental updates via Tiled API still work

## Usage

### Run Bulk Registration

```bash
cd $PROJ_VDP/tiled_poc_v6c

# Register 10 Hamiltonians (default)
uv run --with 'tiled[server]' --with pandas --with pyarrow \
  --with h5py --with canonicaljson --with 'ruamel.yaml' \
  python bulk_register.py

# Register all 10K Hamiltonians
VDP_MAX_HAMILTONIANS=10000 uv run --with 'tiled[server]' \
  --with pandas --with pyarrow --with h5py --with canonicaljson \
  --with 'ruamel.yaml' python bulk_register.py
```

### Start Tiled Server

```bash
cd $PROJ_VDP/tiled_poc_v6c
uv run --with 'tiled[server]' tiled serve config config.yml --api-key secret
```

### Test Retrieval

```bash
uv run --with 'tiled[server]' --with pandas python -c "
from tiled.client import from_uri
client = from_uri('http://localhost:8004', api_key='secret')
print(f'Hamiltonians: {len(client)}')
h = client[list(client)[0]]
print(f'Artifacts: {list(h)}')
data = h['mh_powder_30T'].read()
print(f'Shape: {data.shape}')
"
```

### Verify Database Integrity

```bash
cd $PROJ_VDP/tiled_poc_v6c
sqlite3 catalog.db "
SELECT 'Trigger exists:' as check, name FROM sqlite_master
WHERE type='trigger' AND name='update_closure_table_when_inserting';

SELECT 'Closure by depth:' as check, depth, COUNT(*)
FROM nodes_closure GROUP BY depth;
"
```

## Future Improvements

1. **Parallel HDF5 I/O** - Use `concurrent.futures` for `build_mh_dataset()`
2. **Data consolidation** - Consider storing multiple curves per file
3. **Caching** - Cache frequently accessed arrays in memory
4. **PostgreSQL** - Test with PostgreSQL for production deployment

## References

- Research notes: `$PROJ_VDP/docs/v6a-bulk-registration-options.md`
- Tiled ORM: `$TILED_DIR/tiled/catalog/orm.py`
- Closure table triggers: orm.py lines 308-368
