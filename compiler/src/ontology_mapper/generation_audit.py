"""Generation audit — detect data integrity issues before Stage 6 generation.

Runs after Stage 4 (build matrix) and before Stage 6 (generate) to catch
problems that validation can't easily diagnose. Compares the concept inventory
and mapping matrix, identifying:

  - Active classes with zero source properties (GA-001)
  - Augment action on a non-NIEM flow (GA-002)
  - Augment entries with zero reuse-properties (GA-003)
  - Concepts with source properties but no property mappings in matrix (GA-004)
  - Missing structural scaffolding for extend/augment entries (GA-005)
  - Unresolved human-must-decide properties (GA-006)

Each finding links back to the specific entry that caused it, so the
operator can trace downstream effects to upstream choices.
"""

import json
from pathlib import Path
from datetime import datetime, timezone


def load_inputs(run_dir_arg=None):
    """Load the concept inventory and mapping matrix from a run directory."""
    if not run_dir_arg:
        raise ValueError("run_dir is required")
    run_dir = Path(run_dir_arg)
    inv = json.loads((run_dir / "concept-inventory.json").read_text(encoding="utf-8"))
    matrix = json.loads((run_dir / "mapping-matrix.json").read_text(encoding="utf-8"))
    return run_dir, inv, matrix


def audit_generation(inv, matrix):
    """Audit the mapping matrix against the concept inventory for generation gaps.

    Returns a list of finding dicts:
        [{severity, code, concept, message, related}]
    """
    findings = []
    target_ontology = matrix.get("targetOntology", "")

    # Build lookup of active entries
    active = {}
    for m in matrix["mappings"]:
        if m["action"] in ("reuse", "extend", "augment"):
            active[m["sourceConcept"]] = m

    # Build source property counts per class from inventory
    source_prop_counts = {q: 0 for q in active}
    for prop in inv.get("objectProperties", []):
        for dom in prop.get("domain", []):
            if dom in source_prop_counts:
                source_prop_counts[dom] += 1
    for prop in inv.get("datatypeProperties", []):
        for dom in prop.get("domain", []):
            if dom in source_prop_counts:
                source_prop_counts[dom] += 1
    for shape in inv.get("shaclShapes", []):
        target = shape.get("targetClass", "")
        if target in source_prop_counts:
            source_prop_counts[target] += len(shape.get("properties", []))

    # --- GA-001: Active class with zero source properties ---
    for concept, count in source_prop_counts.items():
        if count == 0:
            m = active[concept]
            findings.append({
                "severity": "info",
                "code": "GA-001",
                "concept": concept,
                "message": (
                    f"{m['action'].capitalize()} class {concept} has zero source properties. "
                    f"Generated type will have no domain-specific properties."
                ),
                "related": {
                    "action": m["action"],
                    "targetType": m.get("targetType"),
                },
            })

    # --- GA-002: Augment action on non-NIEM flow ---
    for concept, m in active.items():
        if m["action"] == "augment" and not target_ontology.startswith("niem"):
            findings.append({
                "severity": "error",
                "code": "GA-002",
                "concept": concept,
                "message": (
                    f"Augment action on {concept} but target ontology is "
                    f"'{target_ontology}', not NIEM. Augmentation is NIEM-specific."
                ),
                "related": {
                    "action": "augment",
                    "targetType": m.get("targetType"),
                    "targetOntology": target_ontology,
                },
            })

    # --- GA-003: Augment entry with zero reuse-properties ---
    for concept, m in active.items():
        if m["action"] != "augment":
            continue
        pms = m.get("propertyMappings", [])
        reuse_count = sum(1 for p in pms if p.get("action") == "reuse-property")
        if pms and reuse_count == 0:
            findings.append({
                "severity": "warning",
                "code": "GA-003",
                "concept": concept,
                "message": (
                    f"Augment class {concept} has {len(pms)} property mappings but "
                    f"none are reuse-property. Augmentation reuses existing properties "
                    f"— this may indicate the action should be extend instead."
                ),
                "related": {
                    "action": "augment",
                    "targetType": m.get("targetType"),
                    "propertyCount": len(pms),
                },
            })

    # --- GA-004: Concept with source properties but no property mappings ---
    for concept, m in active.items():
        source_count = source_prop_counts.get(concept, 0)
        matrix_count = len(m.get("propertyMappings", []))
        if source_count > 0 and matrix_count == 0:
            findings.append({
                "severity": "warning",
                "code": "GA-004",
                "concept": concept,
                "message": (
                    f"{m['action'].capitalize()} class {concept} has {source_count} "
                    f"source properties but no property mappings in the matrix. "
                    f"Properties may have been lost between Stage 3 and Stage 4."
                ),
                "related": {
                    "action": m["action"],
                    "targetType": m.get("targetType"),
                    "sourcePropertyCount": source_count,
                },
            })

    # --- GA-005: Scaffolding consistency ---
    for concept, m in active.items():
        action = m["action"]
        if action == "extend":
            if not m.get("extensionType") or not m.get("baseType"):
                findings.append({
                    "severity": "error",
                    "code": "GA-005",
                    "concept": concept,
                    "message": (
                        f"Extend class {concept} is missing scaffolding: "
                        f"extensionType={m.get('extensionType')}, baseType={m.get('baseType')}. "
                        f"Both are required for generation."
                    ),
                    "related": {"action": action, "targetType": m.get("targetType")},
                })
        elif action == "augment":
            if not m.get("augmentationType") or not m.get("augmentsType"):
                findings.append({
                    "severity": "error",
                    "code": "GA-005",
                    "concept": concept,
                    "message": (
                        f"Augment class {concept} is missing scaffolding: "
                        f"augmentationType={m.get('augmentationType')}, "
                        f"augmentsType={m.get('augmentsType')}. "
                        f"Both are required for generation."
                    ),
                    "related": {"action": action, "targetType": m.get("targetType")},
                })
        elif action == "reuse":
            has_scaffolding = any(m.get(k) for k in (
                "extensionType", "baseType", "augmentationType", "augmentsType"
            ))
            if has_scaffolding:
                findings.append({
                    "severity": "warning",
                    "code": "GA-005",
                    "concept": concept,
                    "message": (
                        f"Reuse class {concept} has structural scaffolding that "
                        f"should not be present. Reuse uses the target type as-is."
                    ),
                    "related": {"action": action, "targetType": m.get("targetType")},
                })

    # --- GA-006: Unresolved human-must-decide properties ---
    for concept, m in active.items():
        pms = m.get("propertyMappings", [])
        unresolved = [p for p in pms if p.get("action") == "human-must-decide"]
        if unresolved:
            names = [p.get("sourceProperty", "?") for p in unresolved]
            findings.append({
                "severity": "error",
                "code": "GA-006",
                "concept": concept,
                "message": (
                    f"{concept} has {len(unresolved)} unresolved human-must-decide "
                    f"properties: {', '.join(names)}. These must be resolved at "
                    f"Stage 5 before generation."
                ),
                "related": {
                    "action": m["action"],
                    "targetType": m.get("targetType"),
                    "unresolvedProperties": names,
                },
            })

    # --- GA-007: Scaffolding/targetType consistency ---
    for concept, m in active.items():
        action = m["action"]
        target_type = m.get("targetType")
        if action == "augment" and m.get("augmentsType") != target_type:
            findings.append({
                "severity": "error",
                "code": "GA-007",
                "concept": concept,
                "message": (
                    f"{concept} has action augment but augmentsType "
                    f"({m.get('augmentsType')}) does not match targetType "
                    f"({target_type}). Target type may have been changed "
                    f"without reclassifying properties."
                ),
                "related": {
                    "action": action,
                    "targetType": target_type,
                    "augmentsType": m.get("augmentsType"),
                },
            })
        elif action == "extend" and target_type is not None and m.get("baseType") != target_type:
            findings.append({
                "severity": "error",
                "code": "GA-007",
                "concept": concept,
                "message": (
                    f"{concept} has action extend but baseType "
                    f"({m.get('baseType')}) does not match targetType "
                    f"({target_type}). Target type may have been changed "
                    f"without reclassifying properties."
                ),
                "related": {
                    "action": action,
                    "targetType": target_type,
                    "baseType": m.get("baseType"),
                },
            })

    return findings


def format_findings(findings):
    """Format findings for console output."""
    if not findings:
        return "\n  Generation audit: no issues found"

    icons = {"error": "X", "warning": "!", "info": "-"}
    lines = ["\n  Generation Audit:"]
    for f in findings:
        icon = icons.get(f["severity"], "?")
        lines.append(f"    [{icon}] {f['code']}: {f['message']}")

    errors = sum(1 for f in findings if f["severity"] == "error")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    infos = sum(1 for f in findings if f["severity"] == "info")
    lines.append(f"    ({errors} errors, {warnings} warnings, {infos} info)")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generation audit: Check matrix consistency before generation")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    args = parser.parse_args()

    run_dir, inv, matrix = load_inputs(args.run_dir)

    findings = audit_generation(inv, matrix)
    print(format_findings(findings))

    # Save audit report
    report = {
        "stage": "4-audit",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "findingCount": len(findings),
        "findings": findings,
    }
    out_path = run_dir / "generation-audit.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"  Audit report: {out_path}")

    # Exit non-zero if errors found
    if any(f["severity"] == "error" for f in findings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
