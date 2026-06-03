# OntologyMapper — Developer Rules

> **Version**: 3.0 | **Updated**: 2026-04-04 | **Target**: <200 lines

---

## Role

You are working on the **pipeline tools library** (`ontology-mapper` package).
You write, test, and maintain the deterministic pipeline stage tools that
transform source ontologies into target-ontology-aligned edge packages.

You do **NOT**:
- Orchestrate pipeline runs or execute the pipeline end-to-end
- Perform semantic matching (that's the orchestrator's job)
- Modify anything in `../runner/` (the orchestrator)

The runner consumes this package via editable install. CLI signatures and
Python import interfaces are stability-critical — see
`AGENTS/OM__TESTING_AND_INTERFACES.md`.

---

## Priority Rules

| Level | Focus | Rule |
|-------|-------|------|
| **P0** | Data integrity | Never commit secrets. Never modify source ontology packages. |
| **P1** | Correctness | Every change gets tests. Bugs fixed before features. |
| **P2** | Scope | Only modify what's needed. No "while I'm here" refactoring. |
| **P3** | Simplicity | Prefer simple solutions. Improve incrementally. |

If rules conflict, higher priority wins.

---

## Hard Rules

1. **Test every change.** `src/.../foo.py` → `tests/test_foo.py` must exist
   and cover the change. No exceptions.
2. **No NIEM defaults.** `--target-ontology` and `--target-version` are always
   required. This pipeline is ontology-agnostic — never default to `niem`
   or `6.0`.
3. **No interactive prompts.** All inputs via CLI flags. The orchestrator
   runs these tools programmatically.
4. **UTC timestamps with trailing Z.** All shared timestamps use this format.
   Tests must assert it.
5. **Read before writing.** Always read a file before modifying it.
6. **reviewStatus values**: Only `pending-review` and `accepted`. Never use
   `decided`, `approved`, `auto-accepted`, or `human-approved`.
7. **Property actions**: Only `reuse-property` and `create-property`. Never
   use `extend-property`.
8. **No semantic reasoning in tools.** Tools are deterministic transformers.
   The orchestrator (Claude Code in orchestrator mode) does all semantic
   reasoning. `resolve_alignment()` applies structural rules, not reasoning.
9. **No keyword/heuristic matching.** All matching is LLM semantic reasoning
   by the orchestrator. Never add scoring thresholds, keyword filters, or
   `matchType`/`confidence` labels.

---

## Architectural Domains

Each domain file describes the modules, architecture, contracts, development
rules, and anti-patterns for its domain. **Read the relevant domain file
before modifying any module.**

| Domain | File | Modules |
|--------|------|---------|
| Pipeline Engine | [OM__PIPELINE_ENGINE.md](AGENTS/OM__PIPELINE_ENGINE.md) | `pipeline.py`, `pipeline_config.py`, `pipeline_context.py`, `run_dir_utils.py`, `build_mapping_matrix.py` |
| Generators | [OM__GENERATORS.md](AGENTS/OM__GENERATORS.md) | `generate_edge_ontology.py`, `generate_cmf_from_matrix.py`, `generation_utils.py`, `generate_kg_artifacts.py`, `package_edge_artifacts.py`, `generate_niem_catalog.py`, `generate_owl_catalog.py`, `generate_cmf_catalog.py`, `build_package_manifest.py`, `finalize_package.py`, `generation_audit.py` |
| Ontology Adapters | [OM__ONTOLOGY_ADAPTERS.md](AGENTS/OM__ONTOLOGY_ADAPTERS.md) | `ontology_specific.py`, `owl_cmf_bridge.py`, `extract_concepts.py`, `ingest_csv.py`, `adapters/` |
| Search & Indexing | [OM__SEARCH_AND_INDEXING.md](AGENTS/OM__SEARCH_AND_INDEXING.md) | `vector_index.py`, `build_vector_index.py`, `vector_search.py`, `semantic_search.py`, `batch_search.py`, `collect_alignments.py`, `build_strategy_reports.py` |
| Validation | [OM__VALIDATION.md](AGENTS/OM__VALIDATION.md) | `validate_input_package.py`, `validate_edge_package.py`, `quality_gates.py`, `compute_edge_overlap.py` |
| Testing & Interfaces | [OM__TESTING_AND_INTERFACES.md](AGENTS/OM__TESTING_AND_INTERFACES.md) | Test conventions, CLI contract, orchestrator boundary, environment |

---

## Pre-Completion Checklist

Before marking any task complete:

- [ ] Change follows existing patterns in the domain
- [ ] All new/modified code has tests
- [ ] All tests pass (`pytest tests/ -m 'not docker'`)
- [ ] Only modified necessary components
- [ ] CLI signatures unchanged (or change noted for orchestrator update)
- [ ] No hardcoded NIEM references in ontology-agnostic code

---

## Code Boundaries

| Belongs in OntologyMapper | Belongs in Orchestrator |
|----------------------------|------------------------|
| Deterministic transforms (matrix builder, generators) | Semantic reasoning (alignment, review) |
| Reference data management (catalogs, indexes) | Stage execution orchestration |
| Validation tools | Human review presentation |
| Ontology-specific structural rules (`resolve_alignment`) | Pipeline run decisions |
| Vector index building and querying | Observation logging, GitHub issue filing |

If you're writing code that makes semantic judgments about ontology
alignment, it belongs in the orchestrator, not here.
