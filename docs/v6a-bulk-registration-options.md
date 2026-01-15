# V6a Bulk Registration Options

Research notes on optimizing Tiled catalog registration for large datasets.

## Problem Statement

The current V6a registration approach (`register_catalog.py`) makes individual HTTP calls for each node:

```python
# One HTTP POST per Hamiltonian container
h_container = client.create_container(key=h_key, metadata=metadata)

# One HTTP POST per artifact child
h_container.new(
    structure_family=StructureFamily.array,
    data_sources=[data_source],
    key=art_key,
    metadata=art_metadata,
)
```

For the full VDP dataset:
- 10K Hamiltonians × ~11 artifacts each = **~120K HTTP requests**
- Each request = separate database transaction with commit
- Observed rate: ~5 Hamiltonians/sec → **~33 minutes for 10K**

## Tiled Architecture Overview

### Database Schema (from `tiled/catalog/orm.py`)

| Table | Purpose |
|-------|---------|
| `nodes` | Main entities (Hamiltonians, artifacts) |
| `nodes_closure` | Ancestor/descendant relationships (auto-populated via triggers) |
| `data_sources` | How to read files (mimetype, parameters) |
| `structures` | Array structure metadata (content-hashed, deduplicated) |
| `assets` | File URIs |
| `data_source_asset_association` | Links data_sources to assets |

### Key Insight: Closure Table Triggers

The `nodes_closure` table has **database triggers** that automatically maintain the ancestor/descendant hierarchy when nodes are inserted:

```sql
-- SQLite trigger (from orm.py lines 312-326)
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

This means even bulk inserts will trigger per-row closure table updates at the database level.

### Tiled's Current Registration Flow

1. HTTP POST to `/register/{path}` endpoint
2. `create_node()` in `adapter.py:658` creates one node per transaction:
   ```python
   async with self.context.session() as db:
       db.add(node)
       await db.commit()  # Individual commit per node
   ```
3. For each data_source: insert structure, data_source, assets, associations
4. Single commit at end of node creation

---

## Option 1: Direct Catalog Access (No HTTP)

Tiled exposes `tiled.catalog.from_uri()` for direct catalog access without running an HTTP server:

```python
from tiled.catalog import from_uri as catalog_from_uri

# Direct access to catalog (no HTTP server needed)
catalog = catalog_from_uri(
    "sqlite:///path/to/catalog.db",
    writable_storage=["/path/to/data"],
    readable_storage=["/path/to/vdp/data"],
)

# Still uses create_node() internally
await catalog.create_node(
    structure_family=StructureFamily.container,
    metadata=metadata,
    key=key,
)
```

### Trade-offs

| Pros | Cons |
|------|------|
| Eliminates HTTP overhead | Still commits per-node |
| No server required | Must use async context |
| Uses Tiled's validation | Moderate speedup only |

### Expected Improvement

~2-3x faster (eliminates HTTP latency, keeps DB commits)

---

## Option 2: SQLAlchemy Bulk Insert (Recommended)

Use SQLAlchemy's bulk insert capabilities with Tiled's ORM directly:

```python
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from tiled.catalog import orm
from tiled.catalog.utils import compute_structure_id

# Connect to catalog database
engine = create_async_engine("sqlite+aiosqlite:///catalog.db")

async with AsyncSession(engine) as db:
    # 1. Bulk insert Hamiltonian containers
    ham_nodes = [
        {
            "key": f"H_{huid[:8]}",
            "parent": 0,  # Root node ID
            "structure_family": "container",
            "metadata": {"Ja_meV": ..., "Jb_meV": ..., ...},
            "specs": [],
            "access_blob": {},
        }
        for huid, row in hamiltonians.iterrows()
    ]
    result = await db.execute(insert(orm.Node).returning(orm.Node.id, orm.Node.key), ham_nodes)
    ham_id_map = {row.key: row.id for row in result}

    # 2. Bulk insert artifact nodes (children of Hamiltonians)
    art_nodes = [
        {
            "key": art_key,
            "parent": ham_id_map[f"H_{huid[:8]}"],
            "structure_family": "array",
            "metadata": {"type": ..., "axis": ..., ...},
            "specs": [],
            "access_blob": {},
        }
        for art_row in artifacts.iterrows()
    ]
    result = await db.execute(insert(orm.Node).returning(orm.Node.id, orm.Node.key), art_nodes)
    art_id_map = {row.key: row.id for row in result}

    # 3. Bulk insert structures (deduplicated by hash)
    structures = [
        {"id": compute_structure_id(struct), "structure": struct}
        for struct in unique_structures
    ]
    await db.execute(
        insert(orm.Structure).on_conflict_do_nothing(index_elements=["id"]),
        structures
    )

    # 4. Bulk insert data_sources
    data_sources = [...]
    await db.execute(insert(orm.DataSource).returning(orm.DataSource.id), data_sources)

    # 5. Bulk insert assets
    assets = [{"data_uri": uri, "is_directory": False} for uri in unique_uris]
    await db.execute(
        insert(orm.Asset).on_conflict_do_nothing(index_elements=["data_uri"]),
        assets
    )

    # 6. Bulk insert associations
    associations = [...]
    await db.execute(insert(orm.DataSourceAssetAssociation), associations)

    # Single commit for everything
    await db.commit()
```

### Trade-offs

| Pros | Cons |
|------|------|
| Single commit for all data | Bypasses Tiled validation |
| Minimal roundtrips | Must manage IDs manually |
| ~10-50x faster | Closure triggers still fire per-row |
| Works with server running | More complex implementation |

### Expected Improvement

~10-50x faster depending on batch sizes and SQLite vs PostgreSQL

---

## Option 3: Disable Triggers + Bulk Insert + Rebuild Closure

For maximum speed, temporarily disable triggers during bulk load:

```python
async with AsyncSession(engine) as db:
    # 1. Disable closure table trigger
    if dialect == "sqlite":
        await db.execute(text("DROP TRIGGER IF EXISTS update_closure_table_when_inserting"))

    # 2. Bulk insert all nodes (no trigger overhead)
    await db.execute(insert(orm.Node), all_nodes)

    # 3. Rebuild closure table from scratch
    await db.execute(text("DELETE FROM nodes_closure"))

    # Self-references (depth=0)
    await db.execute(text("""
        INSERT INTO nodes_closure (ancestor, descendant, depth)
        SELECT id, id, 0 FROM nodes
    """))

    # Parent-child relationships (depth=1)
    await db.execute(text("""
        INSERT INTO nodes_closure (ancestor, descendant, depth)
        SELECT parent, id, 1 FROM nodes WHERE parent IS NOT NULL
    """))

    # Grandparent relationships (depth=2) - for our 2-level hierarchy
    await db.execute(text("""
        INSERT INTO nodes_closure (ancestor, descendant, depth)
        SELECT gp.ancestor, c.id, 2
        FROM nodes c
        JOIN nodes p ON c.parent = p.id
        JOIN nodes_closure gp ON p.id = gp.descendant AND gp.depth = 1
        WHERE c.parent IS NOT NULL
    """))

    # 4. Re-enable trigger
    # (Would need to recreate the trigger - see orm.py for full SQL)

    await db.commit()
```

### Trade-offs

| Pros | Cons |
|------|------|
| Maximum insert speed | Must stop server during load |
| No per-row trigger overhead | Complex closure rebuild logic |
| Best for initial bulk load | Risk of data corruption if done wrong |

### Expected Improvement

~50-100x faster for initial bulk load

---

## Option 4: Batched HTTP with Async

Keep HTTP but use parallel requests:

```python
import asyncio
import httpx

async def register_hamiltonian(client, ham_data):
    """Register one Hamiltonian with all its artifacts."""
    # Create container
    resp = await client.post(f"{base_url}/register/", json=container_payload)

    # Create artifact children
    tasks = [
        client.post(f"{base_url}/register/{h_key}", json=art_payload)
        for art_payload in ham_data["artifacts"]
    ]
    await asyncio.gather(*tasks)

async def register_all(hamiltonians, batch_size=50):
    async with httpx.AsyncClient() as client:
        for batch in chunks(hamiltonians, batch_size):
            tasks = [register_hamiltonian(client, h) for h in batch]
            await asyncio.gather(*tasks)
```

### Trade-offs

| Pros | Cons |
|------|------|
| Uses official Tiled APIs | Still many HTTP requests |
| Server handles validation | Server must handle concurrent load |
| No direct DB access needed | Connection pool limits |

### Expected Improvement

~3-5x faster with async parallelism

---

## Recommendation

For VDP bulk registration (10K Hamiltonians, ~120K nodes, one-time load):

### Short-term: Option 2 (SQLAlchemy Bulk Insert)

1. Pre-compute all data in memory
2. Use `tiled.catalog.from_uri()` to get database context
3. Bulk insert with SQLAlchemy, single commit
4. Let database triggers handle closure table

**Why**: Best balance of speed and safety. Stays within Tiled's architecture while avoiding HTTP overhead.

### For Production/Repeated Loads: Option 4 (Batched HTTP)

If registration needs to happen with a running server (e.g., incremental updates), use batched async HTTP calls.

---

## Implementation Notes

### Getting Database Session from Tiled

```python
from tiled.catalog import from_uri as catalog_from_uri

catalog = catalog_from_uri("sqlite:///catalog.db")
context = catalog.context

# Use context.session() for database access
async with context.session() as db:
    # SQLAlchemy async session
    result = await db.execute(select(orm.Node))
```

### Structure ID Computation

Tiled deduplicates structures by content hash:

```python
from tiled.catalog.utils import compute_structure_id

structure = {"shape": [200], "dtype": "float64", ...}
structure_id = compute_structure_id(structure)  # MD5 hex digest
```

### Root Node ID

The root node always has `id=0`. Hamiltonian containers should have `parent=0`.

---

## References

- Tiled source: `/sdf/data/lcls/ds/prj/prjcwang31/results/software/tiled`
- ORM definitions: `tiled/catalog/orm.py`
- Catalog adapter: `tiled/catalog/adapter.py`
- Client registration: `tiled/client/register.py`
- [Tiled GitHub](https://github.com/bluesky/tiled)
- [Managing Bluesky Data with Tiled (DESY 2025)](https://indico.desy.de/event/49932/contributions/193947/attachments/100369/139167/DESY_Bluesky_Workshop_2025%20(2).pdf)
