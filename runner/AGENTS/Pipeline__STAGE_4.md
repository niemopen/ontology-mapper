# Stage 4: Build Mapping Matrix

Reshapes the alignment report (from Stage 3) into the mapping matrix schema
consumed by downstream stages. Pure formatter — no reasoning. All actions,
property-level decisions, and structural scaffolding were already determined
by `resolve_alignment()` at Stage 3.

**Artifacts**: `mapping-matrix.json`, `decision-log.json`

```
Action:  om-build-matrix --run-dir {run_dir}
         -> Reads alignment-report.json
         -> Carries forward: action, actionRationale, property mappings,
            scaffolding (extensionType/baseType, augmentationType/augmentsType)
         -> Writes mapping-matrix.json and decision-log.json

Action:  om-generation-audit --run-dir {run_dir}
         -> Writes generation-audit.json

Read:    {run_dir}/mapping-matrix.json -> summary
         -> Confirm: action counts sum to totalConcepts
         -> Confirm: propertyStats.total > 0 for non-trivial domains
         -> Confirm: propertyMappings carry through from alignment report

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 4

Action:  om-pipeline mark-complete --stage 4 --run-dir {run_dir}
```
