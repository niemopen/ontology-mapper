#!/usr/bin/env python3
"""Post-stage artifact verification for the OntologyMapper pipeline.

Checks that expected artifacts exist and have correct structure after each
pipeline stage.  Domain-agnostic — derives all paths from .mapper-state.json.

Usage:
    python runner_tools/verify_stage_outputs.py --run-dir <run_dir> --stage <stage>
    python runner_tools/verify_stage_outputs.py --run-dir <run_dir> --stage all

Stages: 1, 2, 3, 4, 5, 6a, 6b, 6c, 7, 8

As a module:
    from runner_tools.verify_stage_outputs import verify
    result = verify(run_dir, "6a")
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from ontology_mapper.pipeline_context import PipelineContext


VALID_STAGES = ["1", "2", "3", "4", "5", "6a", "6b", "6c", "7", "8"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check(name, passed, detail="", severity="error"):
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "detail": detail,
        "severity": severity,
    }


def _file_check(name, path, severity="error"):
    """Check that a file exists and is non-empty."""
    if not path.exists():
        return _check(name, False, f"Missing: {path.name}", severity)
    size = path.stat().st_size
    if size == 0:
        return _check(name, False, f"Empty: {path.name}", severity)
    return _check(name, True, f"{path.name} ({size:,} bytes)")


def _load_json(path):
    """Load JSON file, returning None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _load_state(run_dir):
    """Load .mapper-state.json, returning empty dict on failure."""
    return _load_json(run_dir / ".mapper-state.json") or {}


def _build_ctx(run_dir, state):
    """Build PipelineContext from state dict (no validation — verification must not fail on missing inputs)."""
    inputs = state.get("inputs", {})
    return PipelineContext.from_inputs(inputs, run_dir=run_dir)


# ---------------------------------------------------------------------------
# Per-stage verifiers
# ---------------------------------------------------------------------------

def _verify_stage_1(run_dir, state):
    checks = []
    si_path = run_dir / "source-inventory.json"
    checks.append(_file_check("source_inventory_exists", si_path))

    si = _load_json(si_path)
    if si:
        has_keys = all(k in si for k in ("input_package", "total_files", "input_type"))
        checks.append(_check("source_inventory_structure", has_keys,
                             "Has input_package, total_files, input_type" if has_keys
                             else "Missing required keys"))
        checks.append(_check("source_inventory_nonempty",
                             si.get("total_files", 0) > 0,
                             f"{si.get('total_files', 0)} files"))

    stages = state.get("stages", {})
    s1 = stages.get("1", {})
    completed = s1.get("status") == "completed"
    checks.append(_check("state_stage_completed", completed,
                         "Stage 1 completed in state" if completed
                         else "Stage 1 not marked completed in state"))
    return checks


def _verify_stage_2(run_dir, state):
    checks = []
    ci_path = run_dir / "concept-inventory.json"
    checks.append(_file_check("concept_inventory_exists", ci_path))

    ci = _load_json(ci_path)
    if ci:
        has_keys = all(k in ci for k in ("summary", "classes"))
        checks.append(_check("concept_inventory_structure", has_keys,
                             "Has summary and classes" if has_keys
                             else "Missing summary or classes"))

        cc = ci.get("summary", {}).get("classCount", 0)
        checks.append(_check("concept_inventory_nonempty", cc > 0,
                             f"{cc} classes"))
    return checks


def _verify_stage_3(run_dir, state):
    checks = []

    ar_path = run_dir / "alignment-report.json"
    checks.append(_file_check("alignment_report_exists", ar_path))

    ar = _load_json(ar_path)
    if ar:
        has_keys = all(k in ar for k in ("matchingMethod", "entries"))
        checks.append(_check("alignment_report_structure", has_keys,
                             "Has matchingMethod, entries" if has_keys
                             else "Missing required keys"))

        mm = ar.get("matchingMethod", "")
        checks.append(_check("alignment_matching_method", mm == "semantic",
                             f"matchingMethod={mm}"))

        entries = ar.get("entries", [])
        checks.append(_check("alignment_entry_count", len(entries) > 0,
                             f"{len(entries)} entries"))

        # Check entries are complete
        incomplete = [e["sourceConcept"] for e in entries
                      if not e.get("action") or not e.get("rationale")]
        checks.append(_check("alignment_entries_complete",
                             len(incomplete) == 0,
                             f"{len(incomplete)} incomplete entries"
                             if incomplete else "All entries have action + rationale"))

        # Check no abstract targets
        abstract = [e["sourceConcept"] for e in entries
                    if (e.get("targetType") or "").endswith(("Abstract", "AugmentationPoint"))]
        checks.append(_check("no_abstract_targets", len(abstract) == 0,
                             f"{len(abstract)} entries target Abstract/AugmentationPoint types"
                             if abstract else "No abstract targets"))
    return checks


def _verify_stage_4(run_dir, state):
    checks = []

    mm_path = run_dir / "mapping-matrix.json"
    dl_path = run_dir / "decision-log.json"
    ga_path = run_dir / "generation-audit.json"

    checks.append(_file_check("mapping_matrix_exists", mm_path))
    checks.append(_file_check("decision_log_exists", dl_path))
    checks.append(_file_check("generation_audit_exists", ga_path))

    mm = _load_json(mm_path)
    if not mm:
        return checks

    # --- Document-level structure ---
    required_keys = ("mappings", "summary", "actions", "typePatterns",
                     "targetOntology", "targetVersion")
    has_keys = all(k in mm for k in required_keys)
    missing = [k for k in required_keys if k not in mm]
    checks.append(_check("matrix_document_structure", has_keys,
                         "All required top-level keys present" if has_keys
                         else f"Missing: {', '.join(missing)}"))

    summary = mm.get("summary", {})
    mappings = mm.get("mappings", [])
    total = summary.get("totalConcepts", 0)
    checks.append(_check("matrix_summary_counts",
                         total == len(mappings),
                         f"totalConcepts={total}, len(mappings)={len(mappings)}"))

    # --- Action counts consistency ---
    action_counts = summary.get("actionCounts", {})
    action_sum = sum(action_counts.values())
    checks.append(_check("matrix_action_counts_sum",
                         action_sum == total,
                         f"actionCounts sum={action_sum}, totalConcepts={total}"))

    # --- Property stats ---
    ps = summary.get("propertyStats")
    checks.append(_check("matrix_property_stats_present", ps is not None,
                         f"total={ps.get('total', 0)}, reuse={ps.get('reuseProperty', 0)}, "
                         f"create={ps.get('createProperty', 0)}" if ps
                         else "No propertyStats in summary",
                         severity="warning"))
    if ps:
        ps_sum = ps.get("reuseProperty", 0) + ps.get("createProperty", 0)
        checks.append(_check("matrix_property_stats_consistent",
                             ps.get("total", 0) == ps_sum,
                             f"total={ps.get('total', 0)}, reuse+create={ps_sum}"))

    # --- Per-entry checks ---
    entry_required = ("sourceConcept", "action", "reviewStatus")
    incomplete = []
    missing_rationale = []
    missing_target_path = []
    for m in mappings:
        if not all(m.get(k) for k in entry_required):
            incomplete.append(m.get("sourceConcept", "?"))
        if not m.get("actionRationale") and not m.get("rationale"):
            missing_rationale.append(m.get("sourceConcept", "?"))
        if m.get("targetType") and not m.get("targetPath"):
            missing_target_path.append(m.get("sourceConcept", "?"))

    checks.append(_check("matrix_entries_complete",
                         len(incomplete) == 0,
                         f"{len(incomplete)} entries missing required fields: "
                         f"{', '.join(incomplete[:5])}"
                         if incomplete else f"All {len(mappings)} entries have required fields"))
    checks.append(_check("matrix_entries_have_rationale",
                         len(missing_rationale) == 0,
                         f"{len(missing_rationale)} entries missing rationale"
                         if missing_rationale else "All entries have rationale",
                         severity="warning"))
    checks.append(_check("matrix_entries_have_target_path",
                         len(missing_target_path) == 0,
                         f"{len(missing_target_path)} entries with targetType but no targetPath"
                         if missing_target_path else "All targeted entries have targetPath",
                         severity="warning"))

    # --- Property mappings carried through from Stage 3 ---
    targeted = [m for m in mappings if m.get("targetType")]
    has_props = [m for m in targeted if m.get("propertyMappings")]
    no_props = [m["sourceConcept"] for m in targeted if not m.get("propertyMappings")]
    checks.append(_check("matrix_property_mappings_present",
                         len(no_props) == 0,
                         f"{len(no_props)} targeted entries without propertyMappings: "
                         f"{', '.join(no_props[:5])}"
                         if no_props
                         else f"{len(has_props)}/{len(targeted)} targeted entries have propertyMappings",
                         severity="warning"))

    # --- Property mapping entry structure ---
    pm_required = ("sourceProperty", "action", "reviewStatus")
    bad_props = []
    for m in mappings:
        for pm in m.get("propertyMappings", []):
            if not all(pm.get(k) for k in pm_required):
                bad_props.append(f"{m.get('sourceConcept', '?')}/{pm.get('sourceProperty', '?')}")
    checks.append(_check("matrix_property_mapping_structure",
                         len(bad_props) == 0,
                         f"{len(bad_props)} property mappings missing required fields: "
                         f"{', '.join(bad_props[:5])}"
                         if bad_props else "All property mappings have required fields"))

    # --- Scaffolding consistency ---
    scaffold_issues = []
    for m in mappings:
        action = m.get("action")
        concept = m.get("sourceConcept", "?")
        if action == "extend":
            if not m.get("extensionType") or not m.get("baseType"):
                scaffold_issues.append(f"{concept}: extend missing extensionType/baseType")
        elif action == "augment":
            if not m.get("augmentationType") or not m.get("augmentsType"):
                scaffold_issues.append(f"{concept}: augment missing augmentationType/augmentsType")
        elif action == "reuse":
            if any(m.get(k) for k in ("extensionType", "baseType", "augmentationType", "augmentsType")):
                scaffold_issues.append(f"{concept}: reuse has unexpected scaffolding")
    checks.append(_check("matrix_scaffolding_consistent",
                         len(scaffold_issues) == 0,
                         "; ".join(scaffold_issues[:3])
                         if scaffold_issues else "Scaffolding consistent with actions"))

    return checks


def _verify_stage_5(run_dir, state):
    """Verify human review is complete."""
    checks = []

    hrd_path = run_dir / "human-review-decisions.json"
    checks.append(_file_check("human_decisions_exists", hrd_path))

    mm = _load_json(run_dir / "mapping-matrix.json")
    if mm:
        mappings = mm.get("mappings", [])

        pending_class = [m["sourceConcept"] for m in mappings
                         if m.get("reviewStatus") == "pending-review"]
        checks.append(_check("all_classes_accepted",
                             len(pending_class) == 0,
                             f"{len(pending_class)} classes still pending"
                             if pending_class
                             else f"All {len(mappings)} classes accepted"))

        pending_props = []
        for m in mappings:
            for pm in (m.get("propertyMappings") or []):
                if pm.get("reviewStatus") == "pending-review":
                    pending_props.append(f"{m['sourceConcept']}.{pm['sourceProperty']}")
        checks.append(_check("all_properties_accepted",
                             len(pending_props) == 0,
                             f"{len(pending_props)} properties still pending"
                             if pending_props
                             else "All properties accepted"))
    return checks


def _verify_stage_6a(run_dir, state):
    checks = []
    ctx = _build_ctx(run_dir, state)
    source = ctx.source
    pkg = ctx.pkg_dir

    checks.append(_check("edge_package_exists", pkg.is_dir(),
                         str(pkg)))

    ont_dir = pkg / "ontology"
    cmf_dir = pkg / "cmf"

    if source:
        for suffix in ("core", "extensions", "all", "combined"):
            p = ont_dir / ctx.ontology_filename(suffix)
            checks.append(_file_check(f"ontology_{suffix}_exists", p))

        cmf_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf"
        cmf_xml_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf.xml"
        cmf_exists = cmf_path.exists() or cmf_xml_path.exists()
        checks.append(_check("cmf_exists", cmf_exists,
                             f"{cmf_path.name}" if cmf_path.exists()
                             else f"{cmf_xml_path.name}" if cmf_xml_path.exists()
                             else "Neither .cmf nor .cmf.xml found"))

        cmf_json_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf.json"
        checks.append(_file_check("cmf_json_exists", cmf_json_path))
    else:
        # Glob fallback
        ttl_files = list(ont_dir.glob("*-edge-*.ttl")) if ont_dir.exists() else []
        checks.append(_check("ontology_files_found", len(ttl_files) >= 4,
                             f"{len(ttl_files)} TTL files (expected 4)"))

        cmf_files = list(cmf_dir.glob("*.cmf*")) if cmf_dir.exists() else []
        checks.append(_check("cmf_files_found", len(cmf_files) >= 2,
                             f"{len(cmf_files)} CMF files (expected 2)"))

    # OWL pattern checks: verify augment/extend patterns in extensions TTL
    ext_path = ont_dir / ctx.ontology_filename("extensions") if source else None
    mm = _load_json(run_dir / "mapping-matrix.json")
    if ext_path and ext_path.exists() and mm:
        ext_ttl = ext_path.read_text(encoding="utf-8")
        for m in mm.get("mappings", []):
            action = m.get("action")
            concept = m.get("sourceConcept", "?")

            if action == "augment":
                aug_type = m.get("augmentationType", "")
                if aug_type:
                    # NIEM augmentation is transparent — no class declaration
                    has_class = f"ext:{aug_type}" in ext_ttl and "a owl:Class" in ext_ttl
                    # More precise: check if ext:AugType appears as a class subject
                    class_decl = f"ext:{aug_type} a owl:Class"
                    checks.append(_check(
                        f"augment_no_class_{concept}",
                        class_decl not in ext_ttl,
                        f"ext:{aug_type} must NOT be declared as owl:Class "
                        f"(NIEM augmentation is transparent in OWL)",
                    ))

            elif action == "extend":
                base = m.get("baseType")
                ext_type = m.get("extensionType", "")
                if ext_type and base:
                    checks.append(_check(
                        f"extend_subclass_{concept}",
                        f"rdfs:subClassOf {base}" in ext_ttl
                        or f"rdfs:subClassOf  {base}" in ext_ttl,
                        f"ext:{ext_type} should have rdfs:subClassOf {base}",
                        severity="warning",
                    ))

    return checks


def _verify_stage_6b(run_dir, state):
    checks = []
    pkg = _build_ctx(run_dir, state).pkg_dir

    expected_files = [
        ("mappings_matrix", pkg / "mappings" / "mapping-matrix.json"),
        ("mappings_alignment", pkg / "mappings" / "alignment-report.json"),
        ("mappings_justifications", pkg / "mappings" / "extension-justifications.md"),
        ("extensions_catalog", pkg / "extensions" / "extension-catalog.json"),
        ("governance_decision_log", pkg / "governance" / "decision-log.json"),
        ("governance_audit", pkg / "governance" / "generation-audit.json"),
        ("package_manifest", pkg / "package-manifest.json"),
        ("readme", pkg / "README.md"),
    ]
    for name, path in expected_files:
        checks.append(_file_check(name, path))

    # Cross-check manifest stats against mapping matrix
    manifest = _load_json(pkg / "package-manifest.json")
    mm = _load_json(run_dir / "mapping-matrix.json")
    if manifest and mm:
        m_stats = manifest.get("stats", {})
        mm_summary = mm.get("summary", {})
        m_total = m_stats.get("totalConcepts", -1)
        mm_total = mm_summary.get("totalConcepts", -2)
        checks.append(_check("manifest_stats_match_matrix",
                             m_total == mm_total,
                             f"manifest.totalConcepts={m_total}, matrix.totalConcepts={mm_total}",
                             severity="warning"))
    return checks


def _verify_stage_6c(run_dir, state):
    checks = []
    ctx = _build_ctx(run_dir, state)
    pkg = ctx.pkg_dir
    kg = pkg / "kg"

    checks.append(_file_check("kg_neo4j_schema", kg / "neo4j" / "schema.cypher"))
    checks.append(_file_check("kg_neo4j_seed", kg / "neo4j" / "seed.cypher", severity="info"))

    queries_dir = kg / "neo4j" / "queries"
    cypher_files = list(queries_dir.glob("*.cypher")) if queries_dir.exists() else []
    checks.append(_check("kg_neo4j_queries", len(cypher_files) > 0,
                         f"{len(cypher_files)} query files"))

    if ctx.source:
        checks.append(_file_check("kg_rdf_trig", kg / "rdf" / ctx.trig_filename))
    else:
        trig_files = list((kg / "rdf").glob("*.trig")) if (kg / "rdf").exists() else []
        checks.append(_check("kg_rdf_trig", len(trig_files) > 0,
                             f"{len(trig_files)} .trig files"))

    sparql_dir = kg / "rdf" / "sparql"
    rq_files = list(sparql_dir.glob("*.rq")) if sparql_dir.exists() else []
    checks.append(_check("kg_rdf_sparql", len(rq_files) > 0,
                         f"{len(rq_files)} SPARQL query files"))

    checks.append(_file_check("kg_import_transform", kg / "import" / "internal-to-edge.json"))
    checks.append(_file_check("kg_import_loader", kg / "import" / "loader-config.json"))
    return checks


def _verify_stage_7(run_dir, state):
    checks = []
    vr_path = run_dir / "validation-report.json"
    checks.append(_file_check("validation_report_exists", vr_path))

    fb_path = run_dir / "feedback-report.json"
    checks.append(_file_check("feedback_report_exists", fb_path))

    vr = _load_json(vr_path)
    if vr:
        vr_checks = vr.get("checks", [])
        failures = [c for c in vr_checks if c.get("status") == "FAIL"]
        checks.append(_check("validation_all_pass",
                             len(failures) == 0,
                             f"{len(failures)} checks failed"
                             if failures else f"All {len(vr_checks)} checks passed",
                             severity="warning"))
    return checks


def _verify_stage_8(run_dir, state):
    checks = []
    pkg = _build_ctx(run_dir, state).pkg_dir
    gov = pkg / "governance"

    checks.append(_file_check("version_manifest", gov / "version-manifest.json"))
    checks.append(_file_check("lineage_manifest", gov / "lineage-manifest.json"))
    checks.append(_file_check("validation_report_pkg", gov / "validation-report.json"))
    checks.append(_file_check("change_impact", gov / "change-impact.md"))

    # Verify package-manifest.json has finalizedAt and actionCounts
    manifest = _load_json(pkg / "package-manifest.json")
    if manifest:
        has_finalized = bool(manifest.get("finalizedAt"))
        checks.append(_check("package_manifest_finalized", has_finalized,
                             f"finalizedAt: {manifest.get('finalizedAt', 'missing')}"
                             if has_finalized else "No finalizedAt timestamp"))

        stats = manifest.get("stats", {})
        has_action_counts = bool(stats.get("actionCounts"))
        checks.append(_check("package_manifest_action_counts", has_action_counts,
                             f"actionCounts: {stats.get('actionCounts')}"
                             if has_action_counts else "No stats.actionCounts"))

    # Verify version-manifest includes timing data
    vm = _load_json(gov / "version-manifest.json")
    if vm:
        has_timing = bool(vm.get("pipelineTiming"))
        checks.append(_check("version_manifest_timing", has_timing,
                             "Pipeline timing included" if has_timing
                             else "No pipelineTiming (stage timings may not have been recorded)",
                             severity="warning"))

    return checks


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

STAGE_VERIFIERS = {
    "1": _verify_stage_1,
    "2": _verify_stage_2,
    "3": _verify_stage_3,
    "4": _verify_stage_4,
    "5": _verify_stage_5,
    "6a": _verify_stage_6a,
    "6b": _verify_stage_6b,
    "6c": _verify_stage_6c,
    "7": _verify_stage_7,
    "8": _verify_stage_8,
}


def verify(run_dir, stage):
    """Run verification checks for a given stage.

    Args:
        run_dir: Path to the pipeline run directory.
        stage: Stage identifier (e.g. "1", "5", "6a") or "all".

    Returns:
        Dict with keys: stage, runDir, timestamp, checks, summary.
    """
    run_dir = Path(run_dir)
    state = _load_state(run_dir)

    if stage == "all":
        all_checks = []
        for s in VALID_STAGES:
            fn = STAGE_VERIFIERS[s]
            all_checks.extend(fn(run_dir, state))
        checks = all_checks
        stage_label = "all"
    else:
        fn = STAGE_VERIFIERS.get(stage)
        if not fn:
            return {"error": f"Unknown stage: {stage}. Valid: {', '.join(VALID_STAGES)}"}
        checks = fn(run_dir, state)
        stage_label = stage

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail" and c["severity"] == "error")
    warned = sum(1 for c in checks if c["status"] == "fail" and c["severity"] == "warning")

    return {
        "stage": stage_label,
        "runDir": str(run_dir),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "summary": {"total": len(checks), "pass": passed, "fail": failed, "warn": warned},
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Post-stage artifact verification")
    parser.add_argument("--run-dir", required=True, help="Run directory path")
    parser.add_argument("--stage", required=True, help=f"Stage to verify: {', '.join(VALID_STAGES)}, all")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    stage = args.stage

    if not run_dir.exists():
        print(f"Error: run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    result = verify(run_dir, stage)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    # Print human-readable summary
    summary = result["summary"]
    icon = "PASS" if summary["fail"] == 0 else "FAIL"
    print(f"\n  Stage {result['stage']} verification: {icon}")
    print(f"  Run: {run_dir.name}")
    print(f"  Checks: {summary['pass']} pass, {summary['fail']} fail, {summary['warn']} warn")
    print()

    for c in result["checks"]:
        if c["status"] == "pass":
            mark = "  [ok]"
        elif c["severity"] == "warning":
            mark = "  [!!]"
        else:
            mark = "  [XX]"
        print(f"{mark} {c['name']}: {c['detail']}")

    # Also write JSON to stdout-adjacent file for programmatic use
    json_path = run_dir / f"verify-stage-{stage.replace('.', '_')}.json"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\n  Detailed results: {json_path}")

    sys.exit(1 if summary["fail"] > 0 else 0)


if __name__ == "__main__":
    main()
