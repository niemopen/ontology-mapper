#!/usr/bin/env python3
"""Stage 6b: Package Edge Artifacts — assemble non-OWL artifacts into the edge package.

After Stage 6a (generate_edge_ontology.py) produces the OWL/TTL modules, this tool
copies and assembles the remaining artifacts into the edge package:

  - mappings/  (matrix, alignment report, extension justifications)
  - extensions/  (extension catalog)
  - governance/  (decision log, generation audit, quality gate report,
                   coherence manifest)
  - package-manifest.json  (with accurate stats)
  - README.md

This is a deterministic tool — no semantic reasoning required.

Usage:
    om-package-artifacts                  # uses mapper state
    om-package-artifacts <run_dir> <pkg>  # explicit paths
"""

import json
import shutil
import sys
from pathlib import Path
from ontology_mapper.cmf_reference import CMF_OMITTED_REASON, reference_cmf_installed
from ontology_mapper.run_dir_utils import utc_stamp

from ontology_mapper.pipeline_context import load_context
from ontology_mapper.build_strategy_reports import build_class_properties
from ontology_mapper.generation_utils import (
    created_property_is_declared,
    component_iri, created_property_qname, edge_class_name,
    property_qname_resolver, source_declared_properties,
    source_namespace_bindings, source_prefix,
)


def _load_json_optional(path):
    """Load a JSON file, returning None if it doesn't exist."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def copy_if_exists(src, dst, label):
    """Copy a file if the source exists. Returns True if copied."""
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        print(f"  [+] {label}: {dst.relative_to(dst.parent.parent.parent) if len(dst.parts) > 3 else dst.name}")
        return True
    else:
        print(f"  [-] {label}: source not found ({src.name})")
        return False


def copy_alignment_report(run_dir, pkg):
    """Copy alignment report into the edge package."""
    mappings_dir = pkg / "mappings"
    mappings_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    if copy_if_exists(run_dir / "alignment-report.json",
                      mappings_dir / "alignment-report.json", "alignment-report"):
        copied += 1
    return copied


def build_extension_justifications(matrix, target_ontology, target_version):
    """Generate extension-justifications.md from the mapping matrix."""
    extensions = [m for m in matrix["mappings"] if m.get("action") in ("extend", "augment")]

    if not extensions:
        return "# Extension Justifications\n\nNo extensions required.\n"

    now = utc_stamp()
    lines = [
        "# Extension Justifications",
        f"",
        f"Generated: {now}",
        f"Target Ontology: {target_ontology} {target_version}",
        f"Total extensions: {len(extensions)}",
        "",
    ]

    for ext in sorted(extensions, key=lambda e: e["sourceConcept"]):
        concept = ext["sourceConcept"]
        # Extract short name from qname
        short_name = concept.split(":")[-1] if ":" in concept else concept

        lines.append(f"## {short_name} ({concept})")
        lines.append(f"")
        lines.append(f"- **Action**: {ext['action'].capitalize()}")
        lines.append(f"- **Nearest target type**: {ext.get('targetType', 'none')}")
        rationale = ext.get("notes") or ext.get("rationale", "No rationale recorded.")
        lines.append(f"**Rationale**: {rationale}")
        lines.append(f"")

    return "\n".join(lines) + "\n"


def build_extension_catalog(matrix, ctx, inventory, target_ns_map):
    """Inventory accepted new properties using the generators' term identities."""
    classes = {c["qname"]: c for c in inventory["classes"]}
    resolve_property = property_qname_resolver(inventory)
    bindings = source_namespace_bindings(inventory, target_ns_map, ctx.edge_prefix)
    namespaces = {**target_ns_map, ctx.edge_prefix.rstrip(":"): ctx.edge_namespace,
                  "ext": ctx.extension_namespace}
    namespaces.update({prefix: uri for prefix, uri in bindings.values()})
    primary = source_prefix(inventory)
    # The same predicate Stage 3/4 built the decisions from: a property
    # the source declares only through a SHACL shape is a property of
    # that class, and the emitters reference it.
    class_properties = build_class_properties(inventory)
    declared_properties = {q for props in class_properties.values() for q in props}
    minted_properties = source_declared_properties(inventory)
    unresolved = []
    extensions = []
    for m in matrix["mappings"]:
        if m.get("action") not in ("extend", "augment") or m.get("reviewStatus") != "accepted":
            continue

        concept = m["sourceConcept"]
        if concept not in classes:
            # Same answer as an unqualifiable decision below: the catalog
            # cannot write a source IRI for a concept this run's inventory
            # does not carry, and a bare KeyError names no mapping.
            unresolved.append(f"  - {concept}: not in this run's concept inventory")
            continue
        short_name = concept.split(":")[-1] if ":" in concept else concept

        if m["action"] == "augment":
            ext_name = m.get("augmentationType", f"{short_name}AugmentationType")
            base = m.get("augmentsType") or m.get("targetType")
        else:
            ext_name = edge_class_name(concept)
            base = m.get("baseType") or m.get("targetType")

        properties = set()
        for decision in m.get("propertyMappings") or []:
            if not created_property_is_declared(decision):
                # One question, asked once: the emitters mint a term for any
                # decision with no accepted reuse target, whatever its action
                # says. Testing the action as well omitted terms they declare
                # (a pending reuse, a `human-must-decide`).
                continue
            recorded = resolve_property(decision["sourceProperty"], concept)
            if declared_properties and recorded not in class_properties.get(concept, set()):
                # The OWL and CMF emitters walk the inventory class by
                # class, so a decision on a property this concept does not
                # carry produces no term on its extension; listing one here
                # would make the catalog claim a term the model never
                # declares there. Membership anywhere in the inventory was
                # the wrong question: another class's property passed it.
                where = ("belongs to another class in this run's concept inventory"
                         if recorded in declared_properties
                         else "is not in this run's concept inventory")
                unresolved.append(
                    f"  - {concept}: {decision['sourceProperty']} {where}")
                continue
            if recorded in declared_properties and recorded not in minted_properties:
                # Named only by a shape: the emitters reference it as the
                # term it is and mint nothing, so it adds nothing here.
                continue
            qname = created_property_qname(
                recorded, m["action"], primary, bindings, ctx.edge_prefix)
            prefix, name = qname.split(":", 1)
            # This is the only artifact built by walking the decisions
            # rather than the inventory, so it alone must qualify a
            # recorded name the resolver could not resolve
            # (`property_qname_resolver` returns an unknown name
            # unchanged). Such a prefix binds to no namespace: the
            # catalog cannot invent an IRI for it, and the OWL and CMF
            # emitters never wrote one, so name the decision rather than
            # failing on the lookup.
            namespace = namespaces.get(prefix)
            if namespace is None:
                unresolved.append(
                    f"  - {concept}: {decision['sourceProperty']} "
                    f"(prefix '{prefix}' is bound to no namespace)")
                continue
            properties.add(component_iri(namespace, name))

        extensions.append({
            "extensionIRI": component_iri(ctx.extension_namespace, ext_name),
            "name": ext_name,
            "baseType": base,
            "definition": m.get("notes", ""),
            "properties": sorted(properties),
            "justification": m.get("notes") or m.get("rationale", ""),
            "sourceConceptIRI": classes[concept]["iri"],
            "mappingEntryRef": concept,
        })

    # After the loop, not inside it: the count is the run's, and a
    # reviewer who fixes the first offender must not be refused again by
    # the second.
    if unresolved:
        raise ValueError(
            f"{len(unresolved)} accepted mapping(s) name something this run "
            f"cannot qualify; reopen review:\n"
            + "\n".join(unresolved))

    return {"extensions": sorted(extensions, key=lambda e: e["extensionIRI"])}


def build_package_manifest(ctx, matrix):
    """Build or update package-manifest.json with accurate stats."""
    summary = matrix.get("summary", {})
    action_counts = summary.get("actionCounts", {})

    # Use summary action counts, falling back to counting from mappings
    mappings = matrix.get("mappings", [])
    reuse_count = action_counts.get("reuse", sum(1 for m in mappings if m.get("action") == "reuse"))
    extend_count = action_counts.get("extend", sum(1 for m in mappings if m.get("action") == "extend"))
    augment_count = action_counts.get("augment", sum(1 for m in mappings if m.get("action") == "augment"))
    excluded_count = action_counts.get("exclude", sum(1 for m in mappings if m.get("action") == "exclude"))
    total = reuse_count + extend_count + augment_count + excluded_count

    manifest = {
        "name": ctx.edge_package_name,
        "version": "0.1.0",
        "description": ctx.description,
        "sourcePackage": ctx.agency_package_name,
        "targetOntology": ctx.target_ontology,
        "targetVersion": ctx.target_version,
        "targetDomains": [],
        "targetGraphPlatforms": ["neo4j", "rdf"],
        "generatedBy": "ontology-mapper",
        "generatedAt": utc_stamp(),
        "extensionNamespace": ctx.extension_namespace,
        "edgeNamespace": ctx.edge_namespace,
        "stats": {
            "totalConcepts": total,
            "targetMapped": reuse_count,
            "targetExtended": extend_count,
            "targetAugmented": augment_count,
            "excluded": excluded_count,
        },
    }
    if not reference_cmf_installed(ctx.target_ontology, ctx.target_version):
        manifest["omittedArtifacts"] = {"cmf/": CMF_OMITTED_REASON}

    return manifest


def build_readme(ctx, matrix):
    """Generate a README.md for the edge package."""
    summary = matrix.get("summary", {})
    action_counts = summary.get("actionCounts", {})
    mappings = matrix.get("mappings", [])
    total = summary.get("totalConcepts", len(mappings))
    reuse = action_counts.get("reuse", sum(1 for m in mappings if m.get("action") == "reuse"))
    extend = action_counts.get("extend", sum(1 for m in mappings if m.get("action") == "extend"))
    augment = action_counts.get("augment", sum(1 for m in mappings if m.get("action") == "augment"))
    cmf_line = ("- `cmf/` - Canonical Model Format exchange artifacts"
                if reference_cmf_installed(ctx.target_ontology, ctx.target_version)
                else f"- No `cmf/`: {CMF_OMITTED_REASON}")

    return f"""# {ctx.label_prefix} Edge Package

{ctx.description.capitalize()}.

## Overview

| Metric | Value |
|--------|-------|
| Organization | {ctx.organization} |
| Source | {ctx.source} |
| Target Ontology | {ctx.target_ontology} {ctx.target_version} |
| Total Concepts | {total} |
| Reuse | {reuse} |
| Extend | {extend} |
| Augment | {augment} |

## Directory Structure

- `ontology/` - OWL/TTL edge ontology modules
{cmf_line}
- `mappings/` - Internal-to-target-ontology alignment artifacts
- `extensions/` - Extension namespace definitions
- `shapes/` - SHACL validation constraints
- `vocab/` - Controlled vocabularies
- `governance/` - Decision log, audit trail, version metadata
- `tests/` - Validation fixtures
- `contracts/` - Agent-facing integration contracts
- `kg/` - Knowledge graph deployment artifacts
- `schemas/` - Exchange format schemas

## Usage

See `mappings/mapping-matrix.json` for the complete mapping of internal
concepts to target ontology types. See `governance/decision-log.json` for the
rationale behind each mapping decision.

## Generated By

OntologyMapper v1.0
"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 6b: Package edge artifacts")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    parser.add_argument("--package-dir", default=None, help="Edge package directory path")
    args = parser.parse_args()

    ctx = load_context(args.run_dir, args.package_dir)

    print(f"\n  Stage 6b: Package Edge Artifacts")
    print(f"  Run directory: {ctx.run_dir}")
    print(f"  Edge package:  {ctx.pkg_dir}")
    print()

    run_dir = ctx.run_dir
    pkg = ctx.pkg_dir

    # Load mapping matrix (required)
    matrix_path = run_dir / "mapping-matrix.json"
    if not matrix_path.exists():
        print(f"  ERROR: mapping-matrix.json not found in {run_dir}")
        sys.exit(1)
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))

    artifacts_written = 0

    # ── 1. Mapping matrix -> edge package ─────────────────────────────────
    print("  Mappings:")
    dst = pkg / "mappings" / "mapping-matrix.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(matrix_path), str(dst))
    print(f"  [+] mapping-matrix.json")
    artifacts_written += 1

    # ── 2. Alignment report ──────────────────────────────────────────────
    print("\n  Alignment Report:")
    artifacts_written += copy_alignment_report(run_dir, pkg)

    # ── 4. Extension justifications ───────────────────────────────────────
    print("\n  Extensions:")
    ext_just = build_extension_justifications(matrix, ctx.target_ontology, ctx.target_version)
    ext_just_path = pkg / "mappings" / "extension-justifications.md"
    ext_just_path.write_text(ext_just, encoding="utf-8")
    print(f"  [+] extension-justifications.md ({sum(1 for m in matrix['mappings'] if m.get('action') in ('extend', 'augment'))} extensions)")
    artifacts_written += 1

    # ── 5. Extension catalog ──────────────────────────────────────────────
    from ontology_mapper.build_strategy_reports import resolve_catalog_path
    inventory = json.loads((run_dir / "concept-inventory.json").read_text(encoding="utf-8"))
    # One home for "where is this run's reference catalog": the resolver
    # the strategy reports, the review cascade and the generators use, so
    # an install layout it handles is not one this path misses.
    catalog_path = resolve_catalog_path(ctx.target_ontology, ctx.target_version)
    if catalog_path is None:
        raise ValueError(f"No reference catalog for {ctx.target_ontology} "
                         f"{ctx.target_version}")
    target_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    ext_catalog = build_extension_catalog(matrix, ctx, inventory, target_catalog.get("namespaces", {}))
    ext_catalog_path = pkg / "extensions" / "extension-catalog.json"
    ext_catalog_path.parent.mkdir(parents=True, exist_ok=True)
    ext_catalog_path.write_text(json.dumps(ext_catalog, indent=2) + "\n", encoding="utf-8")
    print(f"  [+] extension-catalog.json ({len(ext_catalog['extensions'])} entries)")
    artifacts_written += 1

    # ── 6. Governance artifacts ───────────────────────────────────────────
    print("\n  Governance:")
    gov_dir = pkg / "governance"
    gov_dir.mkdir(parents=True, exist_ok=True)

    gov_artifacts = {
        "decision-log.json": "Decision log",
        "generation-audit.json": "Generation audit",
        "quality-gate-report.json": "Quality gate report",
    }
    for filename, label in gov_artifacts.items():
        if copy_if_exists(run_dir / filename, gov_dir / filename, label):
            artifacts_written += 1

    # ── 7. Coherence manifest ────────────────────────────────────────────
    from ontology_mapper.build_coherence_manifest import build_coherence_manifest

    entropy_summary = _load_json_optional(run_dir / "entropy-summary.json")
    residual_entropy = _load_json_optional(run_dir / "residual-entropy.json")
    coherence = build_coherence_manifest(matrix, entropy_summary, residual_entropy)
    coherence_path = gov_dir / "coherence-manifest.json"
    coherence_path.write_text(json.dumps(coherence, indent=2) + "\n", encoding="utf-8")
    entropy_label = f", entropy: {coherence['entropy']['preTotal']:.1f} pre / {coherence['entropy']['residualTotal']:.1f} residual" if coherence.get("entropy") and "residualTotal" in coherence["entropy"] else ""
    print(f"  [+] coherence-manifest.json ({coherence['rotationSummary']['totalConcepts']} concepts{entropy_label})")
    artifacts_written += 1

    # ── 8. Package manifest ───────────────────────────────────────────────
    print("\n  Package metadata:")
    manifest = build_package_manifest(ctx, matrix)
    manifest_path = pkg / "package-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  [+] package-manifest.json (total: {manifest['stats']['totalConcepts']})")
    artifacts_written += 1

    # ── 8. README ─────────────────────────────────────────────────────────
    readme = build_readme(ctx, matrix)
    readme_path = pkg / "README.md"
    readme_path.write_text(readme, encoding="utf-8")
    print(f"  [+] README.md")
    artifacts_written += 1

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n  Done: {artifacts_written} artifacts written to {pkg}")


if __name__ == "__main__":
    main()
