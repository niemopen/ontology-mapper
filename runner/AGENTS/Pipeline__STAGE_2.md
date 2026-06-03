# Stage 2: Extract

**Artifacts**: `concept-inventory.json`

```
Read:    {run_dir}/.mapper-state.json -> inputs.input_type

If input_type == "owl":
  Action:  om-extract --run-dir {run_dir} --package {input_package_path}

If input_type == "csv":
  Action:  om-ingest-csv "sources/{source}/input/INPUT.csv" --namespace {namespace_prefix} --namespace-uri {namespace_uri}
           (both --namespace and --namespace-uri are required — derive from package contents)

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 2

Action:  om-pipeline mark-complete --stage 2 --run-dir {run_dir}
```
