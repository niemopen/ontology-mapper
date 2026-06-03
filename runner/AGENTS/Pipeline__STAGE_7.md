# Stage 7: Validate

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
| 11 | CMF consistency (NIEM) | CMF XML parses, class count matches matrix, augmentation records present |
| 12 | Codebook drift | `targetDefinitionHash` vs current catalog definitions — types/properties changed or removed |
