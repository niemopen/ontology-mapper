#!/usr/bin/env python3
"""Stage 4: Build mapping matrix from the alignment report.

Pure schema transformer — reshapes alignment-report.json (produced at
Stage 3, enriched by resolve_alignment) into the mapping matrix and
decision log consumed by downstream stages.

No reasoning happens here. The evaluator and resolve_alignment() have
already determined actions, property-level actions, and structural scaffolding.
This step formats those decisions into the matrix schema.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from ontology_mapper.pipeline_context import load_context


def load_stage_data(ctx):
    """Load alignment report; prefer target ontology/version from alignment if present."""
    alignment = json.loads(
        (ctx.run_dir / "alignment-report.json").read_text(encoding="utf-8")
    )
    # Prefer from alignment report (set during alignment)
    target_ontology = alignment.get("targetOntology", ctx.target_ontology)
    target_version = alignment.get("targetVersion", ctx.target_version)
    return alignment, target_ontology, target_version


def build_mapping_entry(entry):
    """Transform one alignment entry into a mapping matrix entry.

    Carries forward all fields from the resolved alignment, reshaping
    into the mapping matrix schema.
    """
    mapping = {
        "sourceConcept": entry["sourceConcept"],
        "sourceDefinition": entry.get("sourceDefinition", ""),
        "sourcePath": entry.get("sourcePath", ""),
        "action": entry.get("action", "pending"),
        "actionRationale": entry.get("actionRationale", ""),
        "targetType": entry.get("targetType"),
        "targetTypeLabel": entry.get("targetTypeLabel"),
        "targetDefinition": entry.get("targetDefinition", ""),
        "targetPath": entry.get("targetPath", ""),
        "rationale": entry.get("rationale", ""),
        "reviewStatus": "pending-review",
    }

    # Carry forward targetDefinitionHash for staleness detection
    if "targetDefinitionHash" in entry:
        mapping["targetDefinitionHash"] = entry["targetDefinitionHash"]

    # Carry forward structural scaffolding (ontology-specific)
    for key in ("extensionType", "baseType", "augmentationType", "augmentsType"):
        if key in entry:
            mapping[key] = entry[key]

    # Carry forward property mappings from Stage 3
    properties = entry.get("properties", [])
    if properties:
        mapping["propertyMappings"] = _build_property_mappings(properties)

    return mapping


def _build_property_mappings(properties):
    """Transform alignment properties into mapping matrix property entries.

    Properties already have propertyAction and targetProperty from
    resolve_alignment(). This just reshapes the schema.
    """
    mappings = []
    for prop in properties:
        pm = {
            "sourceProperty": prop.get("sourceProperty", ""),
            "sourceDefinition": prop.get("sourceDefinition", ""),
            "sourcePath": prop.get("sourcePath", ""),
            "action": prop.get("propertyAction", "create-property"),
            "targetProperty": prop.get("targetProperty"),
            "targetPropertyLabel": prop.get("targetPropertyLabel"),
            "targetDefinition": prop.get("targetDefinition", ""),
            "targetPath": prop.get("targetPath", ""),
            "rationale": prop.get("rationale", ""),
            "reviewStatus": "pending-review",
        }
        # Carry forward newPropertyName if present (for create-property)
        if "newPropertyName" in prop:
            pm["newPropertyName"] = prop["newPropertyName"]
        # Carry forward targetDefinitionHash for staleness detection
        if "targetDefinitionHash" in prop:
            pm["targetDefinitionHash"] = prop["targetDefinitionHash"]
        mappings.append(pm)
    return mappings


def build_decision_log(entries):
    """Build decision log from alignment entries.

    One decision per entry, recording the action and rationale.
    """
    decisions = []
    for i, entry in enumerate(entries, 1):
        decisions.append({
            "id": i,
            "sourceConcept": entry["sourceConcept"],
            "action": entry.get("action", "pending"),
            "rationale": entry.get("actionRationale") or entry.get("rationale", ""),
            "targetType": entry.get("targetType"),
            "source": "resolve_alignment",
        })
    return decisions


def compute_summary(mappings):
    """Compute summary counts from mapping entries."""
    action_counts = {}
    for m in mappings:
        a = m["action"]
        action_counts[a] = action_counts.get(a, 0) + 1

    prop_stats = {
        "total": 0,
        "reuseProperty": 0,
        "createProperty": 0,
        "humanMustDecide": 0,
    }
    for m in mappings:
        for pm in m.get("propertyMappings", []):
            prop_stats["total"] += 1
            if pm["action"] == "reuse-property":
                prop_stats["reuseProperty"] += 1
            elif pm["action"] == "create-property":
                prop_stats["createProperty"] += 1
            elif pm["action"] == "human-must-decide":
                prop_stats["humanMustDecide"] += 1

    return {
        "totalConcepts": len(mappings),
        "actionCounts": action_counts,
        "pendingReview": sum(1 for m in mappings if m["reviewStatus"] == "pending-review"),
        "propertyStats": prop_stats,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 4: Build mapping matrix from alignment report")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    args = parser.parse_args()

    ctx = load_context(args.run_dir)
    run_dir = ctx.run_dir
    alignment, target_ontology, target_version = load_stage_data(ctx)

    matching_method = alignment.get("matchingMethod", "unknown")
    if matching_method == "pending-evaluation":
        print("\n  ERROR: Alignment report has matchingMethod='pending-evaluation'.")
        print("  Stage 3 semantic evaluation must complete before building the matrix.")
        raise SystemExit(1)

    entries = alignment.get("entries", [])
    actions = alignment.get("actions", {})
    type_patterns = alignment.get("typePatterns", {})

    # Build mapping matrix
    mappings = [build_mapping_entry(e) for e in entries]

    # Build decision log
    decision_log = build_decision_log(entries)

    # Compute summary
    summary = compute_summary(mappings)

    # Write mapping matrix
    matrix_doc = {
        "stage": "4",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "targetOntology": target_ontology,
        "targetVersion": target_version,
        "actions": actions,
        "typePatterns": type_patterns,
        "summary": summary,
        "mappings": sorted(mappings, key=lambda m: m["sourceConcept"]),
    }
    matrix_path = run_dir / "mapping-matrix.json"
    matrix_path.write_text(json.dumps(matrix_doc, indent=2) + "\n", encoding="utf-8")

    # Write decision log
    log_doc = {
        "stage": "4",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalDecisions": len(decision_log),
        "decisions": decision_log,
    }
    log_path = run_dir / "decision-log.json"
    log_path.write_text(json.dumps(log_doc, indent=2) + "\n", encoding="utf-8")

    # Report
    print(f"\nStage 4: Build mapping matrix")
    print(f"  Run: {run_dir}")
    print(f"  Mapping matrix: {matrix_path}")
    print(f"  Decision log: {log_path}")
    print(f"  Summary: {json.dumps(summary, indent=2)}")

    # Quality gates
    from ontology_mapper.quality_gates import check_decisions, format_warnings
    warnings = check_decisions(summary)
    if warnings:
        print(format_warnings(warnings))
        qg_report = {
            "stage": "4",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "warnings": warnings,
        }
        qg_path = run_dir / "quality-gate-report.json"
        qg_path.write_text(json.dumps(qg_report, indent=2) + "\n", encoding="utf-8")
        print(f"  Quality gate report: {qg_path}")
    else:
        print("\n  Quality gates: all checks passed")


if __name__ == "__main__":
    main()
