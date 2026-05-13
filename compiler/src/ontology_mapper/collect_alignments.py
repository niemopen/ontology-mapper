#!/usr/bin/env python3
"""Collect evaluations and assemble the alignment report.

After ``om-batch-search`` writes per-type and per-property files and the
evaluator processes each one, this tool:

1. Reads type files from ``{run_dir}/search-results/types/``
2. Reads property files from ``{run_dir}/search-results/properties/``
3. Validates that all have ``status == "evaluated"``
4. Reassembles per-concept evaluations (type + its properties)
5. Calls ``resolve_alignment()`` on each to add actions and scaffolding
6. Writes the completed ``alignment-report.json``

Usage:
    om-collect-alignments --run-dir {run_dir} [--allow-pending]
"""

import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ontology_mapper.pipeline_context import load_context
from ontology_mapper.build_strategy_reports import resolve_catalog_path
from ontology_mapper.ontology_specific import resolve_alignment


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------

def _load_dir(directory: Path) -> list[tuple[str, dict]]:
    """Read all JSON files from a directory, sorted by filename."""
    if not directory.is_dir():
        return []
    results = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        results.append((path.name, doc))
    return results


def load_search_results(run_dir: Path) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """Read type and property files from ``{run_dir}/search-results/``.

    Returns ``(type_results, property_results)`` — each a sorted list of
    ``(filename, document)`` tuples.

    Raises FileNotFoundError if search-results/ does not exist.
    """
    results_dir = run_dir / "search-results"
    if not results_dir.is_dir():
        raise FileNotFoundError(
            f"search-results/ not found in {run_dir}. "
            "Run 'om-batch-search' first."
        )

    types = _load_dir(results_dir / "types")
    properties = _load_dir(results_dir / "properties")
    return types, properties


def validate_evaluations(
    results: list[tuple[str, dict]],
) -> tuple[list[tuple[str, dict]], list[str]]:
    """Partition results into evaluated and pending.

    Returns ``(evaluated, pending_names)``.
    """
    evaluated = []
    pending_names = []
    for filename, doc in results:
        if doc.get("status") == "evaluated":
            evaluated.append((filename, doc))
        else:
            pending_names.append(filename)
    return evaluated, pending_names


# ---------------------------------------------------------------------------
# Reassembly
# ---------------------------------------------------------------------------

def _build_id_to_qname(candidates: list[dict]) -> dict[str, str]:
    """Build display-id → qname lookup from a candidate list.

    When the catalog has labels (e.g. SALI), candidates carry
    id=label and qname=real-identifier. For NIEM, id already equals
    qname. Returns a mapping so evaluations can be resolved to qnames.
    """
    return {c["id"]: c.get("qname", c["id"]) for c in candidates}


_LABEL_FIELDS = {"targetType": "targetTypeLabel", "targetProperty": "targetPropertyLabel"}


def _resolve_target_qname(evaluation: dict, field: str, id_to_qname: dict):
    """Replace a display-id target field with its qname, preserving the label."""
    display_id = evaluation.get(field)
    if display_id is None or display_id == "[undecided]":
        return
    qname = id_to_qname.get(display_id, display_id)
    if qname != display_id:
        evaluation[field] = qname
        evaluation[_LABEL_FIELDS[field]] = display_id


def reassemble_evaluations(
    type_evaluated: list[tuple[str, dict]],
    prop_evaluated: list[tuple[str, dict]],
) -> list[dict]:
    """Reassemble per-concept evaluations from separate type and property files.

    Groups property evaluations by ``source.parentType`` and attaches them
    to the matching type evaluation's ``properties`` list. Resolves
    display ids (labels) back to qnames using each file's candidate list.

    Returns a list of combined evaluation dicts ready for ``resolve_alignment()``.
    """
    # Index property evaluations by parent type qname,
    # resolving targetProperty display ids to qnames
    props_by_parent: dict[str, list[dict]] = defaultdict(list)
    for _filename, doc in prop_evaluated:
        parent = doc["source"]["parentType"]
        ev = doc["evaluation"]
        id_map = _build_id_to_qname(doc.get("candidates", []))
        _resolve_target_qname(ev, "targetProperty", id_map)
        props_by_parent[parent].append(ev)

    combined = []
    for _filename, doc in type_evaluated:
        ev = doc["evaluation"]
        type_qname = doc["source"]["qname"]
        id_map = _build_id_to_qname(doc.get("candidates", []))
        _resolve_target_qname(ev, "targetType", id_map)
        ev["properties"] = props_by_parent.get(type_qname, [])
        combined.append(ev)

    return combined


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _hash_definition(definition):
    """Hash a target definition for codebook version fingerprinting.

    Returns a 16-character hex string (64-bit SHA-256 prefix), or None
    if the definition is None.
    """
    if definition is None:
        return None
    return hashlib.sha256(definition.encode("utf-8")).hexdigest()[:16]


def _build_catalog_def_lookups(catalog):
    """Build lookup dicts from catalog for canonical definition hashing."""
    type_defs = {t["qname"]: t.get("definition") for t in catalog.get("types", [])}
    prop_defs = {}
    for ns_data in catalog.get("propertyIndex", {}).values():
        for p in ns_data.get("properties", []):
            prop_defs[p["qualifiedProperty"]] = p.get("definition")
    return type_defs, prop_defs


def _add_definition_hashes(entry, type_defs, prop_defs):
    """Add targetDefinitionHash to an alignment entry and its properties.

    Hashes the canonical catalog definition (not the enriched definition from
    search results) so that Check 12 can compare against the same source.
    Falls back to the entry's own targetDefinition if the catalog lookup fails.
    """
    target_type = entry.get("targetType")
    canonical_type_def = type_defs.get(target_type) if target_type else None
    entry["targetDefinitionHash"] = _hash_definition(
        canonical_type_def if canonical_type_def is not None else entry.get("targetDefinition")
    )
    for prop in entry.get("properties", []):
        target_prop = prop.get("targetProperty")
        canonical_prop_def = prop_defs.get(target_prop) if target_prop else None
        prop["targetDefinitionHash"] = _hash_definition(
            canonical_prop_def if canonical_prop_def is not None else prop.get("targetDefinition")
        )


def collect_and_resolve(
    evaluations: list[dict],
    target_ontology: str,
    catalog: dict,
) -> list[dict]:
    """Call resolve_alignment() on each reassembled evaluation.

    Returns a list of fully resolved alignment entries (with actions,
    scaffolding, property actions, and target definition hashes).
    """
    type_defs, prop_defs = _build_catalog_def_lookups(catalog)
    resolved = []
    for evaluation in evaluations:
        entry = resolve_alignment(evaluation, target_ontology, catalog)
        _add_definition_hashes(entry, type_defs, prop_defs)
        resolved.append(entry)
    return resolved


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def assemble_alignment_report(
    run_dir: Path,
    entries: list[dict],
    target_ontology: str,
    target_version: str,
    actions: dict,
    type_patterns: dict,
) -> Path:
    """Write the completed alignment-report.json.

    Returns the output path.
    """
    by_action: dict[str, int] = {}
    for e in entries:
        action = e.get("action", "unknown")
        by_action[action] = by_action.get(action, 0) + 1

    report = {
        "stage": "3",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "targetOntology": target_ontology,
        "targetVersion": target_version,
        "matchingMethod": "semantic",
        "actions": actions,
        "typePatterns": type_patterns,
        "summary": {
            "totalConcepts": len(entries),
            **by_action,
        },
        "entries": entries,
    }

    out_path = run_dir / "alignment-report.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Collect evaluations and assemble alignment report"
    )
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    parser.add_argument(
        "--allow-pending", action="store_true",
        help="Skip pending files instead of failing",
    )
    args = parser.parse_args()

    ctx = load_context(args.run_dir)

    print(f"\nsc-collect-alignments")
    print(f"  Run:    {ctx.run_dir}")
    print(f"  Target: {ctx.target_ontology} {ctx.target_version}")

    # Step 1: Load all search result files
    type_results, prop_results = load_search_results(ctx.run_dir)
    print(f"  Type files:     {len(type_results)}")
    print(f"  Property files: {len(prop_results)}")

    # Step 2: Validate evaluations
    type_eval, type_pending = validate_evaluations(type_results)
    prop_eval, prop_pending = validate_evaluations(prop_results)
    all_pending = type_pending + prop_pending

    print(f"  Evaluated: {len(type_eval)} types, {len(prop_eval)} properties")

    if all_pending:
        if args.allow_pending:
            print(f"  Pending (skipped): {len(all_pending)}")
            for name in all_pending[:10]:
                print(f"    - {name}")
            if len(all_pending) > 10:
                print(f"    ... and {len(all_pending) - 10} more")
        else:
            print(f"\n  ERROR: {len(all_pending)} files still pending:")
            for name in all_pending[:10]:
                print(f"    - {name}")
            if len(all_pending) > 10:
                print(f"    ... and {len(all_pending) - 10} more")
            print(f"\n  All files must be evaluated before collecting.")
            print(f"  Use --allow-pending to skip pending files.")
            sys.exit(1)

    if not type_eval:
        print(f"\n  No evaluated type files to collect. Nothing to do.")
        sys.exit(0)

    # Step 3: Reassemble per-concept evaluations
    evaluations = reassemble_evaluations(type_eval, prop_eval)

    # Step 4: Load catalog for resolve_alignment
    catalog_path = resolve_catalog_path(ctx.target_ontology, ctx.target_version)
    if catalog_path is None:
        print(f"\n  ERROR: Reference catalog not found for "
              f"{ctx.target_ontology} {ctx.target_version}")
        sys.exit(1)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    # Step 5: Load placeholder report for actions/typePatterns
    placeholder_path = ctx.run_dir / "alignment-report.json"
    if placeholder_path.exists():
        placeholder = json.loads(placeholder_path.read_text(encoding="utf-8"))
        actions = placeholder.get("actions", {})
        type_patterns = placeholder.get("typePatterns", {})
    else:
        actions = catalog.get("actions", {})
        type_patterns = catalog.get("typePatterns", {})

    # Step 6: Resolve all evaluations
    print(f"\n  Resolving alignments...")
    entries = collect_and_resolve(evaluations, ctx.target_ontology, catalog)

    # Step 7: Assemble and write report
    out_path = assemble_alignment_report(
        ctx.run_dir, entries,
        ctx.target_ontology, ctx.target_version,
        actions, type_patterns,
    )

    # Summary
    by_action: dict[str, int] = {}
    for e in entries:
        a = e.get("action", "unknown")
        by_action[a] = by_action.get(a, 0) + 1

    print(f"\n  Output: {out_path}")
    print(f"  Total concepts: {len(entries)}")
    for action, count in sorted(by_action.items()):
        print(f"    {action}: {count}")
    print(f"  Done.")


if __name__ == "__main__":
    main()
