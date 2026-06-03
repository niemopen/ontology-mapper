#!/usr/bin/env python3
"""CSV-based source domain ingestion: tabular data model → concept-inventory.json.

Takes a CSV file describing a source data model (classes, attributes, types,
multiplicities, definitions) and produces concept-inventory.json matching the
Stage 2 output schema. Stages 3-8 work unchanged.

Designed for data models like the NCSC court data model (NODS INPUT.csv) where
the source vocabulary is independent of NIEM and needs to be aligned against it.

CSV format expected:
    Model Class, Model Attribute, Model Type, Model Multiplicity, Model Definition

Row conventions:
    - Class row: Model Attribute is empty (defines a class)
    - Datatype property: Model Attribute + primitive Model Type (string, date, etc.)
    - Object property: Model Attribute in parentheses like (Charges) → reference to another class

Usage:
    om-ingest-csv "path/to/INPUT.csv"
    om-ingest-csv INPUT.csv --namespace court
    om-ingest-csv INPUT.csv --namespace court --run-dir .mapper-runs/{run_id}
    om-ingest-csv INPUT.csv --output runs/out/concept-inventory.json
"""

import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

# Primitive types that map to datatype properties (everything else is a class reference)
PRIMITIVE_TYPES = {"string", "date", "bool", "amount", "float", "int",
                   "dateTime", "short", "id", "double", "integer", "decimal",
                   "boolean", "time", "duration", "long", "byte"}

# Map source types to XSD-like types for range values
TYPE_TO_XSD = {
    "string": "xs:string",
    "date": "xs:date",
    "bool": "xs:boolean",
    "boolean": "xs:boolean",
    "amount": "xs:decimal",
    "float": "xs:float",
    "double": "xs:double",
    "int": "xs:integer",
    "integer": "xs:integer",
    "short": "xs:short",
    "long": "xs:long",
    "byte": "xs:byte",
    "dateTime": "xs:dateTime",
    "time": "xs:time",
    "duration": "xs:duration",
    "decimal": "xs:decimal",
    "id": "xs:string",
}


# ─── CSV Parsing ─────────────────────────────────────────────────────────

def parse_csv(csv_path):
    """Parse INPUT.csv into structured class/attribute records.

    Returns:
        classes: dict of {class_name: {definition, attributes: [...], object_refs: [...]}}
    """
    classes = {}
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cls_name = row.get("Model Class", "").strip()
            attr_name = row.get("Model Attribute", "").strip()
            mtype = row.get("Model Type", "").strip()
            mult = row.get("Model Multiplicity", "").strip()
            defn = row.get("Model Definition", "").strip()

            if not cls_name:
                continue

            # Ensure class entry exists
            if cls_name not in classes:
                classes[cls_name] = {
                    "definition": "",
                    "attributes": [],
                    "object_refs": [],
                }

            if not attr_name:
                # Class-level row — capture definition if present
                if defn:
                    classes[cls_name]["definition"] = defn
                continue

            # Parenthesized reference → object property (e.g., "(Charges)")
            paren_match = re.match(r"^\((.+)\)$", attr_name)
            if paren_match:
                ref_name = paren_match.group(1)
                classes[cls_name]["object_refs"].append({
                    "ref_name": ref_name,
                    "multiplicity": mult,
                    "definition": defn,
                })
                continue

            # Check if type is a class reference (non-primitive)
            if mtype and mtype.lower() not in PRIMITIVE_TYPES and mtype in classes:
                classes[cls_name]["object_refs"].append({
                    "ref_name": mtype,
                    "multiplicity": mult,
                    "definition": defn,
                    "property_name": attr_name,
                })
                continue

            # Regular datatype attribute
            classes[cls_name]["attributes"].append({
                "name": attr_name,
                "type": mtype,
                "multiplicity": mult,
                "definition": _clean_definition(defn),
            })

    return classes


def _clean_definition(defn):
    """Strip Element# and User Story boilerplate from definitions."""
    if not defn:
        return ""
    # Remove Element# lines and User Story: markers
    lines = defn.split("\n")
    cleaned = []
    for line in lines:
        line = line.strip()
        if line.startswith("Element#"):
            continue
        if line == "User Story:":
            continue
        if line.startswith("User Story: "):
            # Keep the story text if present
            story = line[len("User Story: "):].strip()
            if story:
                cleaned.append(story)
            continue
        if line:
            cleaned.append(line)
    return " ".join(cleaned).strip()


# ─── Multiplicity Parsing ────────────────────────────────────────────────

def parse_multiplicity(mult_str):
    """Parse multiplicity string into (minCount, maxCount).

    Examples: "1" → (1,1), "0..1" → (0,1), "*" → (0,None), "1..*" → (1,None)
    """
    if not mult_str:
        return (0, None)
    mult_str = mult_str.strip()
    if mult_str == "*":
        return (0, None)
    if ".." in mult_str:
        parts = mult_str.split("..", 1)
        lo = int(parts[0])
        hi = None if parts[1] == "*" else int(parts[1])
        return (lo, hi)
    try:
        n = int(mult_str)
        return (n, n)
    except ValueError:
        return (0, None)


# ─── IRI Synthesis ────────────────────────────────────────────────────────

def make_class_iri(ns_uri, class_name):
    return f"{ns_uri}#{class_name}"


def make_property_iri(ns_uri, class_name, prop_name):
    return f"{ns_uri}#{class_name}.{prop_name}"


def make_qname(prefix, name):
    return f"{prefix}:{name}"


# ─── Transform to concept-inventory ──────────────────────────────────────

def build_concept_inventory(classes, csv_path, namespace_prefix,
                            namespace_uri):
    """Transform parsed CSV classes into concept-inventory.json structure."""

    class_entries = []
    object_properties = []
    datatype_properties = []
    shacl_shapes = []

    class_names = set(classes.keys())

    for cls_name, cls_data in sorted(classes.items()):
        cls_qname = make_qname(namespace_prefix, cls_name)
        cls_iri = make_class_iri(namespace_uri, cls_name)

        # ── Class entry ──
        class_entries.append({
            "iri": cls_iri,
            "qname": cls_qname,
            "label": cls_name,
            "comment": cls_data["definition"],
            "subClassOf": [],
        })

        # ── SHACL shape for this class ──
        shape_properties = []

        # Datatype attributes → datatype properties + shape entries
        for attr in cls_data["attributes"]:
            prop_qname = make_qname(namespace_prefix, attr["name"])
            prop_iri = make_property_iri(namespace_uri, cls_name, attr["name"])
            min_c, max_c = parse_multiplicity(attr["multiplicity"])
            xsd_type = TYPE_TO_XSD.get(attr["type"].lower(), "xs:string") if attr["type"] else "xs:string"

            datatype_properties.append({
                "iri": prop_iri,
                "qname": prop_qname,
                "label": attr["name"],
                "comment": attr["definition"],
                "domain": [cls_qname],
                "range": [xsd_type],
            })

            shape_properties.append({
                "path": prop_qname,
                "minCount": min_c,
                "maxCount": max_c,
                "datatype": xsd_type,
                "class": None,
            })

        # Object references → object properties + shape entries
        for ref in cls_data["object_refs"]:
            ref_name = ref["ref_name"]
            prop_name = ref.get("property_name", ref_name)
            prop_qname = make_qname(namespace_prefix, prop_name)
            prop_iri = make_property_iri(namespace_uri, cls_name, prop_name)
            min_c, max_c = parse_multiplicity(ref["multiplicity"])

            # Resolve target class name (handle minor typos like HearingAndEvents → HearingsAndEvents)
            target_cls = ref_name
            if target_cls not in class_names:
                # Try fuzzy match for minor singular/plural differences
                for cn in class_names:
                    if cn.lower().replace("s", "") == target_cls.lower().replace("s", ""):
                        target_cls = cn
                        break

            target_qname = make_qname(namespace_prefix, target_cls)
            target_iri = make_class_iri(namespace_uri, target_cls)

            object_properties.append({
                "iri": prop_iri,
                "qname": prop_qname,
                "label": prop_name,
                "comment": ref.get("definition", ""),
                "domain": [cls_qname],
                "range": [target_qname],
            })

            shape_properties.append({
                "path": prop_qname,
                "minCount": min_c,
                "maxCount": max_c,
                "datatype": None,
                "class": target_qname,
            })

        if shape_properties:
            shacl_shapes.append({
                "iri": f"{namespace_uri}#{cls_name}Shape",
                "targetClass": cls_qname,
                "propertyCount": len(shape_properties),
                "properties": shape_properties,
            })

    # Deduplicate properties that appear in multiple classes
    # (same attribute name may appear on different classes — keep all with merged domains)
    datatype_properties = _merge_property_domains(datatype_properties)
    object_properties = _merge_property_domains(object_properties)

    inventory = {
        "extractedAt": datetime.now(timezone.utc).isoformat(),
        "sourcePackage": str(csv_path),
        "primaryNamespace": {
            "prefix": namespace_prefix,
            "uri": namespace_uri,
        },
        "namespaceMap": {
            namespace_uri: namespace_prefix + ":",
        },
        "summary": {
            "classCount": len(class_entries),
            "objectPropertyCount": len(object_properties),
            "datatypePropertyCount": len(datatype_properties),
            "codelistSchemeCount": 0,
            "totalCodelistConcepts": 0,
            "workflowModelCount": 0,
            "totalWorkflowStates": 0,
            "totalWorkflowTransitions": 0,
            "shaclShapeCount": len(shacl_shapes),
            "augmentingNamespaceCount": 0,
        },
        "classes": class_entries,
        "objectProperties": object_properties,
        "datatypeProperties": datatype_properties,
        "codelistSchemes": [],
        "workflowModels": [],
        "shaclShapes": shacl_shapes,
        "augmentingNamespaces": [],
    }
    return inventory


def _merge_property_domains(props):
    """Merge properties with the same qname by combining their domains."""
    by_qname = {}
    for p in props:
        qn = p["qname"]
        if qn in by_qname:
            # Merge domains
            existing = by_qname[qn]
            for d in p["domain"]:
                if d not in existing["domain"]:
                    existing["domain"].append(d)
            # Merge ranges
            for r in p["range"]:
                if r not in existing["range"]:
                    existing["range"].append(r)
        else:
            by_qname[qn] = p
    return sorted(by_qname.values(), key=lambda p: p["qname"])


# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest a CSV source data model into concept-inventory.json")
    parser.add_argument("csv_file", help="Path to INPUT.csv")
    parser.add_argument("--namespace", required=True,
                        help="Namespace prefix for source concepts (e.g. dbpi, nods)")
    parser.add_argument("--namespace-uri", required=True,
                        help="Namespace URI for source concepts (e.g. urn:dbpi-model)")
    parser.add_argument("--run-dir", default=None,
                        help="Run directory (default: auto-resolve most recent)")
    parser.add_argument("--output", "-o",
                        help="Output path (overrides --run-dir auto-resolution)")
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"Error: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    classes = parse_csv(csv_path)
    inventory = build_concept_inventory(
        classes, csv_path,
        namespace_prefix=args.namespace,
        namespace_uri=args.namespace_uri,
    )

    output = json.dumps(inventory, indent=2)
    if args.output:
        out_path = Path(args.output)
    else:
        if not args.run_dir:
            print("Error: --run-dir is required.", file=sys.stderr)
            raise SystemExit(1)
        run_dir = Path(args.run_dir)
        out_path = run_dir / "concept-inventory.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(f"Wrote {out_path}: {inventory['summary']['classCount']} classes, "
          f"{inventory['summary']['objectPropertyCount']} object properties, "
          f"{inventory['summary']['datatypePropertyCount']} datatype properties, "
          f"{inventory['summary']['shaclShapeCount']} shapes",
          file=sys.stderr)


if __name__ == "__main__":
    main()
