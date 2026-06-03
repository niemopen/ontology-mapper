#!/usr/bin/env python3
"""Pre-flight inspection of target ontology reference specs.

Run this before the first matching step of any pipeline run to understand
the available reference data, its structure, and how to use it.

Usage:
    python runner_tools/preflight_specs.py --target-ontology niem --target-version 6.0

Output: A structured report of all specs files, their schemas, sizes,
and intended usage.
"""

import json
import sys
from pathlib import Path


def find_specs_dir():
    """Locate the specs directory from the installed ontology-mapper package."""
    try:
        from ontology_mapper.run_dir_utils import resolve_specs_dir
        return resolve_specs_dir()
    except ImportError:
        print("Error: ontology-mapper package not installed.")
        print("Install with: pip install -e ../mapper")
        return None


def inspect_type_directory(path):
    """Inspect the type directory file and report its structure."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header_lines = [l for l in lines if l.startswith("#")]
    data_lines = [l for l in lines if l and not l.startswith("#")]

    # Parse a sample entry to show format
    sample = data_lines[0] if data_lines else ""
    fields = [f.strip() for f in sample.split("|")]

    # Count by pattern
    patterns = {}
    namespaces = set()
    for line in data_lines:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            ns = parts[0].split(":")[0] if ":" in parts[0] else "?"
            namespaces.add(ns)
            pattern = parts[2]
            patterns[pattern] = patterns.get(pattern, 0) + 1

    return {
        "file": str(path),
        "totalLines": len(data_lines),
        "headerLines": header_lines,
        "format": "qname | baseType | pattern | propCount | definition | topProperties",
        "sampleEntry": sample[:200],
        "fieldCount": len(fields),
        "namespaces": sorted(namespaces),
        "namespaceCount": len(namespaces),
        "patternCounts": dict(sorted(patterns.items())),
    }


def inspect_catalog_summary(path):
    """Inspect the catalog summary and report its structure."""
    data = json.loads(path.read_text(encoding="utf-8"))

    ns_info = {}
    for ns, ns_data in data.get("namespaces", {}).items():
        types = ns_data.get("types", [])
        ns_info[ns] = {
            "label": ns_data.get("label", ""),
            "typeCount": len(types),
        }

    # Show structure of a type entry
    sample_type = None
    for ns_data in data.get("namespaces", {}).values():
        types = ns_data.get("types", [])
        if types:
            sample_type = {k: type(v).__name__ for k, v in types[0].items()}
            break

    return {
        "file": str(path),
        "version": data.get("version", "?"),
        "stats": data.get("stats", {}),
        "namespaces": ns_info,
        "typeEntrySchema": sample_type,
    }


def inspect_reference_catalog(path):
    """Inspect the full reference catalog and report its structure."""
    data = json.loads(path.read_text(encoding="utf-8"))

    top_keys = list(data.keys())

    # Types structure
    types = data.get("types", [])
    type_schema = None
    if types:
        type_schema = {}
        for k, v in types[0].items():
            if isinstance(v, list) and v:
                type_schema[k] = f"list[{type(v[0]).__name__}] ({len(v)} items)"
            elif isinstance(v, dict):
                type_schema[k] = f"dict ({len(v)} keys)"
            else:
                type_schema[k] = type(v).__name__

    # Property index structure
    pi = data.get("propertyIndex", {})
    pi_namespaces = list(pi.keys())
    pi_total = sum(len(ns.get("properties", [])) for ns in pi.values())
    pi_sample = None
    for ns_data in pi.values():
        props = ns_data.get("properties", [])
        if props:
            pi_sample = {k: type(v).__name__ for k, v in props[0].items()}
            break

    # Augmentation map structure
    aug = data.get("augmentationMap", {})
    aug_sample = None
    if aug:
        first_key = list(aug.keys())[0]
        first_val = aug[first_key]
        aug_sample = {
            "exampleBaseType": first_key,
            "structure": {k: type(v).__name__ for k, v in first_val.items()} if isinstance(first_val, dict) else type(first_val).__name__,
        }

    return {
        "file": str(path),
        "version": data.get("version", "?"),
        "description": data.get("description", ""),
        "topLevelKeys": top_keys,
        "stats": data.get("stats", {}),
        "namespaces": list(data.get("namespaces", {}).keys()),
        "typeCount": len(types),
        "typeEntrySchema": type_schema,
        "propertyIndex": {
            "namespaces": pi_namespaces,
            "totalProperties": pi_total,
            "propertyEntrySchema": pi_sample,
        },
        "augmentationMap": {
            "totalBaseTypes": len(aug),
            "sample": aug_sample,
        },
    }


def main():
    import argparse, sys, io
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    elif not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="Pre-flight inspection of target ontology reference specs")
    parser.add_argument("--target-ontology", required=True, help="Target ontology name (e.g. niem, sali-folio, nods)")
    parser.add_argument("--target-version", required=True, help="Target ontology version (e.g. 6.0, 2.0, 1.0)")
    args = parser.parse_args()
    ontology = args.target_ontology
    version = args.target_version

    specs_dir = find_specs_dir()
    if not specs_dir:
        print("ERROR: Cannot locate specs directory.")
        sys.exit(1)

    print(f"=== {ontology} {version} Specs Pre-Flight ===")
    print(f"Specs directory: {specs_dir}")
    print()

    # List all files
    all_files = sorted(specs_dir.glob(f"*{ontology}*{version}*"))
    if not all_files:
        # Fallback: try just version match
        all_files = sorted(specs_dir.glob(f"*{version}*"))
    print(f"Available files for {ontology} {version}:")
    for f in all_files:
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name}  ({size_kb:.0f} KB)")
    print()

    # Inspect each file type (generic pattern: {ontology}_*_{version}.ext)
    td_path = specs_dir / f"{ontology}_type_directory_{version}.txt"
    cs_path = specs_dir / f"{ontology}_catalog_summary_{version}.json"
    rc_path = specs_dir / f"{ontology}_reference_catalog_{version}.json"

    if td_path.exists():
        print("--- Type Directory ---")
        info = inspect_type_directory(td_path)
        print(f"  Total types: {info['totalLines']}")
        print(f"  Format: {info['format']}")
        print(f"  Namespaces ({info['namespaceCount']}): {', '.join(info['namespaces'])}")
        print(f"  Pattern counts: {info['patternCounts']}")
        print(f"  Usage: Compact one-line-per-type for efficient full-catalog scanning.")
        print(f"         Read the ENTIRE file to scan all types for a source concept.")
        print(f"  Sample: {info['sampleEntry']}")
        print()

    if cs_path.exists():
        print("--- Catalog Summary ---")
        info = inspect_catalog_summary(cs_path)
        print(f"  Stats: {json.dumps(info['stats'])}")
        print(f"  Namespaces:")
        for ns, ns_info in sorted(info["namespaces"].items()):
            print(f"    {ns}: {ns_info['label']} ({ns_info['typeCount']} types)")
        print(f"  Type entry fields: {info['typeEntrySchema']}")
        print(f"  Usage: Namespace-grouped types with property lists.")
        print(f"         Use for deeper inspection after identifying candidates")
        print(f"         from the type directory.")
        print()

    if rc_path.exists():
        print("--- Reference Catalog ---")
        info = inspect_reference_catalog(rc_path)
        print(f"  Description: {info['description'][:150]}")
        print(f"  Stats: {json.dumps(info['stats'], indent=4)}")
        print(f"  Top-level keys: {info['topLevelKeys']}")
        print(f"  Type entry fields: {info['typeEntrySchema']}")
        print(f"  Property index: {info['propertyIndex']['totalProperties']} properties across {info['propertyIndex']['namespaces']}")
        print(f"  Property entry fields: {info['propertyIndex']['propertyEntrySchema']}")
        print(f"  Augmentation map: {info['augmentationMap']['totalBaseTypes']} base types")
        if info["augmentationMap"]["sample"]:
            print(f"  Aug sample: {info['augmentationMap']['sample']}")
        print(f"  Usage: Full catalog with property definitions, type hierarchy,")
        print(f"         augmentation map, and cross-namespace property index.")
        print(f"         Use for property-level semantic matching.")
        print()

    print("=== Recommended Matching Workflow ===")
    print("  Class-level:    Read type directory (full scan per concept)")
    print("  Property-level: Read reference catalog (property definitions,")
    print("                  augmentation map, property index)")
    print("  Both levels:    ALL matching by LLM semantic reasoning.")
    print("                  NO keyword filtering, scoring, or heuristics.")


if __name__ == "__main__":
    main()
