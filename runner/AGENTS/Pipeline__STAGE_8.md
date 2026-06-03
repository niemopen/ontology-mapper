# Stage 8: Finalize

**Artifacts** (in `edge-package/`): `governance/version-manifest.json`, `governance/lineage-manifest.json`, `governance/validation-report.json`, `governance/change-impact.md`, `package-manifest.json` (updated)

```
Action:  om-finalize --run-dir {run_dir}
         -> Writes governance artifacts with pipeline timing data
         -> Sets finalizedAt and actionCounts in package-manifest.json

Action:  om-pipeline mark-complete --stage 8 --run-dir {run_dir}
         -> Records Stage 8 completion time in pipeline state

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 8

Report final package status to user.
```

## Governance Artifacts

| Artifact | Contents |
|----------|----------|
| `governance/version-manifest.json` | Version, target ontology, mapper version, generation history with `mappingStats` (`{action: count}`), pipeline timing (per-stage durations + total) |
| `governance/lineage-manifest.json` | Per-artifact provenance: source inputs, target references, mapping entries, dependencies |
| `governance/validation-report.json` | Copy of Stage 7 validation results (travels with the package) |
| `governance/change-impact.md` | Extension risk table, validation failures, audit warnings, target version upgrade guidance |
| `package-manifest.json` | Updated with `finalizedAt`, `version`, `stats.actionCounts` |

## Stage Timing

`run_pipeline.py` marks each stage complete via `om-pipeline mark-complete --stage N` after verification passes. This records `started_at` and `completed_at` in `.mapper-state.json`. Stage 8 reads these timings and includes them in `version-manifest.json`.

For stages with automated handlers (1, 5), timing is recorded automatically. For other stages (2-4, 6-8), `run_pipeline.py` calls `mark-complete` explicitly.
