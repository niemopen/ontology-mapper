# Pipeline Engine

> **Version**: 1.0 | **Updated**: 2026-04-04

---

## Modules

| Module | CLI | Purpose |
|--------|-----|---------|
| `pipeline.py` | `om-pipeline` | State machine, stage definitions, run lifecycle |
| `pipeline_config.py` | *(library)* | Threshold defaults, per-run config overrides |
| `pipeline_context.py` | *(library)* | Resolved inputs and derived naming conventions |
| `run_dir_utils.py` | *(library)* | Run directory resolution, state I/O, specs path |
| `build_mapping_matrix.py` | `om-build-matrix` | Stage 4: reshape alignment report into mapping matrix |

---

## Architecture

### Run directory layout

Each pipeline run gets an isolated directory under `.mapper-runs/`:

```
.mapper-runs/
  {org}_{YYYYMMDD-HHMMSS}/
    .mapper-state.json     # Pipeline state (inputs, stages, progress)
    source-inventory.json    # Stage 1 output
    concept-inventory.json   # Stage 2 output
    source-concepts.json     # Stage 3 prep
    search-results/          # Stage 3: vector search results (om-batch-search)
      types/                 #   one file per source type
      properties/            #   one file per source property
    alignment-report.json    # Stage 3 output (om-collect-alignments writes this)
    mapping-matrix.json      # Stage 4 output
    decision-log.json        # Stage 4 output
    generation-audit.json    # Stage 4 output (om-generation-audit)
    validation-report.json   # Stage 7 output
    edge-package/            # Stage 6+ output artifacts
```

The `OM_RUNS_DIR` env var overrides the `.mapper-runs/` root.
The orchestrator repo sets this to keep run artifacts in its own tree.

### State machine

`PipelineState` tracks inputs, stage results, and the highest completed stage.
Each `StageResult` records status (`completed`, `failed`, `skipped`,
`pending_review`, `pending`), timestamps, artifacts, and optional error/notes.

Stages are defined as `StageSpec` dataclasses in `STAGES` list:

| Stage | Name | Key property |
|-------|------|-------------|
| 1 | Ingest | |
| 2 | Extract | |
| 3 | Align | |
| 4 | Decide | |
| 5 | Review | `requires_human_review=True` |
| 6 | Generate | |
| 7 | Validate | |
| 8 | Finalize | |

The CLI supports: `om-pipeline` (new run), `rerun` (resume/jump), `status`,
`replay`, `mark-complete`, `help`.

### PipelineContext

All stage tools use `PipelineContext` instead of constructing f-strings.
It provides derived names (edge_package_name, namespace URIs, file prefixes)
from the resolved inputs. Created via `load_context(run_dir)` which reads
`.mapper-state.json` and validates that `target_ontology` and
`target_version` are present.

### Configuration

`pipeline_config.py` holds threshold defaults (currently
`property_composition_max_depth: 2`). Per-run overrides via a `thresholds`
key in `.mapper-state.json`. All stage tools call `load_config()`.

### Run directory resolution

`run_dir_utils.py` resolves run directories in priority order:
1. Explicit CLI `--run-dir` argument
2. Filter by org prefix (if `--org` given)
3. Most recent run directory (by folder-name timestamp)

Windows Git Bash paths (`/c/dev/...`) are normalized to native paths.

---

## Contracts

### What the orchestrator depends on

- `om-pipeline` creates the run directory and writes `.mapper-state.json`
  with `inputs.organization`, `inputs.source`, `inputs.input_package_path`,
  `inputs.target_ontology`, `inputs.target_version`
- `inputs.input_type` is added by Stage 1 after ingest completes
- `om-pipeline status` reports current stage and progress
- `om-pipeline rerun --stage N` jumps to a specific stage

### What stage tools depend on

Every stage tool calls `load_context()` to get a `PipelineContext`.
This requires `target_ontology` and `target_version` in the state —
a `ValueError` is raised if missing.

---

## Development Rules

In addition to the hard rules in `AGENTS.md`:

- **State file is the source of truth.** Stage tools read inputs from
  `.mapper-state.json`, not from CLI args (except `--run-dir`).
- **PipelineContext for all derived names.** Do not construct namespace URIs,
  file prefixes, or package names with f-strings — use `PipelineContext`.
- **Stage boundaries are strict.** A stage tool reads the previous stage's
  output and writes its own. Do not skip stages or combine them.
- **build_mapping_matrix.py is a pure transformer.** It reshapes the
  alignment report into mapping matrix schema. No reasoning — actions,
  property-level decisions, and scaffolding are already determined by
  `resolve_alignment()` at Stage 3.

---

## Anti-Patterns

- **Hardcoding run paths**: Use `resolve_run_dir(cli_arg=...)`, never
  construct paths to `.mapper-runs/` manually.
- **Reading global state**: There is no global state file. Every run has
  its own `.mapper-state.json`.
