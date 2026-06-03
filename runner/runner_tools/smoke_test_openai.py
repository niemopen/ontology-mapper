"""Smoke test: compare an OpenAI model against the existing Sonnet baseline.

Samples N evaluated search-result files from a run directory, calls the
chosen OpenAI model on each (default: gpt-5.4-mini), and writes a side-by-side
markdown report comparing the new outputs against the existing 'evaluation'
field already on disk (the prior Sonnet run).

Usage:
    export OPENAI_API_KEY=sk-...
    python runner_tools/smoke_test_openai.py \\
        --run-dir .mapper-runs/redvale/20260413-234605 \\
        --sample-size 15 \\
        --output smoke-tests/redvale-niem6.md

Reports default to smoke-tests/{run-name}.md unless --output overrides.

The smoke test deliberately does not measure "correctness" — there is no
ground truth for ontology mapping. It surfaces:
  - Schema adherence on the new vendor
  - Whether picks are broadly aligned with Sonnet
  - Rationale coherence and tone
  - Failure modes (refusals, schema breaks, off-list picks)
"""

import argparse
import random
import sys
from pathlib import Path

from orchestrator_service.evaluator import EvaluationError
from orchestrator_service.evaluator_openai import evaluate_file_openai
from orchestrator_service.runner import collect_pending_files, load_context, read_file


def stratified_sample(
    files: list[Path], sample_size: int, seed: int, offset: int = 0
) -> list[Path]:
    """Pick a sample biased ~2/3 types, ~1/3 properties.

    Types and properties stress different parts of the prompt structure
    (parent-type context, range vs inheritance), so include both.

    With ``offset > 0``, skip the first ``offset`` items from the same
    deterministic shuffle (allocated proportionally between types and
    properties). Lets later runs draw concepts disjoint from earlier ones
    while keeping the same seed.
    """
    rng = random.Random(seed)
    types = [f for f in files if "/types/" in f.as_posix() or "\\types\\" in str(f)]
    properties = [
        f for f in files
        if "/properties/" in f.as_posix() or "\\properties\\" in str(f)
    ]

    n_types = (sample_size * 2) // 3
    n_props = sample_size - n_types
    off_types = (offset * 2) // 3
    off_props = offset - off_types

    rng.shuffle(types)
    rng.shuffle(properties)

    take_types = types[off_types : off_types + n_types]
    take_props = properties[off_props : off_props + n_props]
    return take_types + take_props


def _target_field(kind: str) -> str:
    return "targetType" if kind == "type" else "targetProperty"


def _format_evaluation(eval_dict: dict, kind: str) -> str:
    target_field = _target_field(kind)
    target = eval_dict.get(target_field)
    target_str = "null" if target is None else f"`{target}`"
    target_path = eval_dict.get("targetPath") or "—"
    rationale = (eval_dict.get("rationale") or "").strip()
    return (
        f"- **{target_field}**: {target_str}\n"
        f"- **targetPath**: `{target_path}`\n"
        f"- **rationale**: {rationale}\n"
    )


def _diff_line(sonnet_eval: dict, new_eval: dict, kind: str) -> str:
    target_field = _target_field(kind)
    s = sonnet_eval.get(target_field)
    n = new_eval.get(target_field)
    if s == n:
        return f"**Diff**: SAME ({target_field})"
    return (
        f"**Diff**: DIFFERENT — Sonnet picked `{s}`, "
        f"new model picked `{n}`"
    )


def _short_target(eval_dict: dict, kind: str) -> str:
    target = eval_dict.get(_target_field(kind))
    if target is None:
        return "null"
    return f"`{target}`"


def _build_summary_table(rows: list[dict], new_model: str) -> str:
    header = f"| Concept | Sonnet | {new_model} |\n"
    sep = "|---|---|---|\n"
    body = "\n".join(
        f"| `{r['concept']}` ({r['kind']}) | {r['sonnet']} | {r['new']} |"
        for r in rows
    )
    return header + sep + body + "\n"


def _format_block(
    source_id: str,
    kind: str,
    candidate_count: int,
    sonnet_eval: dict,
    new_eval: dict | None,
    new_model: str,
    error: str | None,
) -> str:
    sonnet_by = sonnet_eval.get("evaluatedBy", "?")
    sonnet_block = _format_evaluation(sonnet_eval, kind)
    if error is not None:
        new_block = f"```\nFAILED: {error}\n```\n"
        diff = "**Diff**: N/A — new model failed"
    else:
        new_block = _format_evaluation(new_eval, kind)
        diff = _diff_line(sonnet_eval, new_eval, kind)
    return (
        f"## {source_id}  (kind={kind}, candidateCount={candidate_count})\n\n"
        f"### Sonnet baseline (`evaluatedBy: {sonnet_by}`)\n"
        f"{sonnet_block}\n"
        f"### {new_model}\n"
        f"{new_block}\n"
        f"{diff}\n"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Smoke test an OpenAI model against existing Sonnet baseline"
    )
    parser.add_argument("--run-dir", required=True, type=Path,
                        help="Pipeline run directory with evaluated search-results")
    parser.add_argument("--sample-size", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--offset", type=int, default=0,
                        help="Skip first N items from the same deterministic "
                             "shuffle; use to draw a sample disjoint from a "
                             "prior run with the same seed")
    parser.add_argument("--output", type=Path, default=None,
                        help="Report path. Defaults to "
                             "smoke-tests/{run-dir-name}.md")
    parser.add_argument("--model", default="gpt-5.4-mini",
                        help="OpenAI model id (default: gpt-5.4-mini)")
    parser.add_argument("--reasoning-effort", default="low",
                        choices=["minimal", "low", "medium", "high"],
                        help="Reasoning effort for gpt-5 family (default: low)")
    args = parser.parse_args()

    if not args.run_dir.is_dir():
        print(f"Error: run directory not found: {args.run_dir}", file=sys.stderr)
        sys.exit(1)

    if args.output is None:
        smoke_tests_dir = Path("smoke-tests")
        smoke_tests_dir.mkdir(exist_ok=True)
        args.output = smoke_tests_dir / f"{args.run_dir.name}.md"

    context = load_context(args.run_dir)
    all_files = collect_pending_files(args.run_dir)

    eligible = []
    for f in all_files:
        try:
            doc = read_file(f)
        except Exception:
            continue
        if doc.get("status") == "evaluated" and doc.get("evaluation"):
            eligible.append(f)
    if not eligible:
        print(
            "Error: no evaluated files with existing evaluation found in run",
            file=sys.stderr,
        )
        sys.exit(1)

    sample = stratified_sample(
        eligible, args.sample_size, args.seed, args.offset
    )

    print(f"Smoke test: {args.model}")
    print(f"  Run-dir:     {args.run_dir}")
    print(f"  Sample size: {len(sample)} of {len(eligible)} eligible")
    print(f"  Reasoning:   {args.reasoning_effort}")
    print(f"  Seed:        {args.seed}")
    print(f"  Output:      {args.output}")
    print()

    blocks = []
    summary_rows = []
    same_count = 0
    diff_count = 0
    failed_count = 0

    for i, path in enumerate(sample, 1):
        doc = read_file(path)
        kind = doc.get("kind", "?")
        source_id = doc.get("source", {}).get("qname", path.stem)
        existing = doc.get("evaluation", {})
        candidate_count = len(doc.get("candidates", []))

        print(f"  [{i:>2}/{len(sample)}] {kind:<8} {source_id}", flush=True)

        new_eval = None
        error = None
        try:
            new_eval = evaluate_file_openai(
                doc, context,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
            )
        except EvaluationError as e:
            error = str(e)

        if error is not None:
            failed_count += 1
            new_cell = "FAILED"
        elif existing.get(_target_field(kind)) == new_eval.get(_target_field(kind)):
            same_count += 1
            new_cell = _short_target(new_eval, kind)
        else:
            diff_count += 1
            new_cell = _short_target(new_eval, kind)

        summary_rows.append({
            "concept": source_id,
            "kind": kind,
            "sonnet": _short_target(existing, kind),
            "new": new_cell,
        })

        blocks.append(_format_block(
            source_id, kind, candidate_count,
            existing, new_eval, args.model, error,
        ))

    summary = (
        f"# Smoke Test: {args.model} vs Sonnet baseline\n\n"
        f"- Run-dir: `{args.run_dir}`\n"
        f"- Sample size: {len(sample)}\n"
        f"- Same target: {same_count}\n"
        f"- Different target: {diff_count}\n"
        f"- Failed: {failed_count}\n"
        f"- Reasoning effort: `{args.reasoning_effort}`\n"
        f"- Seed: {args.seed}\n\n"
        f"## Summary\n\n"
    )

    table = _build_summary_table(summary_rows, args.model)

    args.output.write_text(
        summary + table + "\n---\n\n## Detail\n\n" + "\n".join(blocks),
        encoding="utf-8",
    )
    print()
    print(f"Report written to {args.output}")
    print(f"  Same target:    {same_count}")
    print(f"  Different:      {diff_count}")
    print(f"  Failed:         {failed_count}")


if __name__ == "__main__":
    main()
