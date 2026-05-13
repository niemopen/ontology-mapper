# Stage 5: Review (Interactive)

**Artifacts**: Updated `mapping-matrix.json`, `decision-log.json`, `human-review-decisions.json`

## Automated (run_pipeline.py)

`run_pipeline.py` runs Stage 5 as an interactive loop:

1. **Present** pending items grouped by action (reuse/augment/extend)
2. **Read** user natural language input at the `Review>` prompt
3. **Interpret** via `claude -p --json-schema` — maps input to a structured action
4. **Dispatch** the action to the appropriate Python function
5. **Check** if pending items remain — loop back to step 2, or continue to Stage 6

Available actions during review:
- `approve` — accept a single concept's recommendation
- `approve_all` — accept all pending (blocked if human-must-decide properties exist)
- `detail` — show full rationale and property mappings for a concept
- `change_target` — change target type, triggering reclassification cascade
- `resolve_property` — resolve a single property (especially human-must-decide)
- `search` — search the target catalog for types or properties

After all items are reviewed:
```
Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 5

Action:  om-residual-entropy --run-dir {run_dir}
         -> Joins pre-rotation entropy with confidence signals from review
         -> Writes residual-entropy.json

Action:  om-pipeline mark-complete --stage 5 --run-dir {run_dir}
```

## Manual (CLI subcommands)

For running Stage 5 outside the automated runner:

```bash
# Present review summary
python runner_tools/_present_and_apply_human_review.py --run-dir {run_dir} present

# Show detail for one concept
python runner_tools/_present_and_apply_human_review.py --run-dir {run_dir} detail {concept}

# Approve a single concept
python runner_tools/_present_and_apply_human_review.py --run-dir {run_dir} approve {concept}

# Approve all (blocked if human-must-decide properties exist)
python runner_tools/_present_and_apply_human_review.py --run-dir {run_dir} approve-all

# Search target catalog
python runner_tools/_present_and_apply_human_review.py --run-dir {run_dir} search {query}
```
