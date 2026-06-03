# Search and Indexing

> **Version**: 1.0 | **Updated**: 2026-04-04

---

## Modules

| Module | CLI | Purpose |
|--------|-----|---------|
| `vector_index.py` | *(library)* | FAISS index build, load, query; OntologyEntry dataclass |
| `build_vector_index.py` | `om-build-vector-index` | CLI for building/managing indexes |
| `vector_search.py` | `om-vector-search` | CLI for cross-ontology similarity search |
| `semantic_search.py` | *(library)* | Per-concept search API (used internally by `batch_search.py`) |
| `batch_search.py` | `om-batch-search` | Batch vector search: writes one JSON file per source concept |
| `collect_alignments.py` | `om-collect-alignments` | Collects evaluated search results, resolves actions, writes alignment report |
| `build_strategy_reports.py` | `om-build-strategy` | Stage 3 prep: source-concepts.json + alignment workspace |

---

## Architecture

### Vector index infrastructure

**Embedding model**: BAAI/bge-large-en-v1.5 (1024-dim, local, no API key).
**Vector store**: FAISS flat L2 index (exact search).

All vector infrastructure lives under `specs/vector/`:

```
specs/vector/
  model/                # Cached embedding model (downloaded by om-build-vector-index)
  indexes/
    {name}-{version}/   # Per-ontology index pair
      types.faiss
      types.meta.json
      properties.faiss
      properties.meta.json
```

Indexes and the model are built/cached once and persisted until explicitly
rebuilt or deleted. The entire `specs/vector/` directory is gitignored.

**Model download policy**: The embedding model is only downloaded from
Hugging Face during `om-build-vector-index` (index building). At query
time (`search_type`, `search_property`), the model must already be cached
— a `FileNotFoundError` is raised if it is missing.

### OntologyEntry dataclass

The core data model for vector indexing. Ontology-agnostic:

```python
@dataclass
class OntologyEntry:
    id: str            # Qualified name (e.g., "j:ArrestType")
    definition: str    # Natural language definition
    kind: str          # "type" or "property"
    context: str = ""  # Additional embedding text (base type, range, paths)
    metadata: dict = field(default_factory=dict)  # Structural info, NOT embedded
```

The embedding text is built from `id + definition + context`. The `metadata`
dict carries structural information (base type, inheritance chain,
augmentation, paths) that is available for post-retrieval reasoning but
is NOT embedded as vector content.

### Index building flow

```
Ontology data (catalog or inventory)
    |
    v
Adapter (catalog_adapter or source_adapter)
    |
    v
List[OntologyEntry]
    |
    v
build_index() → (FAISS index, metadata list)
    |
    v
save_index() → specs/vector/indexes/{name}-{version}/types.faiss + types.meta.json
```

Two adapter paths:
- `--adapter catalog`: Any reference catalog (NIEM, OWL, CMF) via `catalog_adapter.py`
- `--adapter source`: Pipeline concept inventory via `source_adapter.py`

### Semantic search API

The orchestrator calls two functions from `semantic_search.py`:

```python
from ontology_mapper.semantic_search import search_type, search_property

# Returns ranked candidates with score, definition, namespace, metadata
type_candidates = search_type(
    source_concept="court:HearingType",
    source_definition="A scheduled court proceeding.",
    target_ontology="niem-6.0",
    top_k=20,
    source_context="",  # optional additional embedding text
)

property_candidates = search_property(
    source_property="court:hearingDate",
    source_definition="The date of the hearing.",
    target_ontology="niem-6.0",
    top_k=20,
    source_context="",  # optional additional embedding text
)
```

Each function creates an `OntologyEntry` from the source, queries the
target's FAISS index, and returns ranked candidates. The orchestrator
evaluates candidates semantically — it never relies on search scores.

### Stage 3 preparation

`build_strategy_reports.py` (`om-build-strategy`) prepares the alignment
workspace:

1. Loads concept inventory from Stage 2
2. Locates the target ontology's reference catalog in specs/
3. Produces `source-concepts.json` (per-run, all source classes with
   definitions, properties, and superclasses)
4. Writes a placeholder `alignment-report.json` (the orchestrator fills it)
5. Reports paths to reference data files for the orchestrator to read

### Batch search flow

`om-batch-search` and `om-collect-alignments` eliminate all inline Python
from Stage 3. The orchestrator works exclusively with JSON files.

```
1. om-build-strategy --run-dir {run_dir}           (prep workspace)
2. om-batch-search --run-dir {run_dir}              (batch query vector index)
3. Orchestrator: for each file in types/ and properties/:  (Read/Edit — no Python)
     - Read file, evaluate candidates, write evaluation
4. om-collect-alignments --run-dir {run_dir}         (reassemble, resolve actions, assemble report)
```

`om-batch-search` loads the embedding model once, queries the type index
and property index in two batch calls, then writes separate files:

- `{run_dir}/search-results/types/{qname}.json` — one per source type
- `{run_dir}/search-results/properties/{qname}.json` — one per source property

Candidates are filtered: only the top-k (default 25) are queried, then
any scoring below `--min-score-ratio` (default 75%) of the rank-1 score
are dropped. This balances breadth of candidates against noise.

On re-run, files with `status == "evaluated"` are preserved (resumable).

`om-collect-alignments` reads type and property files, reassembles
per-concept evaluations (type + its properties grouped by `parentType`),
calls `resolve_alignment()` on each, and writes the completed
`alignment-report.json`. Fails if any files are still pending
(use `--allow-pending` to skip them).

`semantic_search.py` provides per-concept wrappers (`search_type()`,
`search_property()`) for direct orchestrator use. `batch_search.py` uses
the lower-level `query_index()` from `vector_index.py` directly for
batch efficiency.

---

## Contracts

### What the orchestrator depends on

- `om-batch-search` writes type files to `search-results/types/` and property files to `search-results/properties/`
- `om-collect-alignments` reads evaluated files and writes `alignment-report.json`
- `om-build-strategy` prints paths to reference data files on stdout

### Index naming convention

The `target_ontology` argument uses the format `{name}-{version}`:
- `niem-6.0`
- `sali-folio-2.0`
- `nods-1.0`

This maps to the index directory `specs/vector/indexes/{name}-{version}/`.

---

## Development Rules

In addition to the hard rules in `AGENTS.md`:

- **Embedding text is id + definition + context.** The `metadata` dict is
  NOT embedded. If you need structural info in the embedding, add it to
  the `context` field via the adapter.
- **Adapters are the format boundary.** All ontology-specific format parsing
  happens in adapters. `vector_index.py` and `semantic_search.py` are
  ontology-agnostic.
- **Scores are for ranking, not for decisions.** The orchestrator uses scores
  to rank candidates but makes decisions based on semantic evaluation of
  definitions and structural metadata. Never threshold on scores.
- **Indexes are immutable once built.** To update, use `--rebuild` or
  `--delete` + rebuild. Never modify index files in place.
- **Model is only downloaded at build time.** Query-time code must never
  trigger a download. If the model cache is missing, fail with a clear
  error pointing to `om-build-vector-index`.

---

## Anti-Patterns

- **Embedding structural metadata**: The `metadata` dict exists for
  post-retrieval reasoning. If it gets embedded, it pollutes the semantic
  signal.
- **Namespace-by-namespace searching**: The orchestrator searches
  concept-by-concept across ALL namespaces. Namespace-by-namespace
  browsing causes asymmetric attention.
