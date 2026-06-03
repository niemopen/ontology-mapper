#!/usr/bin/env python3
"""Stage 8: Finalize — stamp the edge package with version, lineage, and validation metadata.

Runs after Stage 7 validation. Writes:

  - governance/version-manifest.json  (version history and generation context)
  - governance/lineage-manifest.json  (provenance from sources to artifacts)
  - governance/validation-report.json (copy of Stage 7 validation results)
  - governance/change-impact.md       (impact analysis summary)
  - Updates package-manifest.json     (final stats reconciliation)

This is a deterministic tool — no semantic reasoning required.

Usage:
    om-finalize                  # uses mapper state
    om-finalize <run_dir> <pkg>  # explicit paths
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from ontology_mapper.pipeline_context import load_context


def _count_actions(mappings):
    """Count actions from a mappings list. Returns {action: count} dict."""
    counts = {}
    for m in mappings:
        action = m.get("action", "unknown")
        counts[action] = counts.get(action, 0) + 1
    return counts


def _load_stage_timings(state):
    """Extract per-stage timing from pipeline state. Returns list of dicts."""
    timings = []
    stages = state.get("stages", {})
    for stage_num in sorted(stages.keys(), key=lambda s: (len(s), s)):
        entry = stages[stage_num]
        started = entry.get("started_at")
        completed = entry.get("completed_at")
        duration = None
        if started and completed:
            try:
                from datetime import datetime as dt
                t0 = dt.fromisoformat(started)
                t1 = dt.fromisoformat(completed)
                duration = round((t1 - t0).total_seconds(), 1)
            except (ValueError, TypeError):
                pass
        timings.append({
            "stage": stage_num,
            "name": entry.get("notes", ""),
            "status": entry.get("status", "unknown"),
            "startedAt": started,
            "completedAt": completed,
            "durationSeconds": duration,
        })
    return timings


def _total_duration(timings):
    """Calculate total pipeline duration from first start to last completion."""
    starts = [t["startedAt"] for t in timings if t["startedAt"]]
    ends = [t["completedAt"] for t in timings if t["completedAt"]]
    if not starts or not ends:
        return None
    try:
        from datetime import datetime as dt
        first = min(dt.fromisoformat(s) for s in starts)
        last = max(dt.fromisoformat(e) for e in ends)
        return round((last - first).total_seconds(), 1)
    except (ValueError, TypeError):
        return None


def build_version_manifest(ctx, matrix, state=None):
    """Build governance/version-manifest.json."""
    mappings = matrix.get("mappings", [])
    action_counts = _count_actions(mappings)
    source_name = ctx.agency_package_name
    now = datetime.now(timezone.utc).isoformat()

    manifest = {
        "currentVersion": "1.0.0",
        "targetOntology": ctx.target_ontology,
        "targetVersion": ctx.target_version,
        "mapperVersion": "ontology-mapper-1.0",
        "sourcePackageVersion": f"{source_name}@1.0",
        "generationHistory": [
            {
                "version": "1.0.0",
                "generatedAt": now,
                "targetOntology": ctx.target_ontology,
                "targetVersion": ctx.target_version,
                "changeDescription": f"Initial generation from {source_name}.",
                "conceptCount": len(mappings),
                "mappingStats": action_counts,
            }
        ],
    }

    # Include pipeline timing if state is available
    if state:
        timings = _load_stage_timings(state)
        total = _total_duration(timings)
        manifest["pipelineTiming"] = {
            "stages": timings,
            "totalDurationSeconds": total,
        }

    return manifest


def build_lineage_manifest(ctx, matrix):
    """Build governance/lineage-manifest.json tracking provenance."""
    artifacts = []
    now = datetime.now(timezone.utc).isoformat()

    # Collect target ontology references from the mapping matrix
    target_refs = set()
    source_concepts = set()
    for m in matrix.get("mappings", []):
        if m.get("targetType"):
            target_refs.add(m["targetType"])
        source_concepts.add(m["sourceConcept"])

    # Scan generated ontology files
    pkg = ctx.pkg_dir
    source_package = ctx.input_package_path
    ontology_dir = pkg / "ontology"
    if ontology_dir.exists():
        for ttl_file in sorted(ontology_dir.glob("*.ttl")):
            rel = str(ttl_file.relative_to(pkg)).replace("\\", "/")
            artifacts.append({
                "artifactPath": rel,
                "generatedAt": now,
                "generatedBy": "ontology-mapper",
                "stage": "generate",
                "sourceInputs": [str(source_package)] if source_package else [],
                "targetReferences": sorted(target_refs),
                "mappingEntries": sorted(source_concepts),
                "dependsOn": ["mappings/mapping-matrix.json"],
            })

    # Collect ontology file names for CMF sourceInputs
    ontology_files = []
    if ontology_dir.exists():
        ontology_files = sorted(f"ontology/{f.name}" for f in ontology_dir.glob("*.ttl"))

    # CMF artifacts
    cmf_dir = pkg / "cmf"
    if cmf_dir.exists():
        for cmf_file in sorted(cmf_dir.iterdir()):
            if cmf_file.is_file():
                rel = str(cmf_file.relative_to(pkg)).replace("\\", "/")
                artifacts.append({
                    "artifactPath": rel,
                    "generatedAt": now,
                    "generatedBy": "owl_cmf_bridge",
                    "stage": "generate",
                    "sourceInputs": ontology_files,
                    "targetReferences": sorted(target_refs),
                    "mappingEntries": sorted(source_concepts),
                    "dependsOn": ["ontology/"],
                })

    # Shapes
    shapes_dir = pkg / "shapes"
    if shapes_dir.exists():
        for shape_file in sorted(shapes_dir.glob("*.ttl")):
            rel = str(shape_file.relative_to(pkg)).replace("\\", "/")
            artifacts.append({
                "artifactPath": rel,
                "generatedAt": now,
                "generatedBy": "ontology-mapper",
                "stage": "generate",
                "sourceInputs": [str(source_package)] if source_package else [],
                "mappingEntries": sorted(source_concepts),
                "dependsOn": ["mappings/mapping-matrix.json"],
            })

    # KG artifacts (graph deployment scripts)
    kg_dir = pkg / "kg"
    if kg_dir.exists():
        for kg_file in sorted(kg_dir.rglob("*")):
            if kg_file.is_file():
                rel = str(kg_file.relative_to(pkg)).replace("\\", "/")
                artifacts.append({
                    "artifactPath": rel,
                    "generatedAt": now,
                    "generatedBy": "ontology-mapper",
                    "stage": "generate",
                    "sourceInputs": [str(source_package)] if source_package else [],
                    "mappingEntries": sorted(source_concepts),
                    "dependsOn": ["mappings/mapping-matrix.json", "ontology/"],
                })

    return {"artifacts": artifacts}


def build_change_impact(matrix, validation_report, generation_audit):
    """Generate governance/change-impact.md summarizing potential impacts."""
    lines = [
        "# Change Impact Analysis",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        "",
    ]

    mappings = matrix.get("mappings", [])
    summary = matrix.get("summary", {})
    total = summary.get("totalConcepts", len(mappings))
    extend_count = summary.get("extend", sum(1 for m in mappings if m.get("action") == "extend"))
    reuse_count = summary.get("reuse", sum(1 for m in mappings if m.get("action") == "reuse"))

    lines.append(f"- **Total concepts**: {total}")
    lines.append(f"- **Target reuse**: {reuse_count} (stable, low change risk)")
    lines.append(f"- **Extensions**: {extend_count} (custom, higher change risk)")
    lines.append("")

    # Validation status
    if validation_report:
        passed = validation_report.get("allPassed", False)
        fail_count = validation_report.get("failCount", 0)
        lines.append("## Validation Status")
        lines.append("")
        if passed:
            lines.append("All validation checks passed.")
        else:
            lines.append(f"**{fail_count} validation check(s) failed.**")
            lines.append("")
            for check in validation_report.get("checks", []):
                if check["status"] == "FAIL":
                    lines.append(f"- {check['check']}: {check.get('details', '')}")
        lines.append("")

    # Generation audit findings
    if generation_audit:
        findings = generation_audit.get("findings", [])
        warnings = [f for f in findings if f.get("severity") == "warning"]
        if warnings:
            lines.append("## Generation Warnings")
            lines.append("")
            lines.append(f"{len(warnings)} warning(s) from generation audit:")
            lines.append("")
            for w in warnings:
                lines.append(f"- **{w.get('concept', 'unknown')}**: {w.get('message', '')}")
            lines.append("")

    # Extension impact
    extensions = [m for m in mappings if m.get("action") == "extend"]
    if extensions:
        lines.append("## Extension Impact")
        lines.append("")
        lines.append("Extensions are custom types not in the target ontology. Changes to target ontology versions")
        lines.append("will not affect these, but they must be maintained by the domain owner.")
        lines.append("")
        lines.append("| Extension | Base Target Type |")
        lines.append("|-----------|---------------|")
        for ext in sorted(extensions, key=lambda e: e["sourceConcept"]):
            concept = ext["sourceConcept"]
            base = ext.get("targetType", "none")
            lines.append(f"| {concept} | {base} |")
        lines.append("")

    # Target ontology version impact
    lines.append("## Target Ontology Version Considerations")
    lines.append("")
    lines.append("If upgrading the target ontology version:")
    lines.append("")
    lines.append("- **Reuse mappings**: Verify each `targetType` still exists in the new version")
    lines.append("- **Extension base types**: Verify base types for extensions still exist")
    lines.append("- **Namespace changes**: Check for namespace URI changes between versions")
    lines.append("")

    return "\n".join(lines) + "\n"


def reconcile_manifest(pkg, matrix):
    """Update package-manifest.json with final accurate stats and finalizedAt."""
    manifest_path = pkg / "package-manifest.json"
    if not manifest_path.exists():
        return False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mappings = matrix.get("mappings", [])
    action_counts = _count_actions(mappings)

    manifest["stats"] = {
        "totalConcepts": len(mappings),
        "actionCounts": action_counts,
    }
    manifest["version"] = "1.0.0"
    manifest["finalizedAt"] = datetime.now(timezone.utc).isoformat()

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 8: Finalize package with governance artifacts")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    parser.add_argument("--package-dir", default=None, help="Edge package directory path")
    args = parser.parse_args()

    ctx = load_context(args.run_dir, args.package_dir)

    print(f"\n  Stage 8: Finalize Package")
    print(f"  Run directory: {ctx.run_dir}")
    print(f"  Edge package:  {ctx.pkg_dir}")
    print()

    # Load required artifacts
    matrix_path = ctx.run_dir / "mapping-matrix.json"
    if not matrix_path.exists():
        # Try edge package copy
        matrix_path = ctx.pkg_dir / "mappings" / "mapping-matrix.json"
    if not matrix_path.exists():
        print(f"  ERROR: mapping-matrix.json not found")
        sys.exit(1)
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))

    # Load optional artifacts
    val_path = ctx.run_dir / "validation-report.json"
    validation_report = json.loads(val_path.read_text(encoding="utf-8")) if val_path.exists() else None

    audit_path = ctx.run_dir / "generation-audit.json"
    generation_audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None

    # Load pipeline state for timing data
    from ontology_mapper.run_dir_utils import STATE_FILENAME
    state_path = ctx.run_dir / STATE_FILENAME
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None

    pkg = ctx.pkg_dir
    gov_dir = pkg / "governance"
    gov_dir.mkdir(parents=True, exist_ok=True)
    artifacts_written = 0

    # ── 1. Version manifest ───────────────────────────────────────────────
    version_manifest = build_version_manifest(ctx, matrix, state)
    vm_path = gov_dir / "version-manifest.json"
    vm_path.write_text(json.dumps(version_manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  [+] version-manifest.json (v{version_manifest['currentVersion']})")
    artifacts_written += 1

    # ── 2. Lineage manifest ───────────────────────────────────────────────
    lineage = build_lineage_manifest(ctx, matrix)
    lm_path = gov_dir / "lineage-manifest.json"
    lm_path.write_text(json.dumps(lineage, indent=2) + "\n", encoding="utf-8")
    print(f"  [+] lineage-manifest.json ({len(lineage['artifacts'])} artifacts tracked)")
    artifacts_written += 1

    # ── 3. Validation report copy ─────────────────────────────────────────
    if validation_report:
        vr_path = gov_dir / "validation-report.json"
        vr_path.write_text(json.dumps(validation_report, indent=2) + "\n", encoding="utf-8")
        print(f"  [+] validation-report.json (passed: {validation_report.get('allPassed', 'unknown')})")
        artifacts_written += 1
    else:
        print(f"  [-] validation-report.json: not found in run directory")

    # ── 4. Change impact analysis ─────────────────────────────────────────
    change_impact = build_change_impact(matrix, validation_report, generation_audit)
    ci_path = gov_dir / "change-impact.md"
    ci_path.write_text(change_impact, encoding="utf-8")
    print(f"  [+] change-impact.md")
    artifacts_written += 1

    # ── 5. Reconcile package manifest ─────────────────────────────────────
    if reconcile_manifest(pkg, matrix):
        print(f"  [+] package-manifest.json updated with final stats")
        artifacts_written += 1
    else:
        print(f"  [-] package-manifest.json: not found, skipping reconciliation")

    # ── Summary ───────────────────────────────────────────────────────────
    all_passed = validation_report.get("allPassed", False) if validation_report else False
    status = "READY" if all_passed else "REVIEW NEEDED"

    print(f"\n  Done: {artifacts_written} artifacts written")
    print(f"  Package status: {status}")
    print(f"  Package location: {pkg}")

    if not all_passed and validation_report:
        fail_count = validation_report.get("failCount", 0)
        print(f"  Warning: {fail_count} validation check(s) failed - review change-impact.md")

    return 0  # Always succeed — validation failures are advisory


if __name__ == "__main__":
    sys.exit(main())
