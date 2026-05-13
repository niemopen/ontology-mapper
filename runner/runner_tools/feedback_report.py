"""Feedback report — map validation failures back to source decisions.

Runs after Stage 7 validation. Reads the validation report and maps each
failure back to the mapping matrix entry that caused it, producing a
feedback-report.json that the operator can review.

This closes the feedback loop without auto-correcting: decisions that led
to downstream problems are flagged so the operator can adjust them.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

FEEDBACK_FILENAME = "feedback-report.json"


def load_inputs(run_dir_arg):
    """Load validation report, mapping matrix, and generation audit."""
    run_dir = Path(run_dir_arg)

    val_path = run_dir / "validation-report.json"
    validation = json.loads(val_path.read_text(encoding="utf-8")) if val_path.exists() else None

    matrix = json.loads((run_dir / "mapping-matrix.json").read_text(encoding="utf-8"))

    audit_path = run_dir / "generation-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None

    return run_dir, validation, matrix, audit


def build_feedback(validation, matrix, audit):
    """Build feedback entries linking downstream problems to upstream decisions.

    Args:
        validation: Validation report dict (from Stage 6), or None.
        matrix: Mapping matrix dict.
        audit: Generation audit dict (from post-Stage 4), or None.

    Returns:
        List of feedback dicts:
        [{concept, decision, downstream_issue, severity, recommendation}]
    """
    feedback = []
    decision_by_concept = {m["sourceConcept"]: m for m in matrix.get("mappings", [])}

    # --- From validation failures ---
    if validation and not validation.get("allPassed", True):
        for check in validation.get("checks", []):
            if check["status"] != "FAIL":
                continue

            check_name = check["check"]
            details = check.get("details", "")

            if check_name == "shacl-conformance":
                for concept, decision in decision_by_concept.items():
                    local = concept.split(":")[-1] if ":" in concept else concept
                    type_name = local + "Type"
                    if type_name in details or local in details:
                        feedback.append({
                            "concept": concept,
                            "decision": {
                                "action": decision["action"],
                                "targetType": decision.get("targetType"),
                            },
                            "downstream_issue": {
                                "stage": "7-validation",
                                "check": check_name,
                                "detail": f"SHACL validation failed — {type_name} may have constraint violations",
                            },
                            "severity": "warning",
                            "recommendation": (
                                f"Review the SHACL shape for {type_name}. "
                                f"The {decision['action']} decision may need adjustment "
                                f"if property constraints are incompatible with the target base type."
                            ),
                        })

            elif check_name == "mapping-completeness":
                if "unmapped:" in details:
                    unmapped_str = details.split("unmapped:")[1].strip()
                    feedback.append({
                        "concept": None,
                        "decision": None,
                        "downstream_issue": {
                            "stage": "7-validation",
                            "check": check_name,
                            "detail": f"Unmapped concepts found: {unmapped_str}",
                        },
                        "severity": "warning",
                        "recommendation": (
                            "Some source concepts were not included in the mapping matrix. "
                            "This may indicate a gap in Stage 3 alignment."
                        ),
                    })

            elif check_name in ("extension-catalog-count", "decision-log-count",
                                "cypher-validity", "sparql-syntax",
                                "schema-ontology-consistency", "seed-data-consistency",
                                "transform-matrix-consistency",
                                "cmf-consistency"):
                feedback.append({
                    "concept": None,
                    "decision": None,
                    "downstream_issue": {
                        "stage": "7-validation",
                        "check": check_name,
                        "detail": details,
                    },
                    "severity": "info",
                    "recommendation": f"Check {check_name} failed. Review Stage 6 generation output.",
                })

    # --- From generation audit ---
    if audit:
        for finding in audit.get("findings", []):
            if finding["severity"] != "warning":
                continue

            concept = finding.get("concept")
            related = finding.get("related", {})

            feedback.append({
                "concept": concept,
                "decision": {
                    "action": related.get("action"),
                    "targetType": related.get("targetType"),
                } if related else None,
                "downstream_issue": {
                    "stage": "4-audit",
                    "check": finding["code"],
                    "detail": finding["message"],
                },
                "severity": "warning",
                "recommendation": finding["message"],
            })

    return feedback


def main():
    import argparse, sys, io
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    elif not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="Map validation failures to source decisions")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    args = parser.parse_args()

    run_dir, validation, matrix, audit = load_inputs(args.run_dir)

    feedback = build_feedback(validation, matrix, audit)

    # Save feedback report
    report = {
        "stage": "7-feedback",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "feedbackCount": len(feedback),
        "feedback": feedback,
    }
    out_path = run_dir / FEEDBACK_FILENAME
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # Print summary
    warnings = sum(1 for f in feedback if f["severity"] == "warning")
    infos = sum(1 for f in feedback if f["severity"] == "info")

    if feedback:
        print(f"\n  Feedback report: {len(feedback)} items ({warnings} warnings, {infos} info)")
        for fb in feedback:
            icon = "!" if fb["severity"] == "warning" else "-"
            concept = fb.get("concept") or "(general)"
            issue = fb.get("downstream_issue", {})
            print(f"    [{icon}] {concept}: {issue.get('detail', '')[:100]}")
    else:
        print("\n  Feedback report: no downstream issues detected")

    print(f"  Saved to: {out_path}")


if __name__ == "__main__":
    main()
