# Testing and Interfaces

> **Version**: 1.0 | **Updated**: 2026-04-04

---

## Testing Standards

### Every module gets a test file

The naming convention is strict: `src/.../foo.py` → `tests/test_foo.py`.
When you create or modify a module, its test file must exist and cover the
change. No exceptions.

### Test markers

Defined in `tests/conftest.py`:

| Marker | Purpose | Run with |
|--------|---------|----------|
| `@pytest.mark.integration` | End-to-end artifact tests (TriG, Cypher, SPARQL) | `pytest -m integration` |
| `@pytest.mark.docker` | Tests requiring Docker (testcontainers Neo4j) | `pytest -m docker` |
| *(unmarked)* | Unit tests — fast, no I/O, no Docker | `pytest -m 'not integration and not docker'` |

### Test patterns

**Unit tests** should:
- Test pure functions with synthetic data (not loaded from files)
- Use dicts/lists that match the real schema, not arbitrary toy data
- Assert specific fields, not just "it didn't crash"
- Cover edge cases: empty inputs, missing keys, zero-length lists

**Integration tests** should:
- Parse actual generated artifacts (Turtle, Cypher, TriG)
- Verify structural correctness (triple counts, node labels, relationships)
- Use `@pytest.mark.integration` so they can be deselected

**Docker tests** should:
- Use `@pytest.mark.docker` and `testcontainers` for Neo4j
- Be self-contained: create, populate, query, and tear down

### What to test when modifying code

| Change type | Required tests |
|-------------|---------------|
| New function | Unit tests for the function |
| Modified function | Update existing tests + add tests for new behavior |
| New CLI entry point | Test the `main()` function with synthetic args |
| Schema change (JSON output) | Verify output structure in test assertions |
| Bug fix | Add a regression test that would have caught the bug |

### Running tests

```bash
# All unit tests (fast)
pytest tests/ -m 'not integration and not docker'

# All tests including integration
pytest tests/

# Specific module
pytest tests/test_ontology_specific.py -v

# Docker tests (requires Docker Desktop running)
pytest tests/ -m docker
```

---

## CLI Interface Contract

### The orchestrator boundary

The OntologyMapper library is consumed by the orchestrator repo via the
installed `ontology-mapper` package. The orchestrator calls:

1. **CLI commands** (`om-*`) — all registered in `pyproject.toml` under
   `[project.scripts]`
2. **Python imports** — `from ontology_mapper.semantic_search import search_type`
   and `from ontology_mapper.ontology_specific import resolve_alignment`

Both are stable interfaces. Changes require coordination with the
orchestrator repo.

### CLI conventions

- All run-scoped commands accept `--run-dir` (or positional run_dir)
- Target ontology is specified via `--target-ontology` and `--target-version`
  — **never default these**
- All commands use `load_context()` to resolve run inputs
- Output is written to the run directory, never to stdout (except status
  messages and progress)
- No interactive prompts (`input()`) — all inputs via CLI flags
- Exit code 0 = success, non-zero = failure

### Current CLI entry points

| Command | Module | Stage |
|---------|--------|-------|
| `om-pipeline` | `pipeline.py` | run lifecycle |
| `om-validate-input` | `validate_input_package.py` | pre-1 |
| `om-extract` | `extract_concepts.py` | 2 (OWL) |
| `om-ingest-csv` | `ingest_csv.py` | 2 (CSV) |
| `om-build-strategy` | `build_strategy_reports.py` | 3 |
| `om-batch-search` | `batch_search.py` | 3 |
| `om-collect-alignments` | `collect_alignments.py` | 3 |
| `om-entropy` | `compute_entropy.py` | 3 |
| `om-residual-entropy` | `compute_entropy.py` | post-5 |
| `om-detect-staleness` | `detect_staleness.py` | utility |
| `om-catalog-search` | `catalog_search.py` | Stage 5 |
| `om-build-matrix` | `build_mapping_matrix.py` | 4 |
| `om-generation-audit` | `generation_audit.py` | 4 |
| `om-generate-ontology` | `generate_edge_ontology.py` | 6 |
| `om-package-artifacts` | `package_edge_artifacts.py` | 6 |
| `om-generate-kg` | `generate_kg_artifacts.py` | 6 |
| `om-validate` | `validate_edge_package.py` | 7 |
| `om-finalize` | `finalize_package.py` | 8 |
| `om-build-manifest` | `build_package_manifest.py` | 6 |
| `om-generate-catalog` | `generate_niem_catalog.py` | one-time |
| `om-generate-owl-catalog` | `generate_owl_catalog.py` | one-time |
| `om-generate-cmf-catalog` | `generate_cmf_catalog.py` | one-time |
| `om-build-vector-index` | `build_vector_index.py` | one-time |
| `om-vector-search` | `vector_search.py` | ad-hoc |
| `om-edge-overlap` | `compute_edge_overlap.py` | post-run |

### Changing a CLI interface

If you change a command's arguments, output format, or behavior:

1. Update the command's module and docstring
2. Update or add tests in `tests/test_{module}.py`
3. Note the change — the orchestrator repo's AGENTS/ docs may reference
   the old interface (the orchestrator maintainer handles that update)

### Python import interface

Functions imported directly by the orchestrator:

```python
# Stage 3: per-concept semantic search
from ontology_mapper.semantic_search import search_type, search_property

# Stage 3: action determination after orchestrator evaluation
from ontology_mapper.ontology_specific import resolve_alignment

# Stage 5: reclassify after user changes target type
from ontology_mapper.ontology_specific import reclassify_for_target_type_change
```

These function signatures are the most stability-critical interfaces in
the library. Changes require careful coordination.

---

## Environment

### Dependencies

| Package | Purpose |
|---------|---------|
| `rdflib` | RDF parsing, serialization, graph manipulation |
| `lxml` | XML processing for CMF serialization |
| `faiss-cpu` | Vector similarity search |
| `sentence-transformers` | Embedding model (BAAI/bge-large-en-v1.5) |
| `pyshacl` | SHACL validation (optional, for validation stage) |

### Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `OM_SPECS_DIR` | Path to reference catalogs, vector indexes, and embedding model | `{package}/specs/` |
| `OM_RUNS_DIR` | Path to pipeline run directories | `.mapper-runs/` (CWD-relative) |

---

## Development Rules

In addition to the hard rules in `AGENTS.md`:

- **Don't break the orchestrator.** CLI signatures and import interfaces
  are the stability boundary. Think before changing them.

---

## Anti-Patterns

- **Tests that don't assert schema shape**: A test that just calls a
  function and checks `len(result) > 0` catches nothing. Assert specific
  fields and values.
- **Mocking the filesystem for pipeline tests**: Use synthetic data dicts
  that match the real schema. If you must mock, mock at the I/O boundary,
  not deep inside the logic.
- **Changing CLI output format silently**: The orchestrator parses stdout
  from some commands (`om-build-strategy` prints reference data paths).
  Changes to output format can break orchestration.
