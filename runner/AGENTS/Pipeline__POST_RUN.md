# Post-Run Reference

After the pipeline completes, observations logged during the run can be
reviewed and used to file issues manually.

## Observation Logging

During development or debugging, observations can be logged via `run_feedback.py`:

```bash
python runner_tools/run_feedback.py log \
    --run-dir {run_dir} --stage 3 --type bug \
    --component "om-batch-search" \
    --description "..." --target pipeline
```

Types: `bug`, `gap`, `feature-need`, `performance`
Target: `pipeline` (om-* tools) or `orchestrator` (pipeline support tools)

## Viewing Observations

```bash
python runner_tools/run_feedback.py show --run-dir {run_dir}
```

## Observation Schema

Each observation in `run-feedback.json` has:

| Field | Values |
|-------|--------|
| `stage` | "1"–"8" |
| `type` | bug, gap, feature-need, performance |
| `component` | Tool or function name |
| `description` | What happened |
| `impact` | low, medium, high |
| `target` | pipeline, orchestrator |
| `workaround` | How the issue was worked around (optional) |
