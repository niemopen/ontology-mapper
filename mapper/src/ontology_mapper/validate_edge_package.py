#!/usr/bin/env python3
"""Stage 7: Validate — run all conformance checks on the edge package."""

import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from ontology_mapper.pipeline_context import load_context


import re


def add_check(results, name, passed, details=""):
    """Record a single validation check result."""
    status = "pass" if passed else "FAIL"
    results.append({"check": name, "status": status, "details": details})
    icon = "+" if passed else "!"
    print(f"  [{icon}] {name}: {status}" + (f" — {details}" if details else ""))


# ---------------------------------------------------------------------------
# Testable cross-reference helpers
# ---------------------------------------------------------------------------
def check_schema_labels(schema_content, active_labels):
    """Check that Cypher schema constraint/index labels reference active classes.

    Args:
        schema_content: Text of schema.cypher.
        active_labels: Set of active class labels from the mapping matrix.

    Returns:
        List of error strings. Empty means all labels match.
    """
    constraint_labels = set(re.findall(r"FOR \(n:(\w+)\)", schema_content))
    return [
        f"Constraint references unknown label: {label}"
        for label in sorted(constraint_labels)
        if label not in active_labels
    ]


def check_seed_consistency(seed_content):
    """Check that MATCH labels in seed.cypher reference CREATEd labels.

    Args:
        seed_content: Text of seed.cypher.

    Returns:
        Tuple of (created_labels, matched_labels, errors).
    """
    created = set(re.findall(r"CREATE \(:(\w+)\s", seed_content))
    matched = set(re.findall(r"MATCH \(\w+:(\w+)\s", seed_content))
    unmatched = matched - created
    errors = []
    if unmatched:
        errors.append(f"MATCH references labels not CREATEd: {unmatched}")
    return created, matched, errors


def check_transform_sources(transforms_data, mapped_concepts):
    """Check that transform source types match the mapping matrix.

    Args:
        transforms_data: Parsed internal-to-edge.json dict.
        mapped_concepts: Set of active source concept qnames.

    Returns:
        List of error strings.
    """
    errors = []
    for t in transforms_data.get("transforms", []):
        src = t.get("sourceType")
        if src and src not in mapped_concepts:
            errors.append(f"Transform source '{src}' not in matrix")
    return errors


def validate_cmf_schema(cmf_path):
    """Validate a CMF file against the official NIEM CMF XSD schema.

    Uses the bundled message.xsd variant from
    https://github.com/niemopen/common-model-format.

    Args:
        cmf_path: Path to the .cmf XML file.

    Returns:
        List of error strings. Empty means XSD-valid.
    """
    from lxml import etree

    xsd_dir = Path(__file__).parent / "specs" / "cmf-xsd"
    xsd_path = xsd_dir / "cmf.xsd"
    if not xsd_path.exists():
        return ["CMF XSD schema not found at specs/cmf-xsd/cmf.xsd"]

    try:
        xsd_doc = etree.parse(str(xsd_path))
        schema = etree.XMLSchema(xsd_doc)
    except Exception as e:
        return [f"CMF XSD schema load error: {str(e)[:150]}"]

    try:
        doc = etree.parse(str(cmf_path))
    except Exception as e:
        return [f"CMF XML parse error: {str(e)[:150]}"]

    if schema.validate(doc):
        return []

    # Deduplicate errors by message prefix
    seen = set()
    errors = []
    for err in schema.error_log:
        key = err.message[:120]
        if key not in seen:
            seen.add(key)
            errors.append(f"L{err.line}: {err.message}")
        if len(errors) >= 10:
            remaining = len(schema.error_log) - len(seen)
            if remaining > 0:
                errors.append(f"... and {remaining} more XSD errors")
            break
    return errors


def check_cmf_consistency(cmf_path, mappings_list):
    """Check that CMF XML is well-formed, XSD-valid, and consistent with the matrix.

    Validates:
    - CMF XML parses without error
    - CMF conforms to the official NIEM CMF XSD schema
    - Class count matches active (reuse + extend) classes in matrix
    - AugmentationRecord entries exist for augment-action mappings
    - At least one property exists

    Args:
        cmf_path: Path to the .cmf XML file.
        mappings_list: List of mapping entry dicts from the matrix.

    Returns:
        List of error strings. Empty means all checks pass.
    """
    errors = []
    try:
        from lxml import etree
    except ImportError:
        errors.append("lxml not installed — CMF validation skipped")
        return errors

    try:
        tree = etree.parse(str(cmf_path))
    except Exception as e:
        errors.append(f"CMF XML parse error: {str(e)[:100]}")
        return errors

    # XSD schema validation
    xsd_errors = validate_cmf_schema(cmf_path)
    errors.extend(xsd_errors)

    root = tree.getroot()
    # CMF uses a namespace — find it dynamically
    nsmap = root.nsmap
    cmf_ns = nsmap.get(None) or nsmap.get("cmf", "")
    ns = {"cmf": cmf_ns} if cmf_ns else {}

    def find_all(tag):
        if ns:
            return root.findall(f"cmf:{tag}", ns)
        return root.findall(tag)

    # Count CMF elements
    cmf_classes = find_all("Class")
    cmf_obj_props = find_all("ObjectProperty")
    cmf_data_props = find_all("DataProperty")
    cmf_namespaces = find_all("Namespace")

    # Count augmentation records across all namespaces
    cmf_aug_count = 0
    for ns_el in cmf_namespaces:
        if cmf_ns:
            cmf_aug_count += len(ns_el.findall(f"cmf:AugmentationRecord", ns))
        else:
            cmf_aug_count += len(ns_el.findall("AugmentationRecord"))

    # Expected counts from matrix
    reuse_extend = sum(1 for m in mappings_list
                       if m.get("action") in ("reuse", "extend"))
    augment_count = sum(1 for m in mappings_list
                        if m.get("action") == "augment")

    # Check class count (augment actions don't produce CMF classes — they produce
    # augmentation records instead)
    if len(cmf_classes) < reuse_extend:
        errors.append(
            f"CMF has {len(cmf_classes)} classes, expected >= {reuse_extend} "
            f"(reuse + extend from matrix)"
        )

    # Check augmentation records
    if augment_count > 0 and cmf_aug_count == 0:
        errors.append(
            f"Matrix has {augment_count} augment actions but CMF has no "
            f"AugmentationRecords"
        )

    # Check that at least some properties exist
    total_props = len(cmf_obj_props) + len(cmf_data_props)
    if total_props == 0:
        errors.append("CMF has no properties (expected at least one)")

    return errors


def _hash_definition(definition):
    """Hash a definition string the same way collect_alignments does."""
    if definition is None:
        return None
    return hashlib.sha256(definition.encode("utf-8")).hexdigest()[:16]


def check_codebook_drift(mappings_list, catalog):
    """Check that target definitions in the matrix still match the catalog.

    Compares targetDefinitionHash values in the mapping matrix against
    current definitions in the reference catalog. Reports types and
    properties whose definitions have changed since the alignment was
    performed.

    Args:
        mappings_list: List of mapping entry dicts from the matrix.
        catalog: Reference catalog dict for the target ontology.

    Returns:
        List of error strings. Empty means no drift detected.
    """
    errors = []

    # Build lookup: qname -> definition from catalog types
    type_defs = {}
    for t in catalog.get("types", []):
        type_defs[t["qname"]] = t.get("definition")

    # Build lookup: qualifiedProperty -> definition from catalog propertyIndex
    prop_defs = {}
    for ns_data in catalog.get("propertyIndex", {}).values():
        for p in ns_data.get("properties", []):
            prop_defs[p["qualifiedProperty"]] = p.get("definition")

    for m in mappings_list:
        concept = m.get("sourceConcept", "")
        target_type = m.get("targetType")
        stored_hash = m.get("targetDefinitionHash")

        if target_type and stored_hash:
            current_def = type_defs.get(target_type)
            if current_def is None and target_type in type_defs:
                current_def = type_defs[target_type]
            current_hash = _hash_definition(current_def)

            if target_type not in type_defs:
                errors.append(
                    f"{concept}: target type {target_type} not found in catalog"
                )
            elif current_hash != stored_hash:
                errors.append(
                    f"{concept}: {target_type} definition changed "
                    f"(was {stored_hash}, now {current_hash})"
                )

        for p in m.get("propertyMappings", []):
            src_prop = p.get("sourceProperty", "")
            target_prop = p.get("targetProperty")
            prop_hash = p.get("targetDefinitionHash")

            if target_prop and prop_hash and target_prop != "[undecided]":
                current_prop_def = prop_defs.get(target_prop)
                current_prop_hash = _hash_definition(current_prop_def)

                if target_prop not in prop_defs:
                    errors.append(
                        f"{concept}/{src_prop}: target property {target_prop} "
                        f"not found in catalog"
                    )
                elif current_prop_hash != prop_hash:
                    errors.append(
                        f"{concept}/{src_prop}: {target_prop} definition "
                        f"changed (was {prop_hash}, now {current_prop_hash})"
                    )

    return errors


def extract_active_labels(mappings_list):
    """Extract active class labels from mapping matrix entries.

    Args:
        mappings_list: List of mapping entry dicts.

    Returns:
        Set of label strings (local names).
    """
    labels = set()
    for m in mappings_list:
        if m.get("action") in ("reuse", "extend", "augment"):
            concept = m.get("sourceConcept", "")
            label = concept.split(":")[-1] if ":" in concept else concept
            labels.add(label)
    return labels


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 7: Validate edge package")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    parser.add_argument("--package-dir", default=None, help="Edge package directory path")
    args = parser.parse_args()

    checks = []
    ctx = load_context(args.run_dir, args.package_dir)
    RUN_DIR = ctx.run_dir
    PKG = ctx.pkg_dir
    source = ctx.source
    target_ontology = ctx.target_ontology
    target_version = ctx.target_version

    # ── Check 1: Turtle syntax ──────────────────────────────────────────────
    print("\n  Check 1: Turtle syntax")
    from rdflib import Graph
    ttl_files = list(PKG.rglob("*.ttl"))
    parse_errors = []
    for f in ttl_files:
        try:
            g = Graph()
            g.parse(str(f), format="turtle")
        except Exception as e:
            parse_errors.append(f"{f.relative_to(PKG)}: {e}")

    add_check(checks, "turtle-syntax", len(parse_errors) == 0,
          f"{len(ttl_files)} files parsed, {len(parse_errors)} errors" +
          (": " + "; ".join(parse_errors) if parse_errors else ""))

    # ── Check 2: SHACL conformance ──────────────────────────────────────────
    print("\n  Check 2: SHACL conformance")
    try:
        from pyshacl import validate as shacl_validate

        # Load edge ontology
        data_g = Graph()
        for f in (PKG / "ontology").glob("*.ttl"):
            if "combined" not in f.name and "all" not in f.name:
                data_g.parse(str(f), format="turtle")

        # Load valid test fixture as data
        fixture_path = PKG / "tests" / "fixtures" / "valid" / "permit-lifecycle.ttl"
        if fixture_path.exists():
            data_g.parse(str(fixture_path), format="turtle")

        # Load vocab for concept class resolution
        for f in (PKG / "vocab").glob("*.ttl"):
            data_g.parse(str(f), format="turtle")

        # Load shapes
        shapes_g = Graph()
        for f in (PKG / "shapes").glob("*.ttl"):
            shapes_g.parse(str(f), format="turtle")

        conforms, results_graph, results_text = shacl_validate(
            data_g, shacl_graph=shapes_g, inference="none"
        )
        add_check(checks, "shacl-conformance", conforms,
              "Valid fixtures conform to shapes" if conforms else f"Violations: {results_text[:200]}")
    except ImportError:
        add_check(checks, "shacl-conformance", False, "pyshacl not installed — SHACL validation skipped")
    except Exception as e:
        add_check(checks, "shacl-conformance", False, f"SHACL check failed with error: {str(e)[:100]}")

    # ── Check 3: Mapping completeness ───────────────────────────────────────
    print("\n  Check 3: Mapping completeness")
    inv = json.loads((RUN_DIR / "concept-inventory.json").read_text(encoding="utf-8"))
    internal_classes = {c["qname"] for c in inv["classes"]}

    # Load mapping matrix from edge package
    matrix_path = PKG / "mappings" / "mapping-matrix.json"
    if matrix_path.exists():
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        if "mappings" in matrix:
            mapped_concepts = {e.get("sourceConcept", "") for e in matrix["mappings"]}
        else:
            mapped_concepts = set()
    else:
        # Fall back to mapper run matrix
        matrix = json.loads((RUN_DIR / "mapping-matrix.json").read_text(encoding="utf-8"))
        mapped_concepts = {e["sourceConcept"] for e in matrix["mappings"]}

    unmapped = internal_classes - mapped_concepts
    add_check(checks, "mapping-completeness", len(unmapped) == 0,
          f"{len(mapped_concepts)}/{len(internal_classes)} classes mapped" +
          (f", unmapped: {unmapped}" if unmapped else ""))

    # ── Check 4: Extension catalog vs matrix count ───────────────────────────
    print("\n  Check 4: Extension catalog count")
    ext_catalog_path = PKG / "extensions" / "extension-catalog.json"

    if ext_catalog_path.exists():
        catalog = json.loads(ext_catalog_path.read_text(encoding="utf-8"))
        ext_count = len(catalog.get("extensions", []))
    else:
        ext_count = 0

    # Count extend + augment actions in matrix (both produce extension catalog entries)
    mappings_list = matrix.get("mappings", matrix.get("entries", []))
    extension_actions = sum(1 for e in mappings_list if e.get("action") in ("extend", "augment"))

    add_check(checks, "extension-catalog-count", ext_count >= extension_actions,
          f"{ext_count} extensions cataloged, {extension_actions} extend+augment actions")

    # ── Check 5: Decision log vs mapped concept count ──────────────────────
    print("\n  Check 5: Decision log count")
    dec_log_path = PKG / "governance" / "decision-log.json"
    if not dec_log_path.exists():
        dec_log_path = RUN_DIR / "decision-log.json"

    dec_log = json.loads(dec_log_path.read_text(encoding="utf-8"))
    dec_count = len(dec_log.get("decisions", []))
    add_check(checks, "decision-log-count", dec_count >= len(mapped_concepts),
          f"{dec_count} decisions for {len(mapped_concepts)} mapped concepts")

    # ── Check 6: Cypher script validity ──────────────────────────────────
    print("\n  Check 6: Cypher script validity")
    kg_dir = PKG / "kg"
    cypher_files = list(kg_dir.rglob("*.cypher")) if kg_dir.exists() else []
    cypher_errors = []

    if not cypher_files:
        cypher_errors.append("No .cypher files found in kg/")
    for f in cypher_files:
        if f.name == "seed.cypher":
            continue  # seed data is optional; checked separately in Check 9
        content = f.read_text(encoding="utf-8").strip()
        non_comment_lines = [l for l in content.splitlines()
                             if l.strip() and not l.strip().startswith("//")]
        if not non_comment_lines:
            cypher_errors.append(f"{f.relative_to(PKG)}: empty or comment-only")

    add_check(checks, "cypher-validity", len(cypher_errors) == 0,
          f"{len(cypher_files)} files, {len(cypher_errors)} errors" +
          (": " + "; ".join(cypher_errors) if cypher_errors else ""))

    # ── Check 7: SPARQL syntax validation ─────────────────────────────────
    print("\n  Check 7: SPARQL syntax")
    sparql_files = list(kg_dir.rglob("*.rq")) if kg_dir.exists() else []
    sparql_errors = []

    if sparql_files:
        try:
            from rdflib.plugins.sparql import prepareQuery
            for f in sparql_files:
                content = f.read_text(encoding="utf-8")
                # Skip parameterized queries (contain $variable placeholders)
                if "$" in content:
                    continue
                try:
                    prepareQuery(content)
                except Exception as e:
                    sparql_errors.append(f"{f.relative_to(PKG)}: {str(e)[:80]}")
        except ImportError:
            sparql_errors.append("rdflib SPARQL parser not available")

    add_check(checks, "sparql-syntax", len(sparql_errors) == 0,
          f"{len(sparql_files)} files, {len(sparql_errors)} errors" +
          (": " + "; ".join(sparql_errors) if sparql_errors else ""))

    # ── Check 8: Schema labels match active classes ───────────────────────
    print("\n  Check 8: Schema-to-ontology consistency")
    schema_path = kg_dir / "neo4j" / "schema.cypher" if kg_dir.exists() else None
    active_labels = extract_active_labels(mappings_list)

    if schema_path and schema_path.exists():
        schema_errors = check_schema_labels(
            schema_path.read_text(encoding="utf-8"), active_labels
        )
    else:
        schema_errors = []

    add_check(checks, "schema-ontology-consistency",
          len(schema_errors) == 0,
          f"{len(active_labels)} active labels, {len(schema_errors)} mismatches" +
          (": " + "; ".join(schema_errors[:3]) if schema_errors else ""))

    # ── Check 9: Seed MATCH references match CREATEd nodes ───────────────
    print("\n  Check 9: Seed data consistency")
    seed_path = kg_dir / "neo4j" / "seed.cypher" if kg_dir.exists() else None

    if seed_path and seed_path.exists():
        created_labels, matched_labels, seed_errors = check_seed_consistency(
            seed_path.read_text(encoding="utf-8")
        )
        seed_detail = (f"{len(created_labels)} created, {len(matched_labels)} matched" +
                       (": " + "; ".join(seed_errors) if seed_errors else ""))
    else:
        seed_errors = []
        seed_detail = "No seed data"

    add_check(checks, "seed-data-consistency", len(seed_errors) == 0, seed_detail)

    # ── Check 10: Transform source types match mapping matrix ─────────────
    print("\n  Check 10: Transform-to-matrix consistency")
    transform_path = kg_dir / "import" / "internal-to-edge.json" if kg_dir.exists() else None
    transform_errors = []

    active_concepts = {m.get("sourceConcept") for m in mappings_list
                       if m.get("action") in ("reuse", "extend", "augment")}

    if transform_path and transform_path.exists():
        try:
            transforms_data = json.loads(transform_path.read_text(encoding="utf-8"))
            transform_errors = check_transform_sources(transforms_data, active_concepts)
        except json.JSONDecodeError as e:
            transform_errors.append(f"Invalid JSON: {e}")
    elif kg_dir and kg_dir.exists():
        transform_errors.append("internal-to-edge.json not found")

    # Also check loader-config.json is valid JSON
    loader_path = kg_dir / "import" / "loader-config.json" if kg_dir.exists() else None
    if loader_path and loader_path.exists():
        try:
            json.loads(loader_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            transform_errors.append(f"loader-config.json invalid JSON: {e}")
    elif kg_dir and kg_dir.exists():
        transform_errors.append("loader-config.json not found")

    add_check(checks, "transform-matrix-consistency", len(transform_errors) == 0,
          f"{len(active_concepts)} active concepts" +
          (f", {len(transform_errors)} errors: " + "; ".join(transform_errors[:3])
           if transform_errors else ", all transforms match"))

    # ── Check 11: CMF consistency (NIEM only) ─────────────────────────────
    if target_ontology == "niem":
        print("\n  Check 11: CMF consistency")
        cmf_dir = PKG / "cmf"
        cmf_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf" if cmf_dir.exists() else None

        if cmf_path and cmf_path.exists():
            cmf_errors = check_cmf_consistency(cmf_path, mappings_list)
        elif cmf_dir.exists():
            cmf_errors = [f"CMF file not found: {ctx.cmf_model_stem}.cmf"]
        else:
            cmf_errors = ["cmf/ directory not found"]

        add_check(checks, "cmf-consistency", len(cmf_errors) == 0,
              "CMF matches matrix" if not cmf_errors else "; ".join(cmf_errors[:3]))

    # ── Check 12: Cross-boundary codebook drift ───────────────────────────
    print("\n  Check 12: Codebook drift")
    try:
        from ontology_mapper.build_strategy_reports import resolve_catalog_path
        catalog_path = resolve_catalog_path(target_ontology, target_version)
        if catalog_path and catalog_path.exists():
            ref_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            drift_errors = check_codebook_drift(mappings_list, ref_catalog)
            add_check(checks, "codebook-drift", len(drift_errors) == 0,
                  f"no drift detected" if not drift_errors
                  else f"{len(drift_errors)} drifted: " + "; ".join(drift_errors[:3]))
        else:
            add_check(checks, "codebook-drift", True,
                  f"no catalog for {target_ontology} {target_version} — skipped")
    except Exception as e:
        add_check(checks, "codebook-drift", False,
              f"codebook drift check failed: {str(e)[:100]}")

    # ── Save validation report ──────────────────────────────────────────────
    all_passed = all(c["status"] == "pass" for c in checks)
    report = {
        "stage": "7",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "allPassed": all_passed,
        "checkCount": len(checks),
        "passCount": sum(1 for c in checks if c["status"] == "pass"),
        "failCount": sum(1 for c in checks if c["status"] == "FAIL"),
        "checks": checks,
    }

    out_path = RUN_DIR / "validation-report.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\n  {'ALL CHECKS PASSED' if all_passed else 'SOME CHECKS FAILED'}")
    print(f"  Report: {out_path}")


if __name__ == "__main__":
    main()
