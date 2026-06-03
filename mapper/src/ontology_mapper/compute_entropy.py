#!/usr/bin/env python3
"""Pre-rotation entropy measurement for a pipeline run.

Computes boundary entropy H_total from batch search results before the LLM
evaluates any alignments.  For each source concept, the candidate count from
vector search represents |Ωᵢ| — the number of plausible target alternatives.
Per-concept entropy = log₂(|Ωᵢ|).  H_total = Σ log₂(|Ωᵢ|).

The same computation applies to properties: per-property entropy from the
property search candidate count.

Known limitation: candidate counts depend on the batch search filtering
threshold (min_score_ratio), which is relative to the top score.  See
Candidate_Filtering__PLAN.md for future investigation.

Usage:
    om-entropy --run-dir {run_dir}
"""

import json
import math
from pathlib import Path


def compute_entropy(candidate_count):
    """Compute entropy in bits from a candidate count.

    Returns log₂(count), or 0 if count ≤ 1 (no ambiguity).
    """
    if candidate_count <= 1:
        return 0.0
    return math.log2(candidate_count)


def analyze_search_results(run_dir):
    """Read batch search results and compute per-item entropy.

    Args:
        run_dir: Path to the pipeline run directory.

    Returns:
        (type_entries, property_entries) where each entry is a dict with
        sourceConcept/sourceProperty, candidateCount, and entropy.
    """
    search_dir = Path(run_dir) / "search-results"

    type_entries = []
    types_dir = search_dir / "types"
    if types_dir.exists():
        for f in sorted(types_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            source = data.get("source", {})
            candidates = data.get("candidates", [])
            count = len(candidates)
            type_entries.append({
                "sourceConcept": source.get("qname", f.stem),
                "candidateCount": count,
                "entropy": round(compute_entropy(count), 3),
            })

    property_entries = []
    props_dir = search_dir / "properties"
    if props_dir.exists():
        for f in sorted(props_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            source = data.get("source", {})
            candidates = data.get("candidates", [])
            count = len(candidates)
            property_entries.append({
                "sourceProperty": source.get("qname", f.stem),
                "parentConcept": source.get("parentType", ""),
                "candidateCount": count,
                "entropy": round(compute_entropy(count), 3),
            })

    return type_entries, property_entries


def build_entropy_summary(type_entries, property_entries):
    """Build the entropy summary artifact.

    Args:
        type_entries: list of per-concept entropy dicts.
        property_entries: list of per-property entropy dicts.

    Returns:
        dict — the entropy-summary.json content.
    """
    h_types = sum(e["entropy"] for e in type_entries)
    h_properties = sum(e["entropy"] for e in property_entries)

    return {
        "hTotal": round(h_types + h_properties, 3),
        "hTypes": round(h_types, 3),
        "hProperties": round(h_properties, 3),
        "typesAnalyzed": len(type_entries),
        "propertiesAnalyzed": len(property_entries),
        "perConcept": type_entries,
        "perProperty": property_entries,
    }


def compute_residual_entropy(entropy_summary, matrix):
    """Compute residual entropy after human review decisions.

    Joins pre-rotation entropy (from entropy-summary.json) with confidence
    signals (from mapping-matrix.json).  Confident decisions collapse
    entropy to zero.  Best-guess decisions retain their pre-rotation
    entropy — the ambiguity was forced to a choice, not truly resolved.

    Args:
        entropy_summary: parsed entropy-summary.json.
        matrix: parsed mapping-matrix.json.

    Returns:
        dict with:
        - hPreTotal, hPreTypes, hPreProperties: pre-rotation entropy
        - hResidualTotal, hResidualTypes, hResidualProperties: post-review
        - hResolvedTotal: information value of the rotation (pre - residual)
        - perConcept: list of per-concept dicts with pre/residual entropy
        - perProperty: list of per-property dicts with pre/residual entropy
    """
    # Index pre-rotation entropy by source name
    type_entropy = {
        e["sourceConcept"]: e["entropy"]
        for e in entropy_summary.get("perConcept", [])
    }
    prop_entropy = {
        e["sourceProperty"]: e["entropy"]
        for e in entropy_summary.get("perProperty", [])
    }

    # Walk the matrix, join with pre-rotation entropy
    per_concept = []
    per_property = []

    for mapping in matrix.get("mappings", []):
        concept = mapping["sourceConcept"]
        pre = type_entropy.get(concept, 0.0)
        confidence = mapping.get("confidence", "confident")
        residual = pre if confidence == "best-guess" else 0.0

        per_concept.append({
            "sourceConcept": concept,
            "preEntropy": pre,
            "confidence": confidence,
            "residualEntropy": residual,
        })

        for prop in mapping.get("propertyMappings", []):
            prop_name = prop["sourceProperty"]
            prop_pre = prop_entropy.get(prop_name, 0.0)
            prop_confidence = prop.get("confidence", "confident")
            prop_residual = prop_pre if prop_confidence == "best-guess" else 0.0

            per_property.append({
                "sourceProperty": prop_name,
                "sourceConcept": concept,
                "preEntropy": prop_pre,
                "confidence": prop_confidence,
                "residualEntropy": prop_residual,
            })

    h_pre_types = sum(e["preEntropy"] for e in per_concept)
    h_pre_props = sum(e["preEntropy"] for e in per_property)
    h_res_types = sum(e["residualEntropy"] for e in per_concept)
    h_res_props = sum(e["residualEntropy"] for e in per_property)

    return {
        "hPreTotal": round(h_pre_types + h_pre_props, 3),
        "hPreTypes": round(h_pre_types, 3),
        "hPreProperties": round(h_pre_props, 3),
        "hResidualTotal": round(h_res_types + h_res_props, 3),
        "hResidualTypes": round(h_res_types, 3),
        "hResidualProperties": round(h_res_props, 3),
        "hResolvedTotal": round(
            (h_pre_types + h_pre_props) - (h_res_types + h_res_props), 3
        ),
        "perConcept": per_concept,
        "perProperty": per_property,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute pre-rotation entropy from batch search results"
    )
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    search_dir = run_dir / "search-results"

    if not search_dir.exists():
        print(f"\n  ERROR: No search-results directory in {run_dir}")
        print(f"  Run om-batch-search first.")
        import sys
        sys.exit(1)

    print(f"\nsc-entropy")
    print(f"  Run: {run_dir}")

    type_entries, property_entries = analyze_search_results(run_dir)
    summary = build_entropy_summary(type_entries, property_entries)

    print(f"  Types analyzed:      {summary['typesAnalyzed']}")
    print(f"  Properties analyzed: {summary['propertiesAnalyzed']}")
    print(f"  H(types):            {summary['hTypes']:.3f} bits")
    print(f"  H(properties):       {summary['hProperties']:.3f} bits")
    print(f"  H(total):            {summary['hTotal']:.3f} bits")

    # Flag high-entropy concepts
    high = [e for e in type_entries if e["entropy"] >= 4.0]
    if high:
        print(f"\n  High-entropy concepts (>= 4.0 bits = >= 16 candidates):")
        for e in sorted(high, key=lambda x: -x["entropy"]):
            print(f"    {e['sourceConcept']}: {e['entropy']:.3f} bits "
                  f"({e['candidateCount']} candidates)")

    out_path = run_dir / "entropy-summary.json"
    out_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  Written: {out_path}")


def main_residual():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Compute residual entropy after human review"
    )
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)

    entropy_path = run_dir / "entropy-summary.json"
    matrix_path = run_dir / "mapping-matrix.json"

    if not entropy_path.exists():
        print(f"\n  ERROR: No entropy-summary.json in {run_dir}")
        print(f"  Run om-entropy first.")
        sys.exit(1)
    if not matrix_path.exists():
        print(f"\n  ERROR: No mapping-matrix.json in {run_dir}")
        print(f"  Run om-build-matrix first.")
        sys.exit(1)

    entropy_summary = json.loads(entropy_path.read_text(encoding="utf-8"))
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))

    result = compute_residual_entropy(entropy_summary, matrix)

    print(f"\nsc-residual-entropy")
    print(f"  Run: {run_dir}")
    print(f"  Pre-rotation:  {result['hPreTotal']:.3f} bits "
          f"(types: {result['hPreTypes']:.3f}, props: {result['hPreProperties']:.3f})")
    print(f"  Residual:      {result['hResidualTotal']:.3f} bits "
          f"(types: {result['hResidualTypes']:.3f}, props: {result['hResidualProperties']:.3f})")
    print(f"  Resolved:      {result['hResolvedTotal']:.3f} bits")

    # Flag best-guess concepts
    best_guess = [e for e in result["perConcept"] if e["confidence"] == "best-guess"]
    if best_guess:
        print(f"\n  Best-guess concepts ({len(best_guess)} — entropy retained):")
        for e in sorted(best_guess, key=lambda x: -x["residualEntropy"]):
            print(f"    {e['sourceConcept']}: {e['residualEntropy']:.3f} bits")

    best_guess_props = [e for e in result["perProperty"] if e["confidence"] == "best-guess"]
    if best_guess_props:
        print(f"\n  Best-guess properties ({len(best_guess_props)} — entropy retained):")
        for e in sorted(best_guess_props, key=lambda x: -x["residualEntropy"]):
            print(f"    {e['sourceProperty']} ({e['sourceConcept']}): "
                  f"{e['residualEntropy']:.3f} bits")

    out_path = run_dir / "residual-entropy.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  Written: {out_path}")
