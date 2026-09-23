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

## Exit criteria

Review may close when nothing is pending, no property still needs a human
decision, and every accepted class target passes the target ontology's class
policy (`ontology_specific.invalid_class_targets`). The third applies to
decisions saved before the policy existed: they make no selection for the
interactive check to catch, so the exit check and the Stage 6 entry are the
seams that see them. `check_stage_5_exit(matrix, cascade)` takes the run's
`(target_ontology, catalog)`; when that cannot be loaded the targets cannot
be proven valid and that is itself a blocker.

Each driver meets that check at a different point. The web asks it through
`routes/review.stage_5_gate` before it offers to close review; the CLI loop
(`run_stage_5_loop`) keeps prompting until the same check passes, so a
blocker on an entry that is not pending still gets a `Review>` prompt; and
`complete_stage_5` — the step that marks the stage complete for both — runs
the check itself and returns the blockers instead of completing. The
blocker names every field holding the rejected class, because the reviewer
selects a class and stored `baseType`/`augmentsType` is not one:
re-accepting the same class rebuilds scaffolding the policy rejects, so the
message names something the reviewer can act on. A blocked entry is
accepted rather than pending, so the CLI resolves a named concept over
every mapping, not the pending list alone; otherwise the repair the
blocker asks for could not be typed. The Stage 6 entry answers the
same way: an unreadable catalog or matrix shape fails the stage
(`StageError`), never escaping as a traceback the driver does not present.
