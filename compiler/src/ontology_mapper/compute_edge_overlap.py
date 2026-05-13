#!/usr/bin/env python3
"""Compute cross-edge vocabulary overlap between edge packages.

Takes 2+ concept inventory JSON files and computes interoperability
metrics based on shared target type coverage.

Usage:
    om-edge-overlap inv1.json inv2.json --output overlap.json
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone


# ─── Edge Vocabulary Model ───────────────────────────────────────────────

@dataclass
class EdgeVocabulary:
    """Extracted vocabulary from an edge package for overlap computation."""
    name: str
    source_path: str
    target_types: set = field(default_factory=set)
    target_properties: dict = field(default_factory=dict)  # type → {property set}
    namespaces: set = field(default_factory=set)
    codelist_schemes: dict = field(default_factory=dict)  # scheme_label → {code values}


# ─── Loading ─────────────────────────────────────────────────────────────

def load_concept_inventory(path):
    """Load a concept-inventory.json file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def extract_vocabulary(inventory, source_path):
    """Extract an EdgeVocabulary from a concept inventory dict."""
    name = Path(source_path).stem
    vocab = EdgeVocabulary(name=name, source_path=str(source_path))

    # Types: all class qnames
    for cls in inventory.get("classes", []):
        qname = cls.get("qname", "")
        if qname:
            vocab.target_types.add(qname)

    # Properties per type: from SHACL shapes
    for shape in inventory.get("shaclShapes", []):
        target = shape.get("targetClass", "")
        if target:
            prop_paths = {p["path"] for p in shape.get("properties", []) if p.get("path")}
            vocab.target_properties[target] = prop_paths

    # Namespaces
    for uri, prefix in inventory.get("namespaceMap", {}).items():
        vocab.namespaces.add(prefix.rstrip(":"))

    # Codelist schemes
    for scheme in inventory.get("codelistSchemes", []):
        label = scheme.get("label", "")
        if label:
            values = {c["label"] for c in scheme.get("concepts", []) if c.get("label")}
            vocab.codelist_schemes[label] = values

    return vocab


def load_edge_vocabulary(path):
    """Load an edge vocabulary from a JSON concept-inventory file."""
    path = Path(path)
    if path.suffix != ".json":
        raise ValueError(f"Unsupported file type: {path.suffix} (expected .json)")
    inventory = load_concept_inventory(path)
    return extract_vocabulary(inventory, path)


# ─── Overlap Metrics ─────────────────────────────────────────────────────

def jaccard(set_a, set_b):
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def compute_type_overlap(vocab_a, vocab_b):
    """Compute type-level overlap between two vocabularies."""
    shared = vocab_a.target_types & vocab_b.target_types
    return {
        "jaccard": jaccard(vocab_a.target_types, vocab_b.target_types),
        "sharedCount": len(shared),
        "aOnlyCount": len(vocab_a.target_types - vocab_b.target_types),
        "bOnlyCount": len(vocab_b.target_types - vocab_a.target_types),
        "sharedTypes": sorted(shared),
    }


def compute_property_overlap(vocab_a, vocab_b):
    """Compute property-level overlap for shared types."""
    shared_types = set(vocab_a.target_properties.keys()) & set(vocab_b.target_properties.keys())
    if not shared_types:
        return {"averageJaccard": 0.0, "sharedTypeCount": 0, "perType": {}}

    per_type = {}
    total_jaccard = 0.0
    for t in sorted(shared_types):
        props_a = vocab_a.target_properties.get(t, set())
        props_b = vocab_b.target_properties.get(t, set())
        j = jaccard(props_a, props_b)
        total_jaccard += j
        shared_props = sorted(props_a & props_b)
        per_type[t] = {
            "jaccard": round(j, 4),
            "sharedProperties": shared_props,
            "sharedCount": len(shared_props),
        }

    return {
        "averageJaccard": round(total_jaccard / len(shared_types), 4) if shared_types else 0.0,
        "sharedTypeCount": len(shared_types),
        "perType": per_type,
    }


def compute_namespace_overlap(vocab_a, vocab_b):
    """Compute namespace-level overlap."""
    shared = vocab_a.namespaces & vocab_b.namespaces
    return {
        "jaccard": jaccard(vocab_a.namespaces, vocab_b.namespaces),
        "sharedCount": len(shared),
        "shared": sorted(shared),
        "aOnly": sorted(vocab_a.namespaces - vocab_b.namespaces),
        "bOnly": sorted(vocab_b.namespaces - vocab_a.namespaces),
    }


def compute_codelist_overlap(vocab_a, vocab_b):
    """Compute codelist overlap — both scheme-level and value-level."""
    shared_schemes = set(vocab_a.codelist_schemes.keys()) & set(vocab_b.codelist_schemes.keys())
    if not shared_schemes:
        return {"schemeJaccard": 0.0, "sharedSchemeCount": 0, "perScheme": {}}

    all_schemes = set(vocab_a.codelist_schemes.keys()) | set(vocab_b.codelist_schemes.keys())
    scheme_jaccard = len(shared_schemes) / len(all_schemes) if all_schemes else 0.0

    per_scheme = {}
    for scheme in sorted(shared_schemes):
        vals_a = vocab_a.codelist_schemes.get(scheme, set())
        vals_b = vocab_b.codelist_schemes.get(scheme, set())
        shared_vals = sorted(vals_a & vals_b)
        per_scheme[scheme] = {
            "valueJaccard": round(jaccard(vals_a, vals_b), 4),
            "sharedValueCount": len(shared_vals),
            "aValueCount": len(vals_a),
            "bValueCount": len(vals_b),
        }

    return {
        "schemeJaccard": round(scheme_jaccard, 4),
        "sharedSchemeCount": len(shared_schemes),
        "perScheme": per_scheme,
    }


def compute_pairwise_overlap(vocab_a, vocab_b, weights=None):
    """Compute all overlap metrics between two vocabularies."""
    if weights is None:
        weights = {"type": 0.4, "property": 0.3, "namespace": 0.1, "codelist": 0.2}

    type_overlap = compute_type_overlap(vocab_a, vocab_b)
    property_overlap = compute_property_overlap(vocab_a, vocab_b)
    namespace_overlap = compute_namespace_overlap(vocab_a, vocab_b)
    codelist_overlap = compute_codelist_overlap(vocab_a, vocab_b)

    composite = (
        weights["type"] * type_overlap["jaccard"]
        + weights["property"] * property_overlap["averageJaccard"]
        + weights["namespace"] * namespace_overlap["jaccard"]
        + weights["codelist"] * codelist_overlap["schemeJaccard"]
    )

    return {
        "a": vocab_a.name,
        "b": vocab_b.name,
        "compositeInteroperabilityScore": round(composite, 4),
        "weights": weights,
        "typeOverlap": type_overlap,
        "propertyOverlap": property_overlap,
        "namespaceOverlap": namespace_overlap,
        "codelistOverlap": codelist_overlap,
    }


# ─── Report ──────────────────────────────────────────────────────────────

def build_overlap_report(paths, weights=None):
    """Build a full overlap report for 2+ edge vocabularies."""
    print(f"Loading {len(paths)} edge vocabularies...")
    vocabs = []
    for p in paths:
        print(f"  Loading {Path(p).name}...")
        vocabs.append(load_edge_vocabulary(p))

    print(f"\nComputing pairwise overlaps...")
    pairs = []
    for i in range(len(vocabs)):
        for j in range(i + 1, len(vocabs)):
            result = compute_pairwise_overlap(vocabs[i], vocabs[j], weights)
            pairs.append(result)
            print(f"  {vocabs[i].name} <-> {vocabs[j].name}: "
                  f"composite={result['compositeInteroperabilityScore']:.4f}")

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "edgeCount": len(vocabs),
        "edges": [
            {
                "name": v.name,
                "source": v.source_path,
                "typeCount": len(v.target_types),
                "propertyTypeCount": len(v.target_properties),
                "namespaceCount": len(v.namespaces),
                "codelistSchemeCount": len(v.codelist_schemes),
            }
            for v in vocabs
        ],
        "pairwiseOverlaps": pairs,
    }

    return report


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    paths = []
    output_path = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        elif args[i].startswith("--"):
            print(f"Unknown argument: {args[i]}")
            sys.exit(1)
        else:
            paths.append(args[i])
            i += 1

    if len(paths) < 2:
        print("Usage: om-edge-overlap <path1> <path2> "
              "[<path3>...] [--output <path>]")
        print("  Accepts .json (concept inventory) files")
        sys.exit(1)

    report = build_overlap_report(paths)

    if output_path is None:
        output_path = Path("edge-overlap-report.json")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nReport saved to {output_path}")


if __name__ == "__main__":
    main()
