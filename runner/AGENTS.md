# Pipeline Rules for OntologyMapper

> **Version**: 3.0 | **Last Updated**: 2026-04-09

---

## How the Pipeline Runs

The automated runner (`runner_tools/run_pipeline.py`) executes all pipeline
stages end-to-end. Stages 1-4 and 6-8 are mechanical command sequences. Stage 3
uses `om-orchestrate-eval` for bounded concurrent LLM evaluation via `claude -p`.
Stage 5 is an interactive review loop: it presents pending items, reads user input,
uses `claude -p` to interpret the input into structured actions, and loops until
all items are reviewed.

There is no LLM orchestrator. The pipeline is driven by Python code, not by an LLM
reading instructions and executing commands one at a time.

**Pipeline tools are installed as**: the `ontology-mapper` package (`pip install -e ../mapper`)

---

## Core Rules

### Code Boundary — What Lives Where

> **"Does this produce or transform a pipeline artifact?"**
> → `ontology-mapper` package (`mapper/`)
>
> **"Does this support running, reviewing, or verifying the pipeline?"**
> → `runner_tools/` (`runner/`)

| Belongs in OntologyMapper (pipeline) | Belongs in runner_tools |
| --- | --- |
| `om-*` CLI commands | `verify_stage_outputs.py` |
| Stage artifact generators | `_present_and_apply_human_review.py` |
| `apply_decision_rules.py` | `run_feedback.py` |
| `resolve_run_dir()` | `feedback_report.py` |
| State persistence (`load_state`, `State.save`) | `preflight_specs.py` |
| CMF/OWL/TTL producers | `run_pipeline.py` (automated runner) |

**Why**: The pipeline engine (`ontology-mapper`) is runner-agnostic — it could be
driven by `run_pipeline.py`, a different script, or manual CLI invocations. Keeping
this boundary clean prevents coupling the engine to a specific execution approach.

### Semantic Evaluation at Stage 3

- `om-batch-search` pre-populates vector search results as separate files: one per source type in `search-results/types/`, one per source property in `search-results/properties/`
- `om-orchestrate-eval` evaluates all pending files via bounded concurrent `claude -p` calls — each file gets a separate invocation with full candidate context
- After all files are evaluated, `om-collect-alignments` reassembles per-concept evaluations and resolves actions

---

## Pipeline Tool Invocations

All pipeline tools are installed as CLI entry points via the `ontology-mapper` package:

```bash
om-{command} [args]
```

Key tools by stage:
- **Stage 1 (Ingest)**: `om-pipeline rerun --stage 1`
- **Stage 2 (Extract)**: `om-extract` or `om-ingest-csv`
- **Stage 3 (Align)**: `om-build-strategy`, `om-batch-search`, `om-orchestrate-eval`, `om-collect-alignments`
- **Stage 4 (Decide)**: `om-build-matrix`
- **Stage 5 (Review)**: `_present_and_apply_human_review.py` (interactive loop in `run_pipeline.py`)
- **Stage 6a (Generate)**: `om-generate-ontology`
- **Stage 6b (Package)**: `om-package-artifacts`
- **Stage 6c (KG)**: `om-generate-kg`
- **Stage 7 (Validate)**: `om-validate`
- **Stage 8 (Finalize)**: `om-finalize`

See `AGENTS/Pipeline__RUNBOOK.md` for the full stage-by-stage command reference.

---

## Appendix Index

| Document | Contents |
| -------- | -------- |
| [AGENTS/Pipeline__RUNBOOK.md](AGENTS/Pipeline__RUNBOOK.md) | Stage-by-stage command reference, environment setup, tool invocations |
| [AGENTS/Pipeline__SEMANTIC_SEARCH.md](AGENTS/Pipeline__SEMANTIC_SEARCH.md) | Semantic search evaluation guidance: element-first search, property-path concepts, type patterns, action selection |
| [AGENTS/Pipeline__REFERENCE.md](AGENTS/Pipeline__REFERENCE.md) | Quick reference, common pitfalls, tool inventory, state management |
| [AGENTS/Pipeline__PROJECT_RULES.md](AGENTS/Pipeline__PROJECT_RULES.md) | Data schemas, valid actions, alignment/mapping contracts, review status lifecycle |
| [AGENTS/Target_OWL_Patterns.md](AGENTS/Target_OWL_Patterns.md) | OWL emission patterns per target ontology: NIEM reuse/extend/augment, SALI/FOLIO alignment |
| [AGENTS/Boundary_Coherence__REFERENCE.md](AGENTS/Boundary_Coherence__REFERENCE.md) | Boundary coherence theory, implemented measurement capabilities, paper reference |
| [AGENTS/edge-package-spec.md](AGENTS/edge-package-spec.md) | Edge package structure, artifact schemas, conformance requirements |
| [runner_tools/](runner_tools/) | Pipeline tools (runner, verification, review, feedback) |
