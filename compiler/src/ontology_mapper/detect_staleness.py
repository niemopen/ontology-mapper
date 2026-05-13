#!/usr/bin/env python3
"""Codebook version fingerprinting — detect stale alignments.

Compares ``targetDefinitionHash`` values between two alignment reports to
identify which alignments reference definitions that have changed.  When a
target ontology releases a new version, run this tool against the old and
new alignment reports to find stale alignments without re-running the full
pipeline.

Usage:
    om-detect-staleness --old REPORT --new REPORT [--output PATH]
"""

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def _index_entries(entries):
    """Build {sourceConcept: entry} lookup from alignment report entries."""
    return {e["sourceConcept"]: e for e in entries}


def _index_properties(entry):
    """Build {sourceProperty: prop} lookup from an entry's properties.

    Works with both alignment report (``properties``) and mapping matrix
    (``propertyMappings``) schemas.
    """
    props = entry.get("properties") or entry.get("propertyMappings") or []
    return {p["sourceProperty"]: p for p in props}


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_properties(old_entry, new_entry):
    """Compare property-level hashes between two alignment entries.

    Returns a list of stale property dicts, each with sourceProperty,
    old/new hash, and old/new definition.
    """
    old_props = _index_properties(old_entry)
    new_props = _index_properties(new_entry)

    stale = []
    for prop_name, new_prop in new_props.items():
        old_prop = old_props.get(prop_name)
        if old_prop is None:
            continue  # new property — not stale, just new

        old_hash = old_prop.get("targetDefinitionHash")
        new_hash = new_prop.get("targetDefinitionHash")

        if old_hash is not None and new_hash is not None and old_hash != new_hash:
            stale.append({
                "sourceProperty": prop_name,
                "oldHash": old_hash,
                "newHash": new_hash,
                "oldDefinition": old_prop.get("targetDefinition"),
                "newDefinition": new_prop.get("targetDefinition"),
            })

    return stale


def compare_reports(old_entries, new_entries):
    """Compare two sets of alignment entries by targetDefinitionHash.

    Args:
        old_entries: list of alignment entries from the old report.
        new_entries: list of alignment entries from the new report.

    Returns:
        dict with keys:
        - staleTypes: entries where the type-level hash changed
        - staleProperties: entries where property-level hashes changed
        - unchanged: entries where all hashes match
        - newConcepts: concepts in new but not old
        - droppedConcepts: concepts in old but not new
    """
    old_index = _index_entries(old_entries)
    new_index = _index_entries(new_entries)

    old_concepts = set(old_index)
    new_concepts = set(new_index)

    stale_types = []
    stale_properties = []
    unchanged = []

    for concept in sorted(old_concepts & new_concepts):
        old_entry = old_index[concept]
        new_entry = new_index[concept]

        old_hash = old_entry.get("targetDefinitionHash")
        new_hash = new_entry.get("targetDefinitionHash")
        type_stale = (
            old_hash is not None
            and new_hash is not None
            and old_hash != new_hash
        )

        prop_stale = compare_properties(old_entry, new_entry)

        if type_stale:
            stale_types.append({
                "sourceConcept": concept,
                "oldHash": old_hash,
                "newHash": new_hash,
                "oldDefinition": old_entry.get("targetDefinition"),
                "newDefinition": new_entry.get("targetDefinition"),
                "targetType": new_entry.get("targetType"),
                "staleProperties": prop_stale,
            })
        elif prop_stale:
            stale_properties.append({
                "sourceConcept": concept,
                "targetType": new_entry.get("targetType"),
                "staleProperties": prop_stale,
            })
        else:
            unchanged.append(concept)

    return {
        "staleTypes": stale_types,
        "staleProperties": stale_properties,
        "unchanged": unchanged,
        "newConcepts": sorted(new_concepts - old_concepts),
        "droppedConcepts": sorted(old_concepts - new_concepts),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_staleness_report(old_report, new_report):
    """Build a staleness report from two alignment reports.

    Args:
        old_report: parsed alignment-report.json (old version).
        new_report: parsed alignment-report.json (new version).

    Returns:
        dict — the staleness report content.
    """
    comparison = compare_reports(
        old_report.get("entries", []),
        new_report.get("entries", []),
    )

    total_stale_props = sum(
        len(e["staleProperties"])
        for e in comparison["staleTypes"] + comparison["staleProperties"]
    )

    return {
        "comparisonMetadata": {
            "oldReport": {
                "targetOntology": old_report.get("targetOntology"),
                "targetVersion": old_report.get("targetVersion"),
                "generatedAt": old_report.get("generatedAt"),
            },
            "newReport": {
                "targetOntology": new_report.get("targetOntology"),
                "targetVersion": new_report.get("targetVersion"),
                "generatedAt": new_report.get("generatedAt"),
            },
        },
        "summary": {
            "totalConcepts": len(comparison["unchanged"])
            + len(comparison["staleTypes"])
            + len(comparison["staleProperties"]),
            "unchanged": len(comparison["unchanged"]),
            "staleTypes": len(comparison["staleTypes"]),
            "stalePropertyOnly": len(comparison["staleProperties"]),
            "totalStaleProperties": total_stale_props,
            "newConcepts": len(comparison["newConcepts"]),
            "droppedConcepts": len(comparison["droppedConcepts"]),
        },
        "staleAlignments": comparison["staleTypes"] + comparison["staleProperties"],
        "newConcepts": comparison["newConcepts"],
        "droppedConcepts": comparison["droppedConcepts"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect stale alignments by comparing targetDefinitionHash "
        "values between two alignment reports"
    )
    parser.add_argument(
        "--old", required=True,
        help="Path to the old alignment-report.json",
    )
    parser.add_argument(
        "--new", required=True,
        help="Path to the new alignment-report.json",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output path (default: writes to same dir as --new)",
    )
    args = parser.parse_args()

    old_path = Path(args.old)
    new_path = Path(args.new)

    if not old_path.exists():
        print(f"\n  ERROR: Old report not found: {old_path}")
        raise SystemExit(1)
    if not new_path.exists():
        print(f"\n  ERROR: New report not found: {new_path}")
        raise SystemExit(1)

    old_report = json.loads(old_path.read_text(encoding="utf-8"))
    new_report = json.loads(new_path.read_text(encoding="utf-8"))

    report = build_staleness_report(old_report, new_report)

    s = report["summary"]
    print(f"\nsc-detect-staleness")
    print(f"  Old: {old_path}")
    print(f"  New: {new_path}")
    print(f"  Concepts compared: {s['totalConcepts']}")
    print(f"  Unchanged:         {s['unchanged']}")
    print(f"  Stale types:       {s['staleTypes']}")
    print(f"  Stale props only:  {s['stalePropertyOnly']}")
    print(f"  Total stale props: {s['totalStaleProperties']}")

    if s["newConcepts"]:
        print(f"  New concepts:      {s['newConcepts']}")
    if s["droppedConcepts"]:
        print(f"  Dropped concepts:  {s['droppedConcepts']}")

    if report["staleAlignments"]:
        print(f"\n  Stale alignments:")
        for entry in report["staleAlignments"]:
            concept = entry["sourceConcept"]
            if "oldHash" in entry:
                print(f"    {concept}: type definition changed "
                      f"({entry['oldHash'][:8]}.. -> {entry['newHash'][:8]}..)")
            if entry.get("staleProperties"):
                for p in entry["staleProperties"]:
                    print(f"      {p['sourceProperty']}: property definition changed "
                          f"({p['oldHash'][:8]}.. -> {p['newHash'][:8]}..)")

    out_path = Path(args.output) if args.output else new_path.parent / "staleness-report.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\n  Written: {out_path}")
