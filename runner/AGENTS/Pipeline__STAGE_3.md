# Stage 3: Semantic Alignment

**Artifacts**: `source-concepts.json`, `search-results/types/*.json`, `search-results/properties/*.json`, `entropy-summary.json`, `alignment-report.json`
**Reference**: [Semantic Search Protocol](Pipeline__SEMANTIC_SEARCH.md) — element-first search, property-path concepts, type patterns, action selection

```
Action:  om-build-strategy --run-dir {run_dir}
         -> Produces source-concepts.json and loads the target reference catalog
         -> Prints paths to reference data files

Action:  om-batch-search --run-dir {run_dir}
         -> Queries vector index for all source types and properties in batch
         -> Writes one file per source type to {run_dir}/search-results/types/
         -> Writes one file per source property to {run_dir}/search-results/properties/
         -> Candidates filtered: top 25, then drop below 75% of rank 1's score
         -> On re-run, preserves files with status == "evaluated"

Action:  om-entropy --run-dir {run_dir}
         -> Computes pre-rotation entropy from batch search candidate counts
         -> Per-concept and per-property: entropy = log₂(candidate count)
         -> Writes {run_dir}/entropy-summary.json
         -> Flags high-entropy concepts (≥ 16 candidates)

Action:  om-orchestrate-eval --run-dir {run_dir}
         -> Evaluates all pending type and property files via bounded concurrent LLM calls
         -> Each file gets a separate claude -p invocation with full candidate context
         -> Resumable: skips files with status == "evaluated"
         -> Use --dry-run to preview without writing
         -> Use --concurrency N to control parallelism (default: 24)

Action:  om-collect-alignments --run-dir {run_dir}
         -> Reads type and property files, reassembles per-concept evaluations
         -> Calls resolve_alignment() on each to add actions and scaffolding
         -> Writes completed alignment-report.json (matchingMethod: "semantic")
         -> Fails if any files are still pending (use --allow-pending to skip)

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 3

Action:  om-pipeline mark-complete --stage 3 --run-dir {run_dir}
```
