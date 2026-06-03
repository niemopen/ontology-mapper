# OntologyMapper — Runner

Automated pipeline runner for the [OntologyMapper](../README.md). `run_pipeline.py` executes all pipeline stages end-to-end: running `om-*` CLI tools, using `claude -p` for bounded LLM evaluation (Stage 3) and natural-language review interpretation (Stage 5), and producing aligned edge packages for target ontologies (NIEM, SALI/FOLIO, etc.).

## Structure

```
CLAUDE.md                          # Session mode rules (developer vs pipeline run)
AGENTS.md                          # Pipeline rules, tool inventory, issue routing
AGENTS/
  Pipeline__RUNBOOK.md             # Stage-by-stage command reference
  Pipeline__SEMANTIC_SEARCH.md     # Semantic search guidance
  Pipeline__PROJECT_RULES.md       # Schemas, valid actions, decision rules
  edge-package-spec.md             # Edge package structure and conformance

runner_tools/                # Pipeline tools
  run_pipeline.py                  # Automated runner — full pipeline with interactive Stage 5
  verify_stage_outputs.py          # Post-stage artifact verification
  _present_and_apply_human_review.py           # Human review API
  preflight_specs.py               # Target ontology specs pre-flight inspection
  feedback_report.py               # Map validation failures to source decisions
  run_feedback.py                  # Log observations during runs

sources/                           # Input source packages
.mapper-runs/                    # Pipeline run artifacts (gitignored)
```

## Setup

```bash
# Install the pipeline tools package (all extras for orchestration)
pip install -e "../mapper[validation,vector]"

# Set runs directory
export OM_RUNS_DIR=$(pwd)/.mapper-runs

# Verify
om-pipeline help
```

**Dependencies installed by extras:**
- `validation`: `pyshacl` — SHACL conformance checks (Stage 7)
- `vector`: `faiss-cpu`, `sentence-transformers` — vector similarity search (Stage 3)

## Prerequisites: Generating Catalogs and Vector Indexes

Before the first pipeline run against a target ontology, two artifacts must exist:

1. **A reference catalog** for the target ontology and version — bundled as package data under `ontology_mapper/specs/`.
2. **A vector index** built from that catalog — used by Stage 3 for semantic candidate retrieval.

Catalog generation is owned by the `ontology-mapper` package. See the [mapper README — Reference Catalogs](../mapper/README.md#reference-catalogs) for the authoritative details (API sources, enrichment flags, offline mode, regeneration policy).

Minimum commands to stand up a fresh install:

```bash
# Catalog — NIEM (API + GitHub CSV enrichment)
om-generate-catalog --version 6.0

# Catalog — SALI/FOLIO (from the FOLIO OWL file)
om-generate-owl-catalog --input LMSS.owl --name sali-folio --version 2.0 --label-as-name

# Catalog — NODS (from a CMF XML file; NIEM-derived message specs use this path)
om-generate-cmf-catalog --input nods.cmf --name nods --version 1.0 --niem-version 6.0

# Vector index — one per target ontology/version
om-build-vector-index --ontology niem       --adapter catalog --version 6.0
om-build-vector-index --ontology sali-folio --adapter catalog --version 2.0
om-build-vector-index --ontology nods       --adapter catalog --version 1.0
```

Inspect and manage indexes:

```bash
om-build-vector-index --list                              # show existing indexes
om-build-vector-index --ontology niem --adapter catalog --version 6.0 --rebuild
om-build-vector-index --ontology niem --delete
```

## Session Mode

Developer mode (see `CLAUDE.md`): build and maintain tools in `runner_tools/` and `../mapper/`. Pipeline runs are executed via `run_pipeline.py`, not by the LLM.

## Supported Target Ontologies

| Ontology | Key | Versions |
|----------|-----|----------|
| [NIEMOpen](https://www.niemopen.org/) (NIEM) | `niem` | 6.0 |
| [SALI/FOLIO](https://www.sali.org/) | `sali-folio` | 2.0 |
| NODS (NIEM message spec, CMF-derived) | `nods` | 1.0 |

## Pipeline Stages

| Stage | Tool | Purpose |
|-------|------|---------|
| 1 | `om-pipeline rerun --stage 1` | Ingest and validate input package |
| 2 | `om-extract` / `om-ingest-csv` | Extract concept inventory |
| 3 | `om-build-strategy` + `om-batch-search` + `om-entropy` + `om-orchestrate-eval` + `om-collect-alignments` | Semantic alignment against target ontology |
| 4 | `om-build-matrix` | Build mapping matrix from alignment report |
| 5 | `_present_and_apply_human_review.py` | Interactive human review gate |
| 6a | `om-generate-ontology` | Generate OWL/TTL |
| 6b | `om-package-artifacts` | Package non-OWL artifacts |
| 6c | `om-generate-kg` | Generate knowledge graph artifacts |
| 7 | `om-validate` | Validate edge package |
| 8 | `om-finalize` | Finalize and version package |

## Tests

```bash
python -m pytest runner_tools/ -v
```
