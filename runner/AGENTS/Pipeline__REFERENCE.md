# Pipeline Reference

Quick reference, common pitfalls, tool inventory, and state management.

---

## Quick Reference: Full Pipeline Command Sequence

```bash
# Pre-flight
python runner_tools/preflight_specs.py --target-ontology {ontology} --target-version {version}
om-pipeline status

# Init (if no run exists)
om-pipeline --organization {org} --source {source} --input-package-path {path} --target-ontology {ontology} --target-version {version}

# Stage 1 (automated)
om-pipeline rerun --stage 1 --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 1

# Stage 2 (check input_type first)
om-extract --run-dir {run_dir} --package {package_path}              # OWL path
# om-ingest-csv "sources/{source}/input/INPUT.csv" --namespace {ns} --namespace-uri {uri}  # CSV path
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 2
om-pipeline mark-complete --stage 2 --run-dir {run_dir}

# Stage 3 (semantic alignment — see Pipeline__STAGE_3.md)
om-build-strategy --run-dir {run_dir}
om-batch-search --run-dir {run_dir}
om-entropy --run-dir {run_dir}               # pre-rotation entropy measurement from search results
om-orchestrate-eval --run-dir {run_dir}      # bounded concurrent LLM evaluation of search results
om-collect-alignments --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 3
om-pipeline mark-complete --stage 3 --run-dir {run_dir}

# Stage 4
om-build-matrix --run-dir {run_dir}
om-generation-audit --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 4
om-pipeline mark-complete --stage 4 --run-dir {run_dir}

# Stage 5 (interactive human review — use _present_and_apply_human_review.py API)
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 5
om-residual-entropy --run-dir {run_dir}
om-pipeline mark-complete --stage 5 --run-dir {run_dir}

# Stage 6 (bootstrap edge-package dirs, then generate)
om-pipeline rerun --stage 6 --run-dir {run_dir}
om-generate-ontology --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 6a
om-package-artifacts --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 6b
om-generate-kg --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 6c
om-pipeline mark-complete --stage 6 --run-dir {run_dir}

# Stage 7
om-validate --run-dir {run_dir}
python runner_tools/feedback_report.py --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 7
om-pipeline mark-complete --stage 7 --run-dir {run_dir}

# Stage 8
om-finalize --run-dir {run_dir}
om-pipeline mark-complete --stage 8 --run-dir {run_dir}
python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 8
```

---

## Resolving `{run_dir}`

All stage commands use `{run_dir}` as a placeholder. Multiple pipeline
runs may run concurrently, so `--run-dir` must be passed to every command.

```bash
# Use absolute path, NOT $(pwd) — command substitution triggers permission prompts
export OM_RUNS_DIR=C:/path/to/OntologyMapper/runner/.mapper-runs

# For a new run: om-pipeline prints the run directory on creation
om-pipeline --organization {org} --source {src} ...

# For resuming: find the most recent run by folder timestamp
run_dir=$(ls -d .mapper-runs/*/ | sort | tail -1 | sed 's:/$::')

# Or target a specific org's most recent run:
run_dir=$(ls -d .mapper-runs/{org}_*/ | sort | tail -1 | sed 's:/$::')

# Verify you have the right one:
om-pipeline status --run-dir $run_dir
```

Every command requires an explicit run directory. `run_pipeline.py` handles
this automatically; for manual invocations, store `run_dir` in a shell variable.

---

## Common Pitfalls

1. **Don't forget Stage 8.** The pipeline doesn't end at validation — finalization is required.
2. **Stage 5 is interactive.** The `run_pipeline.py` loop handles review interpretation via `claude -p`. For manual runs, use `_present_and_apply_human_review.py` CLI subcommands.
3. **Run generation audit between Stage 4 and Stage 6.** It catches data loss early.
4. **Run feedback report after Stage 7.** It closes the loop for subsequent runs.
5. **NEVER copy reference data into pipeline outputs.** Reference data is for measuring accuracy, not producing outputs.
6. **Pipeline tools are an installed package.** Invoked via `om-{command}` CLI entry points — every command is listed in the tool inventory below.
7. **Run verify_stage_outputs.py after every stage.** `run_pipeline.py` does this automatically; for manual runs, run it explicitly.
8. **Use Windows paths for `--run-dir`.** Pass `C:/dev/...` or relative paths, not Git Bash `/c/dev/...` paths.

---

## Tool Inventory

**Pipeline tools** (in `runner_tools/`):

| Tool | Purpose | Used at stage |
|------|---------|---------------|
| `verify_stage_outputs.py` | Post-stage artifact verification | All stages |
| `_present_and_apply_human_review.py` | Human review gate API (load, present, apply, save) | 5 |
| `feedback_report.py` | Map validation failures to source decisions | 7 |
| `run_feedback.py` | Log observations with `--target pipeline\|orchestrator` | Any |
| `run_pipeline.py` | Automated runner — full pipeline with interactive Stage 5 loop | All |
| `preflight_specs.py` | Inspect target ontology reference data | Pre-flight |
| `om-generate-catalog` | Generate NIEM reference catalog from API + GitHub CSVs | Pre-flight |
| `om-generate-owl-catalog` | Generate reference catalog from OWL ontology files | Pre-flight |
| `om-generate-cmf-catalog` | Generate reference catalog from CMF XML + Genericode codelists | Pre-flight |
| `om-build-vector-index` | Build/rebuild FAISS vector indexes from any reference catalog | Pre-flight |
| `om-batch-search` | Batch vector search: writes type + property files to search-results/ | 3 |
| `om-entropy` | Pre-rotation entropy measurement: writes entropy-summary.json | 3 |
| `om-orchestrate-eval` | Concurrent bounded per-file evaluation via claude -p | 3 |
| `om-collect-alignments` | Reassemble evaluations, resolve actions, assemble alignment report | 3 |
| `om-vector-search` | Cross-ontology semantic similarity search | 3 |
| `om-residual-entropy` | Residual entropy after Stage 5: joins entropy with confidence signals | 5 |
| `om-detect-staleness` | Compare `targetDefinitionHash` between two alignment reports | Ad hoc |
| `om-catalog-search` | Catalog lookup by substring for Stage 5 review | 5 |
| `om-edge-overlap` | Detect overlapping extensions across edge packages | Ad hoc |

---

## State Management

- Pipeline state lives in `.mapper-runs/{run_id}/.mapper-state.json` (per-run)
- Running `om-pipeline` with no subcommand always creates a new run directory
- Use `om-pipeline rerun` (with optional `--run-dir` or `--organization`) to resume an existing run
- Run artifacts live in `.mapper-runs/{run_id}/`
- Edge package lives at `.mapper-runs/{run_id}/edge-package/`
- All `om-*` tools require `--run-dir` or `--organization` — no auto-detection
- With `--organization`, the most recent run for that org is selected
- No interactive prompts — all inputs are CLI flags

### Argument styles

**All tools use `--run-dir` as a named flag.** No positional arguments for run directories anywhere.

| Tool | Flags | Example |
| ---- | ----- | ------- |
| `om-pipeline` (init) | `--organization`, `--source`, `--input-package-path` | `om-pipeline --organization redvale --source dbpi --input-package-path PATH` |
| `om-pipeline rerun` | `--run-dir`, `--organization`, `--stage` | `om-pipeline rerun --run-dir .mapper-runs/x` |
| `om-ingest-csv` | `csv_file` (positional), `--run-dir`, `--namespace`, `--namespace-uri` | `om-ingest-csv input.csv --namespace court --namespace-uri urn:court` |
| `om-extract` | `--run-dir`, `--package` | `om-extract --run-dir .mapper-runs/x --package sources/org/domain/` |
| `om-validate-input` | `--package` (required) | `om-validate-input --package sources/org/domain/` |
| `om-build-manifest` | `--package` | `om-build-manifest --package sources/org/domain/` |
| `om-build-strategy` | `--run-dir`, `--catalog` | `om-build-strategy --run-dir .mapper-runs/x` |
| `om-batch-search` | `--run-dir`, `--top-k`, `--min-score-ratio` | `om-batch-search --run-dir .mapper-runs/x` |
| `om-entropy` | `--run-dir` | `om-entropy --run-dir .mapper-runs/x` |
| `om-orchestrate-eval` | `--run-dir`, `--concurrency`, `--model`, `--max-retries`, `--dry-run` | `om-orchestrate-eval --run-dir .mapper-runs/x` |
| `om-collect-alignments` | `--run-dir`, `--allow-pending` | `om-collect-alignments --run-dir .mapper-runs/x` |
| `om-build-matrix` | `--run-dir` | `om-build-matrix --run-dir .mapper-runs/x` |
| `om-generation-audit` | `--run-dir` | `om-generation-audit --run-dir .mapper-runs/x` |
| `om-generate-ontology` | `--run-dir`, `--package-dir` | `om-generate-ontology --run-dir .mapper-runs/x` |
| `om-package-artifacts` | `--run-dir`, `--package-dir` | `om-package-artifacts --run-dir .mapper-runs/x` |
| `om-generate-kg` | `--run-dir`, `--package-dir` | `om-generate-kg --run-dir .mapper-runs/x` |
| `om-validate` | `--run-dir`, `--package-dir` | `om-validate --run-dir .mapper-runs/x` |
| `om-finalize` | `--run-dir`, `--package-dir` | `om-finalize --run-dir .mapper-runs/x` |
| `verify_stage_outputs.py` | `--run-dir`, `--stage` | `python runner_tools/verify_stage_outputs.py --run-dir .mapper-runs/x --stage 3` |
| `_present_and_apply_human_review.py` | `--run-dir` | `python runner_tools/_present_and_apply_human_review.py --run-dir .mapper-runs/x` |
| `feedback_report.py` | `--run-dir` | `python runner_tools/feedback_report.py --run-dir .mapper-runs/x` |

| `run_feedback.py` | `log`/`show`, `--run-dir`, `--stage`, `--type`, etc. | `python runner_tools/run_feedback.py log --run-dir .mapper-runs/x --stage 3 --type bug --component "..." --description "..." --target pipeline` |
| `run_pipeline.py` | `--organization`, `--source`, `--input-package-path`, `--target-ontology`, `--target-version`, `--run-dir`, `--from-stage` | `python runner_tools/run_pipeline.py --organization redvale --source dbpi --input-package-path sources/redvale_dbpi_agency_package` |
| `preflight_specs.py` | `--target-ontology`, `--target-version` | `python runner_tools/preflight_specs.py --target-ontology niem --target-version 6.0` |
| `om-generate-catalog` | `--version`, `--no-github-csv` | `om-generate-catalog --version 6.0` |
| `om-generate-owl-catalog` | `--input`, `--name`, `--version`, `--force` | `om-generate-owl-catalog --input LMSS.owl --name sali-folio --version 2.0` |
| `om-generate-cmf-catalog` | `--input`, `--codelists`, `--name`, `--version`, `--force` | `om-generate-cmf-catalog --input nods.cmf --name nods --version 1.0` |
| `om-build-vector-index` | `--adapter`, `--ontology`, `--version`, `--run-dir`, `--rebuild`, `--delete`, `--list` | `om-build-vector-index --adapter catalog --ontology niem --version 6.0` |
| `om-vector-search` | `--source`, `--target`, `--top-k` | `om-vector-search --source redvale-dbpi --target niem-6.0 --top-k 20` |
| `om-residual-entropy` | `--run-dir` | `om-residual-entropy --run-dir .mapper-runs/x` |
| `om-detect-staleness` | `--old`, `--new` | `om-detect-staleness --old old-report.json --new new-report.json` |
| `om-catalog-search` | `query` (positional), `--catalog`, `--kind`, `--namespace`, `--max-results`, `--json` | `om-catalog-search Person --catalog catalog.json --kind type` |
| `om-edge-overlap` | `package_dirs` (positional, multiple) | `om-edge-overlap pkg1/ pkg2/` |

**Path format**: Use Windows paths (`C:\dev\...` or `C:/dev/...`), not Git Bash paths (`/c/dev/...`).
