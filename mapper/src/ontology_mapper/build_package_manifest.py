#!/usr/bin/env python3
"""Auto-discover and build a package manifest for a source input package.

Scans a source package directory, parses all TTL files, and produces a
package-manifest.json describing:
  - Primary and augmenting namespaces (from @prefix declarations + class counts)
  - File classification (ontology, shapes, vocab, seed data, aggregate)
  - Organization and source (inferred from namespace URIs)
  - Prefix-to-URI mappings (for qname resolution)

The manifest eliminates hardcoded namespace URIs, filenames, and paths
from downstream pipeline stages.

Usage:
    om-build-manifest <package_dir>
    om-build-manifest  # uses mapper state
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict



# ─── File Classification ─────────────────────────────────────────────────

def classify_ttl_file(file_path):
    """Parse a TTL file and classify it by RDF content type.

    Returns a dict with:
      - prefixes: {prefix: uri} from @prefix declarations
      - classification: one of 'ontology', 'shapes', 'vocab', 'seed-data', 'aggregate', 'mixed'
      - class_count: number of owl:Class declarations
      - class_namespaces: {namespace_uri: count} — which namespaces define classes
      - signals: list of classification signals found
      - error: error message if parse failed, else None
    """
    from rdflib import Graph, RDF, RDFS, OWL, URIRef, BNode
    from rdflib.namespace import SH, SKOS

    result = {
        "file": str(file_path),
        "prefixes": {},
        "classification": "unknown",
        "class_count": 0,
        "class_namespaces": {},
        "property_namespaces": {},
        "signals": [],
        "error": None,
    }

    try:
        g = Graph()
        g.parse(str(file_path), format="turtle")
    except Exception as e:
        result["error"] = str(e)
        result["classification"] = "parse-error"
        return result

    # Extract prefixes
    for prefix, uri in g.namespaces():
        if prefix:  # skip default namespace
            result["prefixes"][str(prefix)] = str(uri)

    # Count classification signals
    has_owl_class = False
    has_owl_property = False
    has_shacl_shape = False
    has_skos_scheme = False
    has_owl_imports = False
    has_instances = False
    class_ns_counts = Counter()

    # Check for owl:Class declarations
    for cls in g.subjects(RDF.type, OWL.Class):
        if isinstance(cls, BNode):
            continue
        has_owl_class = True
        result["class_count"] += 1
        cls_str = str(cls)
        # Extract namespace from IRI
        if "#" in cls_str:
            ns = cls_str[:cls_str.rindex("#") + 1]
        elif "/" in cls_str:
            ns = cls_str[:cls_str.rindex("/") + 1]
        else:
            ns = cls_str
        class_ns_counts[ns] += 1

    result["class_namespaces"] = dict(class_ns_counts)

    # Check for properties and count by namespace
    prop_ns_counts = Counter()
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(prop, BNode):
            continue
        has_owl_property = True
        prop_str = str(prop)
        if "#" in prop_str:
            ns = prop_str[:prop_str.rindex("#") + 1]
        elif "/" in prop_str:
            ns = prop_str[:prop_str.rindex("/") + 1]
        else:
            ns = prop_str
        prop_ns_counts[ns] += 1
    for prop in g.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(prop, BNode):
            continue
        has_owl_property = True
        prop_str = str(prop)
        if "#" in prop_str:
            ns = prop_str[:prop_str.rindex("#") + 1]
        elif "/" in prop_str:
            ns = prop_str[:prop_str.rindex("/") + 1]
        else:
            ns = prop_str
        prop_ns_counts[ns] += 1

    result["property_namespaces"] = dict(prop_ns_counts)

    # Check for SHACL shapes
    for _ in g.subjects(RDF.type, SH.NodeShape):
        has_shacl_shape = True
        break

    # Check for SKOS concept schemes
    for _ in g.subjects(RDF.type, SKOS.ConceptScheme):
        has_skos_scheme = True
        break

    # Check for owl:imports (aggregate files)
    ontology_subjects = list(g.subjects(RDF.type, OWL.Ontology))
    for ont in ontology_subjects:
        if list(g.objects(ont, OWL.imports)):
            has_owl_imports = True
            break

    # Check for instance data (typed individuals that aren't class/property defs)
    schema_types = {OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
                    OWL.Ontology, OWL.AnnotationProperty,
                    SH.NodeShape, SH.PropertyShape,
                    SKOS.ConceptScheme, SKOS.Concept}
    for s, _, o in g.triples((None, RDF.type, None)):
        if isinstance(s, BNode):
            continue
        if o not in schema_types and isinstance(o, URIRef):
            has_instances = True
            break

    # Build signal list
    if has_owl_class:
        result["signals"].append("owl:Class")
    if has_owl_property:
        result["signals"].append("owl:Property")
    if has_shacl_shape:
        result["signals"].append("sh:NodeShape")
    if has_skos_scheme:
        result["signals"].append("skos:ConceptScheme")
    if has_owl_imports:
        result["signals"].append("owl:imports")
    if has_instances:
        result["signals"].append("instances")

    # Classify
    # A file with owl:imports that also defines classes/properties is still
    # an ontology file (e.g., augmentation modules that import + extend)
    if has_owl_imports and not has_owl_class and not has_owl_property and not has_shacl_shape:
        result["classification"] = "aggregate"
    elif has_shacl_shape and not has_owl_class:
        result["classification"] = "shapes"
    elif has_skos_scheme and not has_owl_class:
        result["classification"] = "vocab"
    elif has_instances and not has_owl_class and not has_shacl_shape:
        result["classification"] = "seed-data"
    elif has_owl_class or has_owl_property:
        result["classification"] = "ontology"
    elif has_skos_scheme:
        result["classification"] = "vocab"
    else:
        result["classification"] = "unknown"

    return result


# ─── Namespace Analysis ───────────────────────────────────────────────────

def analyze_namespaces(file_results):
    """Determine primary and augmenting namespaces from file analysis.

    The primary namespace is the one where the most owl:Class declarations
    live. Augmenting namespaces are other non-standard namespaces that
    define properties or classes but aren't the primary one.

    Only includes namespaces that actually define entities (classes or
    properties) in the ontology — filters out rdflib's auto-registered
    well-known prefixes.
    """
    # Aggregate class and property counts by namespace
    total_class_counts = Counter()
    total_prop_counts = Counter()
    all_prefixes = {}  # uri → prefix (last one wins, which is fine)

    for fr in file_results:
        for ns, count in fr.get("class_namespaces", {}).items():
            total_class_counts[ns] += count
        for ns, count in fr.get("property_namespaces", {}).items():
            total_prop_counts[ns] += count
        for prefix, uri in fr.get("prefixes", {}).items():
            all_prefixes[uri] = prefix

    if not total_class_counts:
        return None, [], all_prefixes

    # Primary namespace: most classes
    primary_uri = total_class_counts.most_common(1)[0][0]
    primary_prefix = all_prefixes.get(primary_uri, "")

    # Well-known namespaces to exclude (standards, not domain ontologies)
    well_known_uris = {
        "http://www.w3.org/2002/07/owl#",
        "http://www.w3.org/2000/01/rdf-schema#",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "http://www.w3.org/2001/XMLSchema#",
        "http://www.w3.org/2004/02/skos/core#",
        "http://www.w3.org/ns/shacl#",
        "http://purl.org/dc/terms/",
        "http://purl.org/dc/elements/1.1/",
        "http://purl.org/dc/dcam/",
        "http://purl.org/dc/dcmitype/",
        "http://www.w3.org/XML/1998/namespace",
    }
    # rdflib auto-registers these prefixes; exclude them unless they
    # actually define classes or properties in the ontology
    rdflib_auto_prefixes = {
        "brick", "csvw", "dcat", "dcmitype", "dcam", "doap", "foaf",
        "geo", "odrl", "org", "prof", "prov", "qb", "schema", "sosa",
        "ssn", "time", "vann", "void", "wgs", "xml",
    }

    # Collect augmenting namespaces: those that define classes OR properties
    # and aren't well-known or the primary namespace
    augmenting = []
    seen_uris = {primary_uri}

    # From class-defining namespaces
    for uri, count in total_class_counts.items():
        if uri in seen_uris or uri in well_known_uris:
            continue
        prefix = all_prefixes.get(uri, "")
        if prefix in rdflib_auto_prefixes:
            continue
        seen_uris.add(uri)
        prop_count = total_prop_counts.get(uri, 0)
        augmenting.append({
            "prefix": prefix, "uri": uri,
            "classCount": count, "propertyCount": prop_count,
        })

    # From property-defining namespaces (e.g., gis:, finance:)
    for uri, count in total_prop_counts.items():
        if uri in seen_uris or uri in well_known_uris:
            continue
        prefix = all_prefixes.get(uri, "")
        if prefix in rdflib_auto_prefixes:
            continue
        seen_uris.add(uri)
        augmenting.append({
            "prefix": prefix, "uri": uri,
            "classCount": 0, "propertyCount": count,
        })

    return (
        {"prefix": primary_prefix, "uri": primary_uri,
         "classCount": total_class_counts[primary_uri]},
        augmenting,
        all_prefixes,
    )


# ─── Organization / Domain Inference ─────────────────────────────────────

def infer_org_source(primary_namespace_uri):
    """Attempt to infer organization and source from the primary namespace URI.

    Tries several common patterns:
      - https://data.{org}.gov/ontology/{source}/
      - https://{org}.org/ontology/{source}/
      - http://{org}.gov/{source}/
      - https://example.org/{org}/{source}/

    Returns (org, source, confidence) where confidence is 'high', 'medium',
    or 'low'. Returns (None, None, 'none') if nothing can be inferred.
    """
    if not primary_namespace_uri:
        return None, None, "none"

    uri = primary_namespace_uri.rstrip("#/")

    # Pattern 1: https://data.{org}.gov/ontology/{source}
    m = re.match(r'https?://data\.([^.]+)\.[^/]+/ontology/([^/#]+)', uri)
    if m:
        return m.group(1), m.group(2), "high"

    # Pattern 2: https://{org}.{tld}/ontology/{source}
    m = re.match(r'https?://([^.]+)\.[^/]+/ontology/([^/#]+)', uri)
    if m:
        return m.group(1), m.group(2), "high"

    # Pattern 3: https://{org}.{tld}/{source}
    m = re.match(r'https?://([^.]+)\.[^/]+/([^/#]+)', uri)
    if m:
        return m.group(1), m.group(2), "medium"

    # Pattern 4: Use last two path segments
    parts = uri.split("/")
    non_empty = [p for p in parts if p and ":" not in p and "." not in p]
    if len(non_empty) >= 2:
        return non_empty[-2], non_empty[-1], "low"
    if len(non_empty) == 1:
        return None, non_empty[0], "low"

    return None, None, "none"


# ─── Manifest Builder ────────────────────────────────────────────────────

def build_manifest(pkg_dir):
    """Scan a source package directory and build a package manifest.

    Returns (manifest_dict, warnings_list, needs_user_input_dict).
    """
    pkg = Path(pkg_dir)
    warnings = []
    needs_input = {}

    if not pkg.is_dir():
        return None, [f"Package directory does not exist: {pkg}"], {"package_dir": str(pkg)}

    # Find all TTL files
    ttl_files = sorted(pkg.rglob("*.ttl"))
    if not ttl_files:
        return None, [f"No TTL files found in {pkg}"], {}

    # Classify each file
    file_results = []
    for f in ttl_files:
        rel = f.relative_to(pkg)
        result = classify_ttl_file(f)
        result["relativePath"] = str(rel).replace("\\", "/")
        file_results.append(result)
        if result["error"]:
            warnings.append(f"Parse error in {rel}: {result['error']}")

    # Analyze namespaces
    primary_ns, augmenting_ns, all_prefixes = analyze_namespaces(file_results)

    if primary_ns is None:
        warnings.append("Could not determine primary namespace — no owl:Class declarations found.")
        needs_input["primary_namespace"] = "No classes found. Please provide the primary namespace URI and prefix."

    # Infer org/source
    org, source, confidence = (None, None, "none")
    if primary_ns:
        org, source, confidence = infer_org_source(primary_ns["uri"])

    if org is None:
        needs_input["organization"] = "Could not infer organization from namespace URI."
    if source is None:
        needs_input["source"] = "Could not infer source from namespace URI."

    # Group files by classification
    files_by_type = defaultdict(list)
    for fr in file_results:
        files_by_type[fr["classification"]].append(fr["relativePath"])

    # Build prefix map (for qname resolution)
    prefix_map = {}
    if primary_ns:
        prefix_map[primary_ns["uri"]] = primary_ns["prefix"] + ":"
    for aug in augmenting_ns:
        prefix_map[aug["uri"]] = aug["prefix"] + ":"

    # Build manifest
    manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "packageName": pkg.name,
        "packagePath": str(pkg).replace("\\", "/"),
        "namespaces": {
            "primary": primary_ns,
            "augmenting": augmenting_ns,
            "prefixMap": prefix_map,
        },
        "organization": org,
        "source": source,
        "orgDomainConfidence": confidence,
        "files": {
            "ontology": sorted(files_by_type.get("ontology", [])),
            "shapes": sorted(files_by_type.get("shapes", [])),
            "vocab": sorted(files_by_type.get("vocab", [])),
            "seedData": sorted(files_by_type.get("seed-data", [])),
            "aggregate": sorted(files_by_type.get("aggregate", [])),
            "unknown": sorted(files_by_type.get("unknown", [])),
            "parseError": sorted(files_by_type.get("parse-error", [])),
        },
        "stats": {
            "totalFiles": len(ttl_files),
            "ontologyFiles": len(files_by_type.get("ontology", [])),
            "shapeFiles": len(files_by_type.get("shapes", [])),
            "vocabFiles": len(files_by_type.get("vocab", [])),
            "seedDataFiles": len(files_by_type.get("seed-data", [])),
            "aggregateFiles": len(files_by_type.get("aggregate", [])),
            "classCount": primary_ns["classCount"] if primary_ns else 0,
            "augmentingNamespaces": len(augmenting_ns),
        },
    }

    # Warnings for suspicious results
    if not files_by_type.get("ontology"):
        warnings.append("No ontology files detected (no owl:Class declarations found).")
    if not files_by_type.get("shapes"):
        warnings.append("No SHACL shape files detected — structural validation and property assignment will be weaker.")
    if not files_by_type.get("vocab"):
        warnings.append("No SKOS vocabulary files detected — no codelists will be extracted.")
    if files_by_type.get("unknown"):
        warnings.append(f"Unclassified files: {', '.join(files_by_type['unknown'])}")
    if files_by_type.get("parse-error"):
        warnings.append(f"Files with parse errors: {', '.join(files_by_type['parse-error'])}")

    return manifest, warnings, needs_input


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build package manifest for a source package")
    parser.add_argument("--package", default=None, help="Path to source package directory")
    args = parser.parse_args()

    if args.package:
        pkg_dir = args.package
    else:
        print("Error: --package is required.", file=sys.stderr)
        sys.exit(1)

    pkg = Path(pkg_dir)
    print(f"\n  Scanning package: {pkg}")

    manifest, warnings, needs_input = build_manifest(pkg_dir)

    if manifest is None:
        print(f"\n  ERROR: Could not build manifest.")
        for w in warnings:
            print(f"    ! {w}")
        sys.exit(1)

    # Print summary
    ns = manifest["namespaces"]
    print(f"  Package: {manifest['packageName']}")
    if ns["primary"]:
        print(f"  Primary namespace: {ns['primary']['prefix']}: <{ns['primary']['uri']}> ({ns['primary']['classCount']} classes)")
    for aug in ns.get("augmenting", []):
        print(f"  Augmenting: {aug['prefix']}: <{aug['uri']}> ({aug['classCount']} classes)")
    print(f"  Organization: {manifest['organization'] or '???'} (confidence: {manifest['orgDomainConfidence']})")
    print(f"  Source: {manifest['source'] or '???'} (confidence: {manifest['orgDomainConfidence']})")
    print(f"  Files: {manifest['stats']['totalFiles']} total")
    for ftype in ["ontology", "shapes", "vocab", "seedData", "aggregate"]:
        files = manifest["files"][ftype]
        if files:
            print(f"    {ftype}: {len(files)} — {', '.join(files)}")

    if warnings:
        print(f"\n  Warnings:")
        for w in warnings:
            print(f"    ! {w}")

    if needs_input:
        print(f"\n  Needs user input:")
        for key, reason in needs_input.items():
            print(f"    ? {key}: {reason}")

    # Save manifest
    out_path = pkg / "package-manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\n  Saved: {out_path}")

    return manifest, warnings, needs_input


if __name__ == "__main__":
    main()
