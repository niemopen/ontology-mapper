#!/usr/bin/env python3
"""Generate a reference catalog from any OWL ontology file(s).

Parses OWL classes, properties, and structural relationships using rdflib,
then writes the same catalog schema that the pipeline expects (identical to
what generate_niem_catalog.py produces for NIEM).

Works with any standard OWL ontology: SALI/FOLIO, NODS, FIBO, etc.

Usage:
    om-generate-owl-catalog --input LMSS.owl --name sali-folio --version 2.0
    om-generate-owl-catalog --input nods/*.ttl --name nods --version 1.0
    om-generate-owl-catalog --input ontology.rdf --name my-ontology --version 1.0 --label-as-name

The --label-as-name flag is for ontologies with opaque IRIs (like SALI)
where rdfs:label should be used as the display name instead of the IRI
local name.

Outputs (in specs/):
    {name}_reference_catalog_{version}.json
    {name}_catalog_summary_{version}.json
    {name}_type_directory_{version}.txt
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_mapper.run_dir_utils import resolve_specs_dir

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def load_graph(input_paths: list[str]) -> Graph:
    """Load one or more OWL/RDF/TTL files into a single graph."""
    g = Graph()
    for p in input_paths:
        path = Path(p)
        if not path.exists():
            print(f"Error: file not found: {p}", file=sys.stderr)
            sys.exit(1)
        fmt = _guess_format(path)
        print(f"  Loading {path.name} ({fmt})...")
        g.parse(str(path), format=fmt)
    print(f"  Graph loaded: {len(g)} triples")
    return g


def _guess_format(path: Path) -> str:
    """Guess RDF serialization format from file extension."""
    ext = path.suffix.lower()
    return {
        ".owl": "xml",
        ".rdf": "xml",
        ".xml": "xml",
        ".ttl": "turtle",
        ".n3": "n3",
        ".nt": "nt",
        ".jsonld": "json-ld",
    }.get(ext, "xml")


def _local_name(uri) -> str:
    """Extract local name from a URI (after # or last /)."""
    s = str(uri)
    if "#" in s:
        return s.split("#")[-1]
    return s.rsplit("/", 1)[-1]


def _get_label(g: Graph, uri: URIRef) -> str:
    """Get rdfs:label for a resource, or empty string."""
    for label in g.objects(uri, RDFS.label):
        if isinstance(label, Literal):
            # Prefer English or untagged labels
            if label.language in (None, "en", "en-us"):
                return str(label)
    # Fallback: any label
    for label in g.objects(uri, RDFS.label):
        if isinstance(label, Literal):
            return str(label)
    return ""


def _get_definition(g: Graph, uri: URIRef) -> str:
    """Get definition from skos:definition, rdfs:comment, or dc:description."""
    # Try skos:definition first (SALI uses this)
    for defn in g.objects(uri, SKOS.definition):
        text = str(defn).strip()
        if text and text.upper() != "NULL":
            return text
    # Fallback to rdfs:comment
    for comment in g.objects(uri, RDFS.comment):
        text = str(comment).strip()
        if text:
            return text
    # Fallback to dc:description
    DC = Namespace("http://purl.org/dc/elements/1.1/")
    for desc in g.objects(uri, DC.description):
        text = str(desc).strip()
        if text:
            return text
    return ""


def _get_alt_labels(g: Graph, uri: URIRef) -> list[str]:
    """Get skos:altLabel values for a resource (for embedding context)."""
    labels = []
    for label in g.objects(uri, SKOS.altLabel):
        if isinstance(label, Literal):
            if label.language in (None, "en", "en-us"):
                labels.append(str(label))
    return labels


def _build_prefix_map(g: Graph) -> dict[str, str]:
    """Build namespace prefix map from graph bindings."""
    prefix_map = {}
    for prefix, ns in g.namespaces():
        if prefix:
            prefix_map[str(ns)] = prefix
    return prefix_map


def _qname(uri: URIRef, prefix_map: dict, label_as_name: bool = False,
           g: Graph = None) -> str:
    """Convert a URI to a qualified name using the prefix map.

    If label_as_name is True and a graph is provided, uses rdfs:label
    as the local name (for ontologies with opaque IRIs like SALI).
    """
    s = str(uri)
    if label_as_name and g is not None:
        label = _get_label(g, uri)
        if label:
            # Find the prefix for this URI's namespace
            for ns_uri, prefix in prefix_map.items():
                if s.startswith(ns_uri):
                    return f"{prefix}:{label}"
            return label

    for ns_uri, prefix in prefix_map.items():
        if s.startswith(ns_uri):
            local = s[len(ns_uri):]
            return f"{prefix}:{local}"
    return _local_name(uri)


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

def extract_classes(g: Graph, prefix_map: dict,
                    label_as_name: bool = False) -> list[dict]:
    """Extract all OWL classes with their metadata."""
    classes = {}

    for cls_uri in g.subjects(RDF.type, OWL.Class):
        if not isinstance(cls_uri, URIRef):
            continue
        # Skip OWL built-ins
        if str(cls_uri).startswith("http://www.w3.org/"):
            continue

        qn = _qname(cls_uri, prefix_map, label_as_name, g)
        label = _get_label(g, cls_uri)
        definition = _get_definition(g, cls_uri)
        alt_labels = _get_alt_labels(g, cls_uri)

        # Get direct parent classes
        parents = []
        for parent in g.objects(cls_uri, RDFS.subClassOf):
            if isinstance(parent, URIRef) and not str(parent).startswith("http://www.w3.org/2002/07/owl#"):
                parent_qn = _qname(parent, prefix_map, label_as_name, g)
                parents.append(parent_qn)

        classes[str(cls_uri)] = {
            "uri": str(cls_uri),
            "qname": qn,
            "label": label,
            "definition": definition,
            "altLabels": alt_labels,
            "directParents": parents,
            "properties": [],  # filled later
        }

    return classes


def _build_inheritance_chains(classes: dict) -> dict:
    """Compute full inheritance chain for each class.

    Returns a dict mapping class URI -> ordered list of ancestor qnames
    (from root to immediate parent).
    """
    # Build lookup by qname
    qname_to_parents = {}
    for cls_data in classes.values():
        qname_to_parents[cls_data["qname"]] = cls_data["directParents"]

    chains = {}
    for cls_uri, cls_data in classes.items():
        chain = []
        visited = set()
        current = cls_data["qname"]
        while True:
            parents = qname_to_parents.get(current, [])
            if not parents or current in visited:
                break
            visited.add(current)
            parent = parents[0]  # follow first parent for primary chain
            chain.append(parent)
            current = parent
        chain.reverse()
        chains[cls_uri] = chain

    return chains


# ---------------------------------------------------------------------------
# Property extraction
# ---------------------------------------------------------------------------

def extract_properties(g: Graph, classes: dict, prefix_map: dict,
                       label_as_name: bool = False) -> list[dict]:
    """Extract all OWL properties with domain/range info."""
    properties = []
    seen = set()

    for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
        kind = "object" if prop_type == OWL.ObjectProperty else "datatype"
        for prop_uri in g.subjects(RDF.type, prop_type):
            if not isinstance(prop_uri, URIRef):
                continue
            uri_str = str(prop_uri)
            if uri_str in seen or uri_str.startswith("http://www.w3.org/"):
                continue
            seen.add(uri_str)

            qn = _qname(prop_uri, prefix_map, label_as_name, g)
            label = _get_label(g, prop_uri)
            definition = _get_definition(g, prop_uri)

            # Domain classes
            domains = []
            for domain in g.objects(prop_uri, RDFS.domain):
                if isinstance(domain, URIRef):
                    domain_qn = _qname(domain, prefix_map, label_as_name, g)
                    domains.append(domain_qn)

            # Range
            ranges = []
            for range_ in g.objects(prop_uri, RDFS.range):
                if isinstance(range_, URIRef):
                    range_qn = _qname(range_, prefix_map, label_as_name, g)
                    ranges.append(range_qn)

            # Add property to its domain classes
            for domain_uri in g.objects(prop_uri, RDFS.domain):
                if isinstance(domain_uri, URIRef) and str(domain_uri) in classes:
                    local = label if label_as_name and label else _local_name(prop_uri)
                    classes[str(domain_uri)]["properties"].append(local)

            properties.append({
                "uri": uri_str,
                "qualifiedProperty": qn,
                "name": label if label_as_name and label else _local_name(prop_uri),
                "label": label,
                "definition": definition,
                "qualifiedType": ranges[0] if ranges else "",
                "containingTypes": domains,
                "isAbstract": False,
                "propertyKind": kind,
            })

    return properties


# ---------------------------------------------------------------------------
# Definition quality report
# ---------------------------------------------------------------------------

def definition_quality_report(classes: dict, properties: list[dict],
                              ontology_name: str) -> dict:
    """Print a factual summary of definition coverage for human review.

    Reports raw counts, averages, and examples — no quality judgments.
    """
    cls_list = list(classes.values())
    cls_total = len(cls_list)
    cls_with_def = sum(1 for c in cls_list if c["definition"])
    cls_def_lengths = [len(c["definition"]) for c in cls_list if c["definition"]]
    cls_avg_len = round(sum(cls_def_lengths) / len(cls_def_lengths)) if cls_def_lengths else 0

    prop_total = len(properties)
    prop_with_def = sum(1 for p in properties if p["definition"])
    prop_def_lengths = [len(p["definition"]) for p in properties if p["definition"]]
    prop_avg_len = round(sum(prop_def_lengths) / len(prop_def_lengths)) if prop_def_lengths else 0

    # Duplicate definitions
    def_counts = defaultdict(int)
    for c in cls_list:
        if c["definition"]:
            def_counts[c["definition"]] += 1
    for p in properties:
        if p["definition"]:
            def_counts[p["definition"]] += 1
    duplicates = {d: n for d, n in def_counts.items() if n > 1}
    duplicate_count = sum(n for n in duplicates.values())

    missing_cls = [c["qname"] for c in cls_list if not c["definition"]]
    missing_props = [p.get("qualifiedProperty", "") for p in properties if not p["definition"]]

    shortest = sorted(
        [(c["qname"], c["definition"]) for c in cls_list if c["definition"]]
        + [(p.get("qualifiedProperty", ""), p["definition"]) for p in properties if p["definition"]],
        key=lambda x: len(x[1])
    )[:5]

    report = {
        "ontology": ontology_name,
        "types": {
            "total": cls_total,
            "withDefinitions": cls_with_def,
            "coveragePercent": round(100 * cls_with_def / max(cls_total, 1), 1),
            "avgDefinitionLength": cls_avg_len,
            "missingCount": len(missing_cls),
            "missingExamples": missing_cls[:20],
        },
        "properties": {
            "total": prop_total,
            "withDefinitions": prop_with_def,
            "coveragePercent": round(100 * prop_with_def / max(prop_total, 1), 1),
            "avgDefinitionLength": prop_avg_len,
            "missingCount": len(missing_props),
            "missingExamples": missing_props[:20],
        },
        "duplicates": {
            "uniqueDuplicateDefinitions": len(duplicates),
            "totalAffectedEntries": duplicate_count,
            "examples": [
                {"definition": d[:100], "count": n}
                for d, n in sorted(duplicates.items(), key=lambda x: -x[1])[:5]
            ],
        },
        "shortestDefinitions": [
            {"id": qn, "definition": d, "length": len(d)}
            for qn, d in shortest
        ],
    }

    # Print
    print(f"\n{'='*70}")
    print(f"  Definition Report: {ontology_name}")
    print(f"{'='*70}")
    print(f"\n  Types:      {cls_total} total, {cls_with_def} with definitions "
          f"({report['types']['coveragePercent']}%)")
    print(f"  Properties: {prop_total} total, {prop_with_def} with definitions "
          f"({report['properties']['coveragePercent']}%)")
    print(f"  Avg definition length: {cls_avg_len} chars (types), "
          f"{prop_avg_len} chars (properties)")
    if duplicate_count:
        print(f"  Duplicates: {duplicate_count} entries share "
              f"{len(duplicates)} repeated definitions")

    if missing_cls:
        print(f"\n  Types missing definitions ({len(missing_cls)} total, first 10):")
        for qn in missing_cls[:10]:
            print(f"    {qn}")
    if missing_props:
        print(f"\n  Properties missing definitions ({len(missing_props)} total, first 10):")
        for qn in missing_props[:10]:
            print(f"    {qn}")
    if shortest:
        print(f"\n  Shortest definitions:")
        for qn, d in shortest:
            print(f"    {qn}: \"{d}\" ({len(d)} chars)")
    if duplicates:
        print(f"\n  Most repeated definitions:")
        for d, n in sorted(duplicates.items(), key=lambda x: -x[1])[:3]:
            print(f"    \"{d[:80]}{'...' if len(d) > 80 else ''}\" ({n} times)")

    print(f"\n{'='*70}")
    return report


# ---------------------------------------------------------------------------
# Catalog assembly
# ---------------------------------------------------------------------------

def build_catalog(classes: dict, properties: list[dict],
                  inheritance_chains: dict, prefix_map: dict,
                  name: str, version: str, source_files: list[str]) -> dict:
    """Assemble the reference catalog in the canonical schema."""

    # Build type entries
    types = []
    for cls_uri, cls_data in classes.items():
        chain = inheritance_chains.get(cls_uri, [])
        base_type = cls_data["directParents"][0] if cls_data["directParents"] else None

        # Namespace from qname
        qn = cls_data["qname"]
        ns = qn.split(":")[0] if ":" in qn else ""

        types.append({
            "qname": qn,
            "label": cls_data["label"],
            "altLabels": cls_data["altLabels"],
            "uri": cls_data["uri"],
            "definition": cls_data["definition"],
            "baseType": base_type,
            "pattern": "object",
            "properties": cls_data["properties"],
            "contentStyle": "",
            "isAugmentation": False,
            "isAdapter": False,
            "isMetadata": False,
            "propertyCardinalities": {},
            "propertyDefinitions": {},
            "inheritanceChain": chain,
        })

    # Build property index grouped by namespace
    property_index = defaultdict(lambda: {"properties": []})
    for prop in properties:
        qp = prop["qualifiedProperty"]
        ns = qp.split(":")[0] if ":" in qp else "_"
        property_index[ns]["properties"].append({
            "name": prop["name"],
            "label": prop.get("label", ""),
            "uri": prop.get("uri", ""),
            "qualifiedProperty": prop["qualifiedProperty"],
            "definition": prop["definition"],
            "qualifiedType": prop["qualifiedType"],
            "isAbstract": prop["isAbstract"],
            "containingTypes": prop["containingTypes"],
        })

    # Build namespace map
    namespaces = {}
    inv_prefix = {v: k for k, v in prefix_map.items()}
    for prefix in sorted(inv_prefix.keys()):
        if prefix:
            namespaces[prefix] = inv_prefix[prefix]

    # Stats
    stats = {
        "totalTypes": len(types),
        "totalPropertyMemberships": len(properties),
        "namespaces": len(namespaces),
    }

    catalog = {
        "version": version,
        "description": (
            f"{name} reference catalog for semantic ontology alignment. "
            f"Generated from OWL source files on "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
            f"Source: {', '.join(Path(f).name for f in source_files)}."
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": source_files,
        "actions": {
            "reuse": "The source concept maps directly to an existing type. Use the target type as-is.",
            "extend": "The source concept requires a new type that inherits from a target base type via rdfs:subClassOf.",
        },
        "defaultBaseType": "owl:Thing",
        "typePatterns": {
            "defined_class": "Classes with necessary and sufficient conditions (owl:equivalentClass). Gives higher confidence in semantic coverage.",
            "primitive_class": "Classes with only necessary conditions (rdfs:subClassOf). The most common pattern.",
            "restriction": "Classes defined by property restrictions (someValuesFrom, allValuesFrom, cardinality).",
            "equivalent_class": "Two classes declared semantically identical.",
            "disjoint_class": "Classes declared as non-overlapping.",
            "union_class": "Classes defined as the union of other classes.",
            "intersection_class": "Classes defined as the intersection of other classes.",
        },
        "stats": stats,
        "namespaces": namespaces,
        "propertyIndex": dict(property_index),
        "augmentationMap": {},  # Not applicable for generic OWL
        "types": types,
    }

    return catalog


def build_catalog_summary(types: list[dict]) -> dict:
    """Build a lightweight namespace-grouped summary."""
    by_ns = defaultdict(list)
    for t in types:
        qn = t["qname"]
        ns = qn.split(":")[0] if ":" in qn else "_"
        by_ns[ns].append({
            "qname": t["qname"],
            "definition": t["definition"],
            "baseType": t["baseType"],
            "properties": t["properties"][:10],
            "propertyCount": len(t["properties"]),
        })

    summary = {}
    for ns in sorted(by_ns.keys()):
        summary[ns] = {
            "label": ns,
            "types": by_ns[ns],
        }
    return summary


def build_type_directory(types: list[dict]) -> str:
    """Build a compact one-line-per-type directory."""
    lines = []
    lines.append(f"# Type Directory — one line per type for efficient semantic matching")
    lines.append(f"# Format: qname | baseType | pattern | propCount | definition | topProperties")
    lines.append(f"# Total: {len(types)} types")
    lines.append(f"#")

    for t in sorted(types, key=lambda x: x["qname"]):
        base = t["baseType"] or "-"
        props = ", ".join(t["properties"][:8])
        defn = (t["definition"] or "")[:120]
        lines.append(
            f"{t['qname']} | {base} | {t['pattern']} | "
            f"{len(t['properties'])} | {defn} | {props}"
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(input_paths: list[str], name: str, version: str,
             label_as_name: bool = False, force: bool = False) -> Path:
    """Full generation pipeline: parse, assess, emit."""

    specs_dir = resolve_specs_dir()
    catalog_path = specs_dir / f"{name}_reference_catalog_{version}.json"

    if catalog_path.exists() and not force:
        print(f"Catalog already exists: {catalog_path}")
        print(f"Use --force to overwrite.")
        return catalog_path

    # Step 1: Load
    print(f"\nStep 1: Loading OWL files...")
    g = load_graph(input_paths)

    # Step 2: Build prefix map
    prefix_map = _build_prefix_map(g)
    print(f"  Namespaces: {len(prefix_map)}")

    # Step 3: Extract classes
    print(f"\nStep 2: Extracting classes...")
    classes = extract_classes(g, prefix_map, label_as_name)
    print(f"  Classes: {len(classes)}")

    # Step 4: Build inheritance chains
    print(f"\nStep 3: Building inheritance chains...")
    chains = _build_inheritance_chains(classes)
    max_depth = max((len(c) for c in chains.values()), default=0)
    print(f"  Max inheritance depth: {max_depth}")

    # Step 5: Extract properties
    print(f"\nStep 4: Extracting properties...")
    properties = extract_properties(g, classes, prefix_map, label_as_name)
    print(f"  Properties: {len(properties)}")

    # Step 6: Definition quality report
    print(f"\nStep 5: Definition quality assessment...")
    quality = definition_quality_report(classes, properties, name)

    # Save quality report
    quality_path = specs_dir / f"{name}_definition_quality_{version}.json"
    quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  Quality report saved: {quality_path}")

    # Step 7: Assemble catalog
    print(f"\nStep 6: Assembling catalog...")
    catalog = build_catalog(
        classes, properties, chains, prefix_map,
        name, version, input_paths,
    )

    # Write reference catalog
    catalog_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  Reference catalog: {catalog_path}")
    print(f"    Types: {catalog['stats']['totalTypes']}")
    print(f"    Properties: {catalog['stats']['totalPropertyMemberships']}")

    # Write catalog summary
    summary = build_catalog_summary(catalog["types"])
    summary_data = {
        "version": version,
        "description": f"{name} catalog summary",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "namespaces": len(summary),
            "types": sum(len(ns["types"]) for ns in summary.values()),
        },
        "namespaces": summary,
    }
    summary_path = specs_dir / f"{name}_catalog_summary_{version}.json"
    summary_path.write_text(
        json.dumps(summary_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  Catalog summary: {summary_path}")

    # Write type directory
    directory_text = build_type_directory(catalog["types"])
    directory_path = specs_dir / f"{name}_type_directory_{version}.txt"
    directory_path.write_text(directory_text, encoding="utf-8")
    print(f"  Type directory: {directory_path}")

    print(f"\nDone. Catalog for {name} v{version} generated.")
    return catalog_path


def main():
    import argparse
    import glob as globmod

    parser = argparse.ArgumentParser(
        description="Generate a reference catalog from OWL ontology files"
    )
    parser.add_argument("--input", required=True, nargs="+",
                        help="OWL/RDF/TTL file(s) or glob patterns")
    parser.add_argument("--name", required=True,
                        help="Ontology name (e.g., sali-folio, nods, fibo)")
    parser.add_argument("--version", required=True,
                        help="Ontology version (e.g., 2.0, 1.0)")
    parser.add_argument("--label-as-name", action="store_true",
                        help="Use rdfs:label as display name (for ontologies with opaque IRIs)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing catalog")
    args = parser.parse_args()

    # Expand glob patterns
    input_paths = []
    for pattern in args.input:
        expanded = globmod.glob(pattern)
        if expanded:
            input_paths.extend(expanded)
        else:
            input_paths.append(pattern)

    if not input_paths:
        print("Error: no input files specified", file=sys.stderr)
        sys.exit(1)

    generate(input_paths, args.name, args.version,
             label_as_name=args.label_as_name, force=args.force)


if __name__ == "__main__":
    main()
