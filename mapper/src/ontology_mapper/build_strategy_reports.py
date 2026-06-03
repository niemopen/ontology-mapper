#!/usr/bin/env python3
"""Stage 3: Prepare alignment workspace for semantic processing.

Produces two artifacts for the evaluation step:
  - catalog-summary.json (or locates existing one in specs/)
  - source-concepts.json (per-run, from concept inventory)

The evaluator reads both files, performs semantic alignment against
the target ontology reference catalog, and writes the alignment report.

Inputs:
  - concept-inventory.json (from Stage 2)
  - specs/{ontology}_reference_catalog_{version}.json (target ontology reference)
  - specs/{ontology}_catalog_summary_{version}.json (generated alongside catalog)
  - .mapper-runs/{run_id}/.mapper-state.json (run configuration)
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# ─── Configuration ────────────────────────────────────────────────────────

from ontology_mapper.pipeline_context import load_context
from ontology_mapper.run_dir_utils import resolve_specs_dir
SPECS_DIR = resolve_specs_dir()


def strip_prefix(qname):
    """Strip namespace prefix from qname: 'dbpi:Person' -> 'Person'."""
    return qname.split(":", 1)[-1] if ":" in qname else qname


# ─── Data Loading ─────────────────────────────────────────────────────────

def resolve_catalog_path(target_ontology, target_version):
    """Find the reference catalog for the given ontology and version."""
    versioned = SPECS_DIR / f"{target_ontology}_reference_catalog_{target_version}.json"
    if versioned.exists():
        return versioned
    return None


def load_stage_data(ctx, catalog_path=None):
    """Load concept inventory and reference catalog for this stage."""
    inv = json.loads(
        (ctx.run_dir / "concept-inventory.json").read_text(encoding="utf-8")
    )

    if catalog_path is None:
        catalog_path = resolve_catalog_path(ctx.target_ontology, ctx.target_version)
        if catalog_path is None:
            raise FileNotFoundError(
                f"No reference catalog found for {ctx.target_ontology} {ctx.target_version}. "
                f"Generate one first (NIEM: om-generate-catalog, OWL: om-generate-owl-catalog)"
            )
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))

    return inv, catalog


def build_class_properties(inv):
    """Build mapping from class qname -> set of property local names.

    Uses both explicit rdfs:domain and SHACL shape paths.
    """
    class_props = defaultdict(set)

    # From explicit domains in object properties
    for prop in inv.get("objectProperties", []):
        local = strip_prefix(prop["qname"])
        for dom in prop.get("domain", []):
            class_props[dom].add(local)

    # From explicit domains in datatype properties
    for prop in inv.get("datatypeProperties", []):
        local = strip_prefix(prop["qname"])
        for dom in prop.get("domain", []):
            class_props[dom].add(local)

    # From SHACL shapes (properties constrained on a target class)
    for shape in inv.get("shaclShapes", []):
        target = shape.get("targetClass", "")
        for sp in shape.get("properties", []):
            path = sp.get("path", "")
            if path:
                local = strip_prefix(path)
                class_props[target].add(local)

    return dict(class_props)


def build_source_property_defs(inv, class_properties):
    """Build lookup: {class_qname: {prop_local_name: {definition, range}}}.

    Combines property data from objectProperties, datatypeProperties,
    and shaclShapes to create a per-class, per-property definition map.
    """
    # Build global property lookup by local name
    prop_lookup = {}  # local_name -> {definition, range}
    for prop in inv.get("objectProperties", []):
        local = strip_prefix(prop.get("qname", ""))
        prop_lookup[local] = {
            "definition": prop.get("comment", ""),
            "range": prop.get("range", []),
        }
    for prop in inv.get("datatypeProperties", []):
        local = strip_prefix(prop.get("qname", ""))
        prop_lookup[local] = {
            "definition": prop.get("comment", ""),
            "range": prop.get("range", []),
        }

    # Map each class's properties to their definitions
    result = {}
    for class_qname, prop_names in class_properties.items():
        class_defs = {}
        for pname in prop_names:
            if pname in prop_lookup:
                class_defs[pname] = prop_lookup[pname]
        if class_defs:
            result[class_qname] = class_defs
    return result



# ─── Source Concept Summary ───────────────────────────────────────────────

def build_source_concept_summary(inv):
    """Build a structured summary of source concepts for the evaluation step.

    Extracts classes with their definitions, properties, and superclasses.
    Returns a list of concept dicts.
    """
    class_props = build_class_properties(inv)
    prop_defs = build_source_property_defs(inv, class_props)

    concepts = []
    for cls in inv.get("classes", []):
        qname = cls["qname"]
        local_name = strip_prefix(qname)
        definition = cls.get("comment", "") or cls.get("definition", "") or ""

        # Build property list with definitions
        properties = []
        prop_names = sorted(class_props.get(qname, set()))
        class_defs = prop_defs.get(qname, {})
        for pname in prop_names:
            pd = class_defs.get(pname, {})
            properties.append({
                "name": pname,
                "definition": pd.get("definition", ""),
                "range": pd.get("range", []),
            })

        concepts.append({
            "qname": qname,
            "localName": local_name,
            "definition": definition,
            "properties": properties,
            "propertyCount": len(properties),
            "superClasses": cls.get("subClassOf", []),
        })

    return concepts


# ─── Catalog Summary ─────────────────────────────────────────────────────

def resolve_catalog_summary_path(target_ontology, target_version):
    """Find the catalog summary for the given ontology and version."""
    summary_path = SPECS_DIR / f"{target_ontology}_catalog_summary_{target_version}.json"
    if summary_path.exists():
        return summary_path
    return None


def generate_catalog_summary_from_catalog(catalog, target_ontology, target_version):
    """Generate catalog summary from the loaded catalog when no pre-built summary exists."""
    from ontology_mapper.generate_niem_catalog import build_catalog_summary

    # Build ns_map from catalog namespaces
    ns_map = {}
    for prefix, uri in catalog.get("namespaces", {}).items():
        ns_map[prefix] = {"uri": uri}

    summary = build_catalog_summary(catalog["types"], ns_map)
    total_types = sum(len(ns_data["types"]) for ns_data in summary.values())

    summary_doc = {
        "version": target_version,
        "description": (
            f"{target_ontology} {target_version} type summary for semantic processing. "
            f"Auto-generated from reference catalog."
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "namespaces": len(summary),
            "totalTypes": total_types,
        },
        "namespaces": summary,
    }

    summary_path = SPECS_DIR / f"{target_ontology}_catalog_summary_{target_version}.json"

    # Atomic write: temp file + os.replace() so concurrent runs producing
    # the same summary won't corrupt the file.
    content = json.dumps(summary_doc, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=SPECS_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, summary_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return summary_path


# ─── Alignment Report ────────────────────────────────────────────────────

def save_alignment_report(run_dir, entries, target_ontology, target_version, actions, type_patterns):
    """Save the alignment report as JSON.

    The alignment report schema supports both:
    - Placeholder reports (matchingMethod: "pending-evaluation") written by this tool
    - Completed reports (matchingMethod: "semantic") written by the evaluator

    The actions dict lists the valid actions for this target ontology,
    read from the reference catalog. The evaluator uses this as a
    multiple-choice list when deciding how each source concept maps.

    The type_patterns dict describes the structural patterns in the target
    ontology. The evaluator reads these as context during semantic alignment.
    """
    # Summary stats
    total = len(entries)
    by_action = {}
    for e in entries:
        action = e.get("action", "pending")
        by_action[action] = by_action.get(action, 0) + 1

    report = {
        "stage": "3",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "targetOntology": target_ontology,
        "targetVersion": target_version,
        "matchingMethod": "pending-evaluation",
        "actions": actions,
        "typePatterns": type_patterns,
        "summary": {
            "totalConcepts": total,
            **by_action,
        },
        "entries": entries,
    }

    out_path = run_dir / "alignment-report.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return out_path, report["summary"]


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 3: Build alignment strategy reports")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    parser.add_argument("--catalog", default=None, help="Path to reference catalog JSON")
    args = parser.parse_args()

    ctx = load_context(args.run_dir)
    inv, catalog = load_stage_data(ctx, args.catalog)
    run_dir = ctx.run_dir
    target_ontology = ctx.target_ontology
    target_version = ctx.target_version

    target_types = catalog["types"]
    classes = inv["classes"]

    print(f"\nStage 3: Prepare alignment workspace for semantic processing")
    print(f"  Run: {run_dir}")
    print(f"  Target: {target_ontology} {target_version}")
    print(f"  Source classes: {len(classes)}")
    print(f"  Target reference types (full catalog): {len(target_types)}")

    # Step 1: Locate or generate catalog summary
    summary_path = resolve_catalog_summary_path(target_ontology, target_version)
    if summary_path:
        print(f"\n  Catalog summary: {summary_path} (pre-built)")
    else:
        print(f"\n  Catalog summary not found — generating from catalog...")
        summary_path = generate_catalog_summary_from_catalog(catalog, target_ontology, target_version)
        print(f"  Catalog summary: {summary_path} (generated)")

    # Load summary stats for display
    summary_doc = json.loads(summary_path.read_text(encoding="utf-8"))
    ns_count = summary_doc["stats"]["namespaces"]
    stats = summary_doc["stats"]
    type_count = stats.get("totalTypes") or stats.get("types", 0)
    print(f"    {ns_count} namespaces, {type_count} types")

    # Step 2: Build source concept summary
    source_concepts = build_source_concept_summary(inv)
    source_path = run_dir / "source-concepts.json"
    source_doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalConcepts": len(source_concepts),
        "concepts": source_concepts,
    }
    source_path.write_text(
        json.dumps(source_doc, indent=2) + "\n", encoding="utf-8"
    )
    props_total = sum(c["propertyCount"] for c in source_concepts)
    print(f"\n  Source concepts: {source_path}")
    print(f"    {len(source_concepts)} concepts, {props_total} total properties")

    # Step 3: Save placeholder alignment report
    actions = catalog.get("actions", {})
    type_patterns = catalog.get("typePatterns", {})
    if not actions:
        print(f"\n  WARNING: Reference catalog has no 'actions' section.")
        print(f"  Regenerate the catalog to include valid actions for {target_ontology}.")

    placeholder_entries = []
    for cls in classes:
        placeholder_entries.append({
            "sourceConcept": cls["qname"],
            "sourceDefinition": cls.get("comment", "") or cls.get("definition", "") or "",
            "action": "pending",
            "targetType": None,
            "targetDefinition": None,
            "rationale": None,
        })

    out_path, summary = save_alignment_report(
        run_dir, placeholder_entries, target_ontology, target_version, actions, type_patterns
    )
    print(f"\n  Alignment report: {out_path} (placeholder — awaiting evaluation)")
    print(f"  Total concepts: {summary['totalConcepts']}")
    print(f"\n  Ready for semantic processing.")
    if actions:
        print(f"  Valid actions for {target_ontology}: {', '.join(actions.keys())}")


if __name__ == "__main__":
    main()
