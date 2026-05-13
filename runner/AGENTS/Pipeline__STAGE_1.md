# Stage 1: Ingest (Automated)

**Handler**: `pipeline.py` — `_handle_ingest()`

```
Action:  om-pipeline rerun --stage 1
         -> Validates input package, scans files, writes source-inventory.json

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 1
```

**Artifacts**: `source-inventory.json`
