# Stage 7: Validate

## What the report speaks for

The report records `validatedArtifacts`: a SHA-256 per package file Stage 7
validated — every file except the five Stage 8 writes itself
(`governance/version-manifest.json`, `governance/lineage-manifest.json`,
`governance/validation-report.json`, `governance/change-impact.md` and the
root `package-manifest.json`). `governance/` is not Stage 8's alone: Stage 6b
writes the decision log, generation audit, quality-gate report and coherence
manifest there, and Check 5 reads the first of them.

Stage 8 compares those digests before publishing
(`validate_edge_package.stale_against_package`) and refuses a report that
does not cover the package — regenerating after validation, or
`--from-stage 8`, which never runs Stage 7 at all. The comparison is by
content, not timestamp: a package is rewritten in less than a filesystem
timestamp tick, so a report written straight afterwards looks newer than
every file it should have refused. A report from before digests were
recorded falls back to the clock, which under-reports rather than refusing
a package it cannot speak to.

**Artifacts**: `validation-report.json`, `feedback-report.json`

```
Action:  om-validate --run-dir {run_dir}
         -> Runs 12 cross-artifact validation checks, writes validation-report.json

Action:  python runner_tools/feedback_report.py --run-dir {run_dir}
         -> Maps validation failures back to source decisions
         -> Writes feedback-report.json

Read:    {run_dir}/validation-report.json
LLM:     If any checks failed, diagnose root cause and report to user.

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 7

Action:  om-pipeline mark-complete --stage 7 --run-dir {run_dir}
```

`om-validate` exits nonzero when any check fails, after writing
`validation-report.json`. Both orchestrators (`run_pipeline.run_stage_7` and
the web backend's stage runner) still run `feedback_report.py` so the failures
are mapped back to source decisions, then stop the stage: verification's
`validation_all_pass` check fails, Stage 7 is not marked complete, and Stage 8
is never reached. Both orchestrators delete a previous run's
`validation-report.json` and `feedback-report.json` before validating, so a
nonzero exit with no report is a validator crash, not a failed validation: the
error is raised as it was and no feedback report is produced.

## Validation Checks

| # | Check | What it catches |
|---|-------|-----------------|
| 1 | Turtle syntax | rdflib parse failures in any .ttl file |
| 2 | SHACL conformance | Shapes vs instances (requires pyshacl) |
| 3 | Mapping completeness | Source concepts missing from the packaged matrix |
| 4 | Extension catalog count | Catalog entries vs extend+augment action count |
| 5 | Decision log count | Decision entries vs mapped concept count |
| 6 | Cypher validity | Empty or comment-only .cypher files |
| 7 | SPARQL syntax | rdflib SPARQL parser on non-parameterized .rq files |
| 8 | Schema-to-ontology | Cypher constraint/index labels vs active class labels |
| 9 | Seed data consistency | MATCH labels reference CREATEd labels in seed.cypher |
| 10 | Transform-to-matrix | internal-to-edge.json source types vs mapping matrix |
| 11 | CMF consistency (when present; required for NIEM) | See [mapper validation contract](../../mapper/AGENTS/OM__VALIDATION.md) |
| 12 | Codebook drift | `targetDefinitionHash` vs current catalog definitions — types/properties changed or removed |
