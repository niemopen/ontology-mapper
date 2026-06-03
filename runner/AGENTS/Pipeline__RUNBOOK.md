# Pipeline Runbook

> **Repo**: OntologyMapper | **Version**: 5.0 | **Updated**: 2026-04-09

---

## Purpose

This runbook documents the commands `run_pipeline.py` executes at each stage, in what order, and with what arguments. It serves as reference for developers maintaining the pipeline runner, and as a manual fallback for running individual stages.

**Key principle**: The pipeline is driven by `run_pipeline.py`, not by an LLM. LLM calls happen only at two points: Stage 3 (bounded concurrent evaluation via `om-orchestrate-eval`) and Stage 5 (natural-language review interpretation via `claude -p`). Both use `claude -p` as a service call, not as an orchestrator.

**Repo structure**: Pipeline tools are installed as the `ontology-mapper` package (CLI commands prefixed `om-`). Pipeline support tools live in `runner_tools/` in this repo. Run artifacts are local to this repo.

---

## Environment Setup

Run these commands **once at session start**, then invoke `om-*` commands directly for the rest of the session.

1. **Working directory**: All commands run from the `OntologyMapper/runner/` directory
2. **Python environment**: Activated with `rdflib`, `lxml`, and other dependencies
3. **Pipeline tools**: `ontology-mapper` package installed with all extras (`pip install -e "../mapper[validation,vector]"`)
4. **Runs directory**: `OM_RUNS_DIR` set so pipeline tools find run artifacts in this repo
5. **Target ontology**: Must be specified via `--target-ontology` / `--target-version` (e.g., `niem` / `6.0`)

```bash
cd C:/path/to/OntologyMapper/runner
export OM_RUNS_DIR=C:/path/to/OntologyMapper/runner/.mapper-runs

# Verify (once):
om-pipeline help
python -c "import rdflib; print(rdflib.__version__)"
python -c "import faiss; print('FAISS OK')"
```

---

## Running the Pipeline

```bash
# Full pipeline run (Stages 1-8, interactive at Stage 5):
python runner_tools/run_pipeline.py \
    --organization redvale --source dbpi \
    --input-package-path sources/redvale_dbpi_agency_package \
    --target-ontology niem --target-version 6.0

# Resume after failure at a later stage:
python runner_tools/run_pipeline.py \
    --run-dir .mapper-runs/redvale_20260409-120000 --from-stage 6
```

The runner handles preflight checks, command sequencing, verification, and
`mark-complete` calls. It prints a summary table with per-stage timing and
metrics at the end.

---

## Stage-by-Stage Command Reference

Each stage's full protocol lives in its own file.

| Stage | File | Summary |
|-------|------|---------|
| 1 — Ingest | [Pipeline__STAGE_1.md](Pipeline__STAGE_1.md) | Validate input package, write source-inventory.json |
| 2 — Extract | [Pipeline__STAGE_2.md](Pipeline__STAGE_2.md) | Extract concept-inventory.json (OWL or CSV path) |
| 3 — Align | [Pipeline__STAGE_3.md](Pipeline__STAGE_3.md) | Vector search, LLM evaluation, resolve actions |
| 4 — Decide | [Pipeline__STAGE_4.md](Pipeline__STAGE_4.md) | Transform alignment into mapping matrix + decision log |
| 5 — Review | [Pipeline__STAGE_5.md](Pipeline__STAGE_5.md) | Interactive human review loop |
| 6 — Generate | [Pipeline__STAGE_6.md](Pipeline__STAGE_6.md) | OWL/TTL (6a), package artifacts (6b), KG artifacts (6c) |
| 7 — Validate | [Pipeline__STAGE_7.md](Pipeline__STAGE_7.md) | Cross-artifact validation + feedback report |
| 8 — Finalize | [Pipeline__STAGE_8.md](Pipeline__STAGE_8.md) | Governance metadata (version, lineage, change-impact, timing) |

---

## Manual Stage Execution

For running individual stages outside the automated runner (e.g., debugging):

1. **Environment first.** Set `OM_RUNS_DIR` before anything else.
2. **Find the run directory.** `ls -d .mapper-runs/*/ | sort`
3. **Run commands.** Use the command sequence from the stage SOP files above.
4. **Verify.** `python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage {N}`
5. **Mark complete.** `om-pipeline mark-complete --stage {N} --run-dir {run_dir}`

---

## Reference

Full command sequence, common pitfalls, tool inventory, and state management:
[Pipeline__REFERENCE.md](Pipeline__REFERENCE.md)
