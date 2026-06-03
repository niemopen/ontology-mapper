#!/usr/bin/env python3
"""Capture observations during pipeline runs.

Observations (bugs, gaps, feature requests) encountered during a pipeline run
are saved to {run_dir}/run-feedback.json for later review.

Usage (as module):
    from runner_tools.run_feedback import log_observation
    log_observation(run_dir, "3", "bug", "resolve_run_dir()",
                    "Picks wrong directory with multiple runs",
                    workaround="Used explicit path", impact="low",
                    target="pipeline")

Usage (as CLI):
    python runner_tools/run_feedback.py log \\
        --run-dir .mapper-runs/ncsc_20260331-235034 \\
        --stage 3 --type bug --component "resolve_run_dir()" \\
        --description "Picks wrong directory" \\
        --workaround "Used explicit path" --impact low \\
        --target pipeline
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def log_observation(run_dir, stage, obs_type, component, description,
                    workaround=None, impact="low", target="pipeline"):
    """Append an observation to the run feedback log.

    Args:
        run_dir: Path to the pipeline run directory.
        stage: Pipeline stage where the observation occurred (e.g., "3", "5").
        obs_type: One of: bug, gap, feature-need, performance.
        component: The tool or function that exhibited the behavior.
        description: What happened and why it was unexpected.
        workaround: How the issue was worked around (optional).
        impact: low, medium, or high.
        target: Which repo owns this issue — "pipeline" or "orchestrator".
            Apply the litmus test: does this produce/transform a pipeline
            artifact? → pipeline. Does it support running, reviewing,
            or verifying the pipeline? → orchestrator.
    """
    if target not in ("pipeline", "orchestrator"):
        raise ValueError(f"target must be 'pipeline' or 'orchestrator', got '{target}'")

    feedback_path = Path(run_dir) / "run-feedback.json"
    if feedback_path.exists():
        feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
    else:
        feedback = {"observations": []}

    feedback["observations"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": str(stage),
        "type": obs_type,
        "component": component,
        "description": description,
        "workaround": workaround,
        "impact": impact,
        "target": target,
    })
    feedback_path.write_text(json.dumps(feedback, indent=2), encoding="utf-8")


def main():
    import sys, io
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    elif not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="Log pipeline run observations")
    sub = parser.add_subparsers(dest="command")

    log_cmd = sub.add_parser("log", help="Log an observation")
    log_cmd.add_argument("--run-dir", required=True)
    log_cmd.add_argument("--stage", required=True)
    log_cmd.add_argument("--type", required=True, choices=["bug", "gap", "feature-need", "performance"])
    log_cmd.add_argument("--component", required=True)
    log_cmd.add_argument("--description", required=True)
    log_cmd.add_argument("--workaround", default=None)
    log_cmd.add_argument("--impact", default="low", choices=["low", "medium", "high"])
    log_cmd.add_argument("--target", default="pipeline", choices=["pipeline", "orchestrator"],
                         help="Which repo owns this issue (default: pipeline)")

    show_cmd = sub.add_parser("show", help="Show observations for a run")
    show_cmd.add_argument("--run-dir", required=True)

    args = parser.parse_args()

    if args.command == "log":
        log_observation(args.run_dir, args.stage, args.type, args.component,
                        args.description, args.workaround, args.impact,
                        args.target)
        print(f"Observation logged to {args.run_dir}/run-feedback.json")

    elif args.command == "show":
        feedback_path = Path(args.run_dir) / "run-feedback.json"
        if not feedback_path.exists():
            print("No feedback log found.")
            return
        feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
        for obs in feedback.get("observations", []):
            target = obs.get("target", "pipeline")
            print(f"  [{obs['type']}] Stage {obs['stage']}: {obs['component']} (→ {target})")
            print(f"    {obs['description']}")
            if obs.get("workaround"):
                print(f"    Workaround: {obs['workaround']}")
            print()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
