"""CLI entry point for the evaluation service.

Enumerates search result files, runs bounded evaluations concurrently
through the provider-agnostic LLM service (codex or claude per
OM_LLM_PROVIDER), validates responses, and writes evaluations back.

Usage:
    om-orchestrate-eval --run-dir {run_dir} \\
        [--concurrency 8] [--provider codex|claude] [--model <id>]
"""

import asyncio
import json
import sys
from pathlib import Path

from orchestrator_service.evaluator import (
    EvaluationContext,
    EvaluationError,
    evaluate_file,
)
from ontology_mapper.llm_service import (
    DEFAULT_MODELS,
    PROVIDER_ENV_VAR,
    _resolve_provider,
    _resolve_model,
)


# ---------------------------------------------------------------------------
# File enumeration
# ---------------------------------------------------------------------------

def collect_pending_files(run_dir: Path) -> list[Path]:
    """Collect all pending search result files (types first, then properties).

    Returns file paths sorted: all types in sorted order, then all
    properties in sorted order.
    """
    search_dir = run_dir / "search-results"
    types_dir = search_dir / "types"
    props_dir = search_dir / "properties"

    files = []
    for d in (types_dir, props_dir):
        if d.is_dir():
            files.extend(sorted(d.glob("*.json")))
    return files


def load_context(run_dir: Path) -> EvaluationContext:
    """Load actions and typePatterns from the alignment report placeholder."""
    report_path = run_dir / "alignment-report.json"
    if not report_path.exists():
        print(f"Error: {report_path} not found. Run om-build-strategy first.",
              file=sys.stderr)
        sys.exit(1)

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error: cannot read {report_path}: {e}", file=sys.stderr)
        sys.exit(1)
    actions = report.get("actions", {})
    type_patterns = report.get("typePatterns", {})

    if not actions:
        print("Warning: no actions found in alignment-report.json",
              file=sys.stderr)

    return EvaluationContext(actions=actions, type_patterns=type_patterns)


# ---------------------------------------------------------------------------
# Single file processing
# ---------------------------------------------------------------------------

def read_file(path: Path) -> dict:
    """Read a search result file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_evaluation(path: Path, doc: dict, evaluation: dict) -> None:
    """Write the evaluation back to the file."""
    # Remove internal correction marker before writing
    corrected = evaluation.pop("_prefix_corrected", False)
    doc["status"] = "evaluated"
    doc["evaluation"] = evaluation
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return corrected


# ---------------------------------------------------------------------------
# Concurrent evaluation loop
# ---------------------------------------------------------------------------

def _progress(counter: dict) -> str:
    """Format a progress prefix from the shared counter."""
    done = counter["evaluated"] + counter["skipped"] + counter["failed"]
    total = counter["total"]
    pct = (done * 100) // total if total else 0
    return f"[{done}/{total} {pct:>3}%]"


async def process_file(
    path: Path,
    context: EvaluationContext,
    provider: str,
    model: str,
    max_retries: int,
    semaphore: asyncio.Semaphore,
    counter: dict,
) -> None:
    """Process a single file with retry logic."""
    async with semaphore:
        try:
            doc = read_file(path)
        except (json.JSONDecodeError, OSError) as e:
            counter["failed"] += 1
            print(f"  {_progress(counter)} FAILED reading {path.name}: {e}",
                  file=sys.stderr)
            return

        if doc.get("status") == "evaluated":
            counter["skipped"] += 1
            return

        source_id = doc.get("source", {}).get("qname", path.stem)
        kind = doc.get("kind", "?")

        attempts = 0
        last_error = None
        while attempts <= max_retries:
            try:
                evaluation = await evaluate_file(
                    doc, context, provider=provider, model=model
                )
                corrected = write_evaluation(path, doc, evaluation)
                counter["evaluated"] += 1
                if corrected:
                    counter["prefix_corrected"] += 1
                print(f"  {_progress(counter)} {kind:<8} {source_id}")
                return
            except EvaluationError as e:
                last_error = e
                attempts += 1
                if attempts <= max_retries:
                    print(f"  RETRY {source_id}: {e}", file=sys.stderr)
            except (KeyError, OSError) as e:
                # Malformed file or disk error — not retryable
                counter["failed"] += 1
                print(f"  {_progress(counter)} FAILED {source_id}: {e}",
                      file=sys.stderr)
                return

        counter["failed"] += 1
        print(f"  {_progress(counter)} FAILED {source_id}: {last_error}",
              file=sys.stderr)


async def run_evaluations(
    run_dir: Path,
    concurrency: int = 24,
    provider: str | None = None,
    model: str | None = None,
    max_retries: int = 1,
    dry_run: bool = False,
) -> dict:
    """Run all evaluations concurrently."""
    context = load_context(run_dir)
    files = collect_pending_files(run_dir)

    if not files:
        print("No search result files found.")
        return {"total": 0, "evaluated": 0, "skipped": 0, "failed": 0}

    eff_provider = _resolve_provider(provider)
    eff_model = _resolve_model(eff_provider, model)

    print(f"\nom-orchestrate-eval")
    print(f"  Run:         {run_dir}")
    print(f"  Files:       {len(files)}")
    print(f"  Concurrency: {concurrency}")
    print(f"  Provider:    {eff_provider}")
    print(f"  Model:       {eff_model}")
    print(f"  Max retries: {max_retries}")

    if dry_run:
        print(f"\n  DRY RUN — listing files without evaluating:\n")
        for f in files:
            doc = read_file(f)
            status = doc.get("status", "?")
            kind = doc.get("kind", "?")
            source_id = doc.get("source", {}).get("qname", f.stem)
            print(f"  {status:<10} {kind:<8} {source_id}")
        return {"total": len(files), "evaluated": 0, "skipped": 0, "failed": 0}

    counter = {
        "total": len(files),
        "evaluated": 0,
        "skipped": 0,
        "failed": 0,
        "prefix_corrected": 0,
    }

    # Persist orchestration config BEFORE fan-out so the UI can read the
    # active provider/model while Stage 3 is still running. Update again at
    # the end to capture the final concurrency/max_retries used (in case a
    # future caller mutates them mid-flight).
    _save_orchestration_config(
        run_dir, eff_provider, eff_model, concurrency, max_retries
    )

    semaphore = asyncio.Semaphore(concurrency)

    print(f"\n  Evaluating...\n")

    tasks = [
        process_file(
            path, context, eff_provider, eff_model, max_retries, semaphore, counter
        )
        for path in files
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Log any unexpected exceptions that escaped process_file
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            counter["failed"] += 1
            print(f"  UNEXPECTED ERROR in task {i}: {result}", file=sys.stderr)

    print(f"\n  Results:")
    print(f"    Evaluated: {counter['evaluated']}")
    print(f"    Skipped:   {counter['skipped']} (already evaluated)")
    print(f"    Failed:    {counter['failed']}")
    if counter["prefix_corrected"] > 0:
        print(f"    Prefix corrections: {counter['prefix_corrected']}")

    # Write orchestration config to pipeline state
    _save_orchestration_config(
        run_dir, eff_provider, eff_model, concurrency, max_retries
    )
    print(f"  Done.")

    return counter


def _save_orchestration_config(
    run_dir: Path,
    provider: str,
    model: str,
    concurrency: int,
    max_retries: int,
) -> None:
    """Write orchestration config to .mapper-state.json."""
    from ontology_mapper.pipeline import PipelineState, state_path_for

    state_path = state_path_for(run_dir)
    if not state_path.exists():
        return
    state = PipelineState.load(state_path)
    state.orchestration_config = {
        "evaluatorProvider": provider,
        "evaluatorModel": model,
        "evaluatorConcurrency": concurrency,
        "maxRetries": max_retries,
    }
    state.save(state_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run bounded per-file semantic evaluation via the provider-agnostic "
            "LLM service (codex / claude per " + PROVIDER_ENV_VAR + ")"
        )
    )
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    parser.add_argument(
        "--concurrency", type=int, default=24,
        help="Number of parallel evaluations (default: 24)",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(DEFAULT_MODELS.keys()),
        default=None,
        help=(
            "LLM provider; defaults to " + PROVIDER_ENV_VAR + " or 'codex'. "
            "Pass 'claude' to opt back to Anthropic."
        ),
    )
    parser.add_argument(
        "--model", default=None,
        help=(
            "Provider-specific model id (default: per-provider; "
            "codex -> gpt-5.5, claude -> sonnet)"
        ),
    )
    parser.add_argument(
        "--max-retries", type=int, default=1,
        help="Retries per file on validation failure (default: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files without evaluating",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"Error: run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    result = asyncio.run(run_evaluations(
        run_dir=run_dir,
        concurrency=args.concurrency,
        provider=args.provider,
        model=args.model,
        max_retries=args.max_retries,
        dry_run=args.dry_run,
    ))

    if result["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
