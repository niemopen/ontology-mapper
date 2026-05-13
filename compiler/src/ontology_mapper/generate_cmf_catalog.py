#!/usr/bin/env python3
"""Generate a reference catalog from a CMF (Common Model Format) XML file.

Parses CMF XML — the OASIS standard for NIEM model exchange — into the same
catalog JSON structure used by vector indexing and semantic search. Optionally
enriches with Genericode (.gc) codelist files for enumeration values.

Designed for NIEM message specifications (extension schemas) like NODS, but
works with any CMF file. The resulting catalog enables the ontology to serve
as a target for source domain alignment.

Data sources:
  CMF XML file:
    - Namespaces, classes (types), properties, inheritance
    - Property memberships with cardinalities (MinOccurs/MaxOccurs)
    - Augmentation records linking properties to augmented types
    - Property definitions and datatype/range information

  Genericode (.gc) codelist files (optional):
    - Enumeration values for code-type types
    - Codelist names, URIs, and optional value definitions

Usage:
    om-generate-cmf-catalog --input nods.cmf --name nods --version 1.0
    om-generate-cmf-catalog --input nods.cmf --codelists codelists/ --name nods --version 1.0
    om-generate-cmf-catalog --input nods.cmf --name nods --version 1.0 --force
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from ontology_mapper.owl_cmf_bridge import (
    CmfModel,
    CmfXmlParser,
    set_niem_version,
)


# ─── Helpers ─────────────────────────────────────────────────────────────

def _cmf_id_to_qname(cmf_id: str) -> str:
    """Convert CMF dot-notation ID to colon-separated qname.

    'nods.ChargeType' -> 'nods:ChargeType'
    'xs.string' -> 'xs:string'
    '' -> ''
    """
    if not cmf_id:
        return ""
    parts = cmf_id.split(".", 1)
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    return cmf_id


PATTERN_SUFFIXES = [
    ("AugmentationType", "augmentation"),
    ("AssociationType", "association"),
    ("MetadataType", "metadata"),
    ("AdapterType", "adapter"),
    ("CodeSimpleType", "simple_value"),
    ("CodeType", "simple_value"),
    ("SimpleType", "simple_value"),
]


def _classify_pattern(class_name: str) -> str:
    """Infer NIEM type pattern from naming conventions."""
    for suffix, pattern in PATTERN_SUFFIXES:
        if class_name.endswith(suffix):
            return pattern
    return "object"


# ─── Genericode (.gc) Parsing ────────────────────────────────────────────

GC_NS = {"gc": "http://docs.oasis-open.org/codelist/ns/genericode/1.0/"}


def parse_genericode_file(gc_path: Path) -> tuple[str, list[dict]]:
    """Parse a single .gc file into (codelist_name, [{value, definition}]).

    Returns the ShortName and a list of enumeration entries.
    Uses a recovery parser to handle unescaped & in code values.
    """
    parser = etree.XMLParser(recover=True)
    tree = etree.parse(str(gc_path), parser)
    root = tree.getroot()

    # .gc files may use namespace-prefixed or unprefixed child elements.
    # Try both: first with gc namespace, then without.
    def _find(el, path):
        result = el.find(path, GC_NS)
        if result is None:
            # Try without namespace (unprefixed children)
            result = el.find(path.replace("gc:", ""))
        return result

    def _findall(el, path):
        result = el.findall(path, GC_NS)
        if not result:
            result = el.findall(path.replace("gc:", ""))
        return result

    def _findtext(el, path, default=""):
        result = el.findtext(path, default=None, namespaces=GC_NS)
        if result is None:
            result = el.findtext(path.replace("gc:", ""), default=default)
        return result or default

    short_name_el = _find(root, ".//gc:Identification/gc:ShortName")
    short_name = (short_name_el.text or "").strip() if short_name_el is not None else gc_path.stem

    # Discover column refs from ColumnSet
    code_col = "code"
    def_col = "definition"
    for col in _findall(root, ".//gc:ColumnSet/gc:Column"):
        col_id = col.get("Id", "")
        uri = _findtext(col, "gc:CanonicalUri")
        if "column/code" in uri:
            code_col = col_id
        elif "column/definition" in uri:
            def_col = col_id

    values = []
    for row in _findall(root, ".//gc:SimpleCodeList/gc:Row"):
        code_val = ""
        def_val = ""
        for val_el in _findall(row, "gc:Value"):
            col_ref = val_el.get("ColumnRef", "")
            simple = _findtext(val_el, "gc:SimpleValue")
            if col_ref == code_col:
                code_val = simple.strip()
            elif col_ref == def_col:
                def_val = simple.strip()
        if code_val:
            values.append({"value": code_val, "definition": def_val})

    return short_name, sorted(values, key=lambda v: v["value"])


def load_codelists(codelists_dir: Path) -> dict[str, list[dict]]:
    """Load all .gc files from a directory.

    Returns: {codelist_short_name: [{value, definition}, ...]}
    """
    codelists = {}
    gc_files = sorted(codelists_dir.glob("*.gc"))
    total_values = 0
    for gc_file in gc_files:
        try:
            name, values = parse_genericode_file(gc_file)
            if values:
                codelists[name] = values
                total_values += len(values)
        except Exception as e:
            print(f"    WARNING: Failed to parse {gc_file.name}: {e}")
    print(f"    {len(gc_files)} .gc files, {len(codelists)} with values, "
          f"{total_values} total enumeration values")
    return codelists


# ─── CMF → Catalog Transform ────────────────────────────────────────────

def extract_namespaces(model: CmfModel) -> dict[str, dict]:
    """Build namespace map from CmfModel.namespaces."""
    ns_map = {}
    for ns in model.namespaces:
        ns_map[ns.prefix] = {
            "prefix": ns.prefix,
            "uri": ns.uri,
            "category": ns.category,
            "documentation": ns.documentation,
        }
    return ns_map


def extract_types(model: CmfModel) -> list[dict]:
    """Transform CmfModel.classes into catalog type entries."""
    # Build property lookup for definitions and type info
    prop_lookup = {p.prop_id: p for p in model.properties}

    types = []
    for cls in model.classes:
        qname = _cmf_id_to_qname(cls.class_id)
        base_type = _cmf_id_to_qname(cls.sub_class_of) or None
        pattern = _classify_pattern(cls.name)

        # Extract property names from ChildPropertyAssociations
        properties = []
        cardinalities = {}
        prop_definitions = {}

        for hp in cls.properties:
            prop = prop_lookup.get(hp.property_ref)
            prop_name = prop.name if prop else hp.property_ref.split(".")[-1]
            properties.append(prop_name)

            # Cardinalities
            max_occ = hp.max_occurs
            cardinalities[prop_name] = {
                "minOccurs": str(hp.min_occurs),
                "maxOccurs": max_occ,
            }

            # Property definitions
            if prop and prop.documentation:
                prop_def = {"definition": prop.documentation}
                if prop.is_object and prop.class_ref:
                    prop_def["qualifiedType"] = _cmf_id_to_qname(prop.class_ref)
                elif prop.datatype_ref:
                    prop_def["qualifiedType"] = _cmf_id_to_qname(prop.datatype_ref)
                prop_definitions[prop_name] = prop_def

        is_aug = pattern == "augmentation"

        types.append({
            "qname": qname,
            "definition": cls.documentation,
            "baseType": base_type,
            "pattern": pattern,
            "properties": properties,
            "contentStyle": "HasProperty" if properties else "",
            "isAugmentation": is_aug,
            "isAdapter": pattern == "adapter",
            "isMetadata": pattern == "metadata",
            "propertyCardinalities": cardinalities,
            "propertyDefinitions": prop_definitions,
            "inheritanceChain": [],  # filled in later
        })

    types.sort(key=lambda t: t["qname"])
    return types


def extract_properties(model: CmfModel, types: list[dict]) -> list[dict]:
    """Transform CmfModel.properties into property index entries."""
    # Build reverse map: prop_id → list of containing type qnames
    containing_map = defaultdict(list)
    for cls in model.classes:
        cls_qname = _cmf_id_to_qname(cls.class_id)
        for hp in cls.properties:
            containing_map[hp.property_ref].append(cls_qname)

    properties = []
    for prop in model.properties:
        prefix = prop.namespace_ref
        qualified = _cmf_id_to_qname(prop.prop_id)

        if prop.is_object and prop.class_ref:
            qualified_type = _cmf_id_to_qname(prop.class_ref)
        elif prop.datatype_ref:
            qualified_type = _cmf_id_to_qname(prop.datatype_ref)
        else:
            qualified_type = ""

        properties.append({
            "name": prop.name,
            "qualifiedProperty": qualified,
            "definition": prop.documentation,
            "qualifiedType": qualified_type,
            "isAbstract": prop.is_abstract,
            "containingTypes": containing_map.get(prop.prop_id, []),
            "substitutionGroup": _cmf_id_to_qname(prop.sub_property_of) or None,
            "namespace": prefix,
        })

    properties.sort(key=lambda p: p["qualifiedProperty"])
    return properties


def build_property_index(properties: list[dict]) -> dict:
    """Group properties by namespace prefix."""
    by_ns = defaultdict(list)
    for p in properties:
        ns = p.get("namespace", "")
        entry = {
            "name": p["name"],
            "qualifiedProperty": p["qualifiedProperty"],
            "definition": p["definition"],
            "qualifiedType": p["qualifiedType"],
            "isAbstract": p["isAbstract"],
            "containingTypes": p["containingTypes"],
        }
        if p.get("substitutionGroup"):
            entry["substitutionGroup"] = p["substitutionGroup"]
        by_ns[ns].append(entry)

    return {
        ns: {"properties": props, "propertyCount": len(props)}
        for ns, props in sorted(by_ns.items())
    }


def build_inheritance_chains(types: list[dict]) -> None:
    """Compute inheritance chains in-place on type entries."""
    by_qname = {t["qname"]: t for t in types}

    for t in types:
        chain = []
        visited = set()
        current = t["baseType"]
        while current and current not in visited:
            visited.add(current)
            chain.append(current)
            parent = by_qname.get(current)
            current = parent["baseType"] if parent else None
        t["inheritanceChain"] = list(reversed(chain))


def build_augmentation_map(model: CmfModel) -> dict:
    """Build augmentation map from CmfNamespace.augmentations."""
    prop_lookup = {p.prop_id: p for p in model.properties}
    aug_map = defaultdict(lambda: {"augProperties": []})

    for ns in model.namespaces:
        for aug in ns.augmentations:
            base_qname = _cmf_id_to_qname(aug.class_ref)
            prop_qname = _cmf_id_to_qname(aug.property_ref)
            prop = prop_lookup.get(aug.property_ref)
            prop_name = prop.name if prop else aug.property_ref.split(".")[-1]

            aug_map[base_qname]["augProperties"].append({
                "qualifiedProperty": prop_qname,
                "name": prop_name,
                "minOccurs": str(aug.min_occurs),
                "maxOccurs": aug.max_occurs,
            })

    return dict(aug_map)


def enrich_with_codelists(types: list[dict], codelists: dict) -> int:
    """Match codelist data to simple_value types by naming convention.

    Tries: exact match on local name, then ShortName + "CodeSimpleType",
    then ShortName + "CodeType".

    Returns count of types enriched.
    """
    if not codelists:
        return 0

    # Build lookup by local name
    type_by_local = {}
    for t in types:
        local = t["qname"].split(":")[-1] if ":" in t["qname"] else t["qname"]
        type_by_local[local] = t

    enriched = 0
    for cl_name, values in codelists.items():
        # Try matching conventions
        candidates = [
            cl_name,
            cl_name + "CodeSimpleType",
            cl_name + "CodeType",
            cl_name + "SimpleType",
        ]
        for candidate in candidates:
            if candidate in type_by_local:
                type_by_local[candidate]["facets"] = values
                enriched += 1
                break

    return enriched


# ─── Definition Quality Report ───────────────────────────────────────────

def definition_quality_report(types: list[dict], properties: list[dict],
                              name: str) -> dict:
    """Report definition coverage metrics."""
    type_total = len(types)
    type_with_def = sum(1 for t in types if t["definition"])
    type_def_lens = [len(t["definition"]) for t in types if t["definition"]]
    type_avg = round(sum(type_def_lens) / len(type_def_lens)) if type_def_lens else 0

    prop_total = len(properties)
    prop_with_def = sum(1 for p in properties if p["definition"])
    prop_def_lens = [len(p["definition"]) for p in properties if p["definition"]]
    prop_avg = round(sum(prop_def_lens) / len(prop_def_lens)) if prop_def_lens else 0

    # Duplicates
    def_counts = defaultdict(int)
    for t in types:
        if t["definition"]:
            def_counts[t["definition"]] += 1
    for p in properties:
        if p["definition"]:
            def_counts[p["definition"]] += 1
    duplicates = {d: n for d, n in def_counts.items() if n > 1}

    missing_types = [t["qname"] for t in types if not t["definition"]]
    missing_props = [p["qualifiedProperty"] for p in properties if not p["definition"]]

    shortest = sorted(
        [(t["qname"], t["definition"]) for t in types if t["definition"]]
        + [(p["qualifiedProperty"], p["definition"]) for p in properties if p["definition"]],
        key=lambda x: len(x[1])
    )[:5]

    report = {
        "ontology": name,
        "types": {
            "total": type_total,
            "withDefinitions": type_with_def,
            "coveragePercent": round(100 * type_with_def / max(type_total, 1), 1),
            "avgDefinitionLength": type_avg,
            "missingCount": len(missing_types),
            "missingExamples": missing_types[:20],
        },
        "properties": {
            "total": prop_total,
            "withDefinitions": prop_with_def,
            "coveragePercent": round(100 * prop_with_def / max(prop_total, 1), 1),
            "avgDefinitionLength": prop_avg,
            "missingCount": len(missing_props),
            "missingExamples": missing_props[:20],
        },
        "duplicates": {
            "uniqueDuplicateDefinitions": len(duplicates),
            "totalAffectedEntries": sum(duplicates.values()),
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

    # Console output
    print(f"\n{'='*70}")
    print(f"  Definition Report: {name}")
    print(f"{'='*70}")
    print(f"\n  Types:      {type_total} total, {type_with_def} with definitions "
          f"({report['types']['coveragePercent']}%)")
    print(f"  Properties: {prop_total} total, {prop_with_def} with definitions "
          f"({report['properties']['coveragePercent']}%)")
    print(f"  Avg definition length: {type_avg} chars (types), "
          f"{prop_avg} chars (properties)")
    if duplicates:
        print(f"  Duplicates: {sum(duplicates.values())} entries share "
              f"{len(duplicates)} repeated definitions")
    if missing_types:
        print(f"\n  Types missing definitions ({len(missing_types)} total, first 10):")
        for qn in missing_types[:10]:
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
            trunc = f"{d[:80]}..." if len(d) > 80 else d
            print(f"    \"{trunc}\" ({n} times)")
    print(f"\n{'='*70}")

    return report


# ─── Catalog Assembly ────────────────────────────────────────────────────

def build_catalog(types, properties, namespace_map, augmentation_map,
                  property_index, name, version, source_files,
                  codelists_enriched):
    """Assemble the full catalog dict."""
    # Discover which patterns actually appear
    found_patterns = sorted(set(t["pattern"] for t in types))
    niem_pattern_descriptions = {
        "object": "Container types with properties. The primary matching targets for domain concepts.",
        "association": "Relationship types with role properties. Match when the source concept represents a relationship between entities.",
        "complex_value": "Structured value types. Match when the source concept is a structured value, not a standalone entity.",
        "simple_value": "Code tables and primitive wrappers. Match when the source concept is a constrained value set.",
        "simple_list": "Space-separated list types. Rarely direct matching targets.",
        "simple_union": "Union types. Rarely direct matching targets.",
        "metadata": "Metadata containers. Match when the source concept carries metadata about other data.",
        "augmentation": "Augmentation types. Not matchable targets — they contribute properties to base types via the augmentation map.",
        "adapter": "Adapter types that wrap external standards.",
    }
    type_patterns = {
        p: niem_pattern_descriptions.get(p, p)
        for p in found_patterns
    }

    stats = {
        "namespaces": len(namespace_map),
        "totalTypes": len(types),
        "typesWithProperties": sum(1 for t in types if t["properties"]),
        "totalPropertyMemberships": sum(len(t["properties"]) for t in types),
        "totalProperties": len(properties),
        "typesWithBaseType": sum(1 for t in types if t["baseType"]),
        "typesWithInheritanceChain": sum(1 for t in types if t["inheritanceChain"]),
        "augmentedTypes": len(augmentation_map),
        "totalAugmentedProperties": sum(
            len(v["augProperties"]) for v in augmentation_map.values()
        ),
        "codelistsEnriched": codelists_enriched,
        "patternCounts": {
            p: sum(1 for t in types if t["pattern"] == p)
            for p in found_patterns
        },
    }

    # Auto-detect default base type for extend-from-root scenarios.
    # NIEM-derived specs (NIEM itself, NODS, etc.) carry structures:ObjectType
    # as the ultimate root for object types.
    default_base_type = (
        "structures:ObjectType"
        if any(t["qname"] == "structures:ObjectType" for t in types)
        else None
    )

    catalog = {
        "version": version,
        "description": (
            f"{name} reference catalog for semantic ontology alignment. "
            f"Generated from CMF source on "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
            f"Source: {', '.join(Path(f).name for f in source_files)}."
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": source_files,
        "actions": {
            "reuse": "The source concept maps directly to an existing type. Use the target type as-is.",
            "extend": "The source concept requires a new extension type that inherits from a base type via rdfs:subClassOf.",
            "augment": "The source concept contributes properties to an existing type via an augmentation type, without subclassing.",
        },
        "defaultBaseType": default_base_type,
        "typePatterns": type_patterns,
        "stats": stats,
        "namespaces": {
            ns["prefix"]: ns["uri"]
            for ns in namespace_map.values()
        },
        "propertyIndex": property_index,
        "augmentationMap": augmentation_map,
        "types": types,
    }

    return catalog


def build_catalog_summary(types: list[dict]) -> dict:
    """Build a lightweight namespace-grouped summary."""
    by_ns = defaultdict(list)
    for t in types:
        ns = t["qname"].split(":")[0] if ":" in t["qname"] else "_"
        by_ns[ns].append({
            "qname": t["qname"],
            "definition": t["definition"],
            "baseType": t["baseType"],
            "properties": t["properties"][:10],
            "propertyCount": len(t["properties"]),
        })

    return {
        ns: {"label": ns, "types": by_ns[ns]}
        for ns in sorted(by_ns.keys())
    }


def build_type_directory(types: list[dict]) -> str:
    """Build a compact one-line-per-type directory."""
    lines = [
        "# Type Directory — one line per type for efficient semantic matching",
        "# Format: qname | baseType | pattern | propCount | definition | topProperties",
        f"# Total: {len(types)} types",
        "#",
    ]
    for t in sorted(types, key=lambda x: x["qname"]):
        base = t["baseType"] or "-"
        props = ", ".join(t["properties"][:8])
        defn = (t["definition"] or "")[:120]
        lines.append(
            f"{t['qname']} | {base} | {t['pattern']} | "
            f"{len(t['properties'])} | {defn} | {props}"
        )
    return "\n".join(lines) + "\n"


# ─── Pipeline ────────────────────────────────────────────────────────────

def generate(input_path: str, name: str, version: str,
             codelists_dir: str = None, niem_version: str = None,
             force: bool = False) -> Path:
    """Full generation pipeline. Returns path to reference catalog."""
    if not niem_version:
        raise ValueError("niem_version is required (e.g., '6.0')")

    from ontology_mapper.run_dir_utils import resolve_specs_dir

    specs_dir = resolve_specs_dir()
    output_path = specs_dir / f"{name}_reference_catalog_{version}.json"

    if output_path.exists() and not force:
        print(f"Catalog already exists: {output_path}")
        print("Use --force to overwrite.")
        sys.exit(1)

    input_file = Path(input_path)
    source_files = [str(input_file)]

    print(f"Generating CMF reference catalog for {name} v{version}")
    print(f"  Input: {input_file}")
    print(f"  NIEM version: {niem_version}")
    print(f"  Output: {output_path}")

    # Step 1: Parse CMF
    print(f"\nStep 1: Parsing CMF XML...")
    set_niem_version(niem_version)
    parser = CmfXmlParser()
    model = parser.parse(input_file)
    print(f"  Namespaces: {len(model.namespaces)}")
    print(f"  Classes: {len(model.classes)}")
    print(f"  Properties: {len(model.properties)}")
    print(f"  Restrictions: {len(model.restrictions)}")

    # Step 2: Extract namespaces
    print(f"\nStep 2: Extracting namespaces...")
    namespace_map = extract_namespaces(model)
    for prefix, info in sorted(namespace_map.items()):
        print(f"    {prefix}: {info['category']} — {info['uri']}")

    # Step 3: Extract and transform types
    print(f"\nStep 3: Extracting types...")
    types = extract_types(model)
    pattern_counts = defaultdict(int)
    for t in types:
        pattern_counts[t["pattern"]] += 1
    for pattern, count in sorted(pattern_counts.items()):
        print(f"    {pattern}: {count}")
    print(f"    Total: {len(types)} types, "
          f"{sum(1 for t in types if t['properties'])} with properties")

    # Step 4: Extract properties and build index
    print(f"\nStep 4: Extracting properties...")
    properties = extract_properties(model, types)
    property_index = build_property_index(properties)
    print(f"    {len(properties)} properties across "
          f"{len(property_index)} namespaces")

    # Step 5: Build inheritance chains
    print(f"\nStep 5: Building inheritance chains...")
    build_inheritance_chains(types)
    with_chain = sum(1 for t in types if t["inheritanceChain"])
    print(f"    {sum(1 for t in types if t['baseType'])}/{len(types)} types with baseType")
    print(f"    {with_chain}/{len(types)} types with inheritanceChain")

    # Step 6: Build augmentation map
    print(f"\nStep 6: Building augmentation map...")
    augmentation_map = build_augmentation_map(model)
    total_aug_props = sum(len(v["augProperties"]) for v in augmentation_map.values())
    print(f"    {len(augmentation_map)} augmented types, "
          f"{total_aug_props} augmented properties")

    # Step 7: Load codelists (optional)
    codelists_enriched = 0
    if codelists_dir:
        cl_path = Path(codelists_dir)
        if cl_path.is_dir():
            print(f"\nStep 7: Loading Genericode codelists...")
            codelists = load_codelists(cl_path)
            codelists_enriched = enrich_with_codelists(types, codelists)
            print(f"    {codelists_enriched} types enriched with codelist facets")
            source_files.append(str(cl_path))
        else:
            print(f"\n  WARNING: Codelists directory not found: {cl_path}")
    else:
        print(f"\nStep 7: No codelists directory specified (skipping)")

    # Step 8: Definition quality report
    print(f"\nStep 8: Definition quality assessment...")
    quality = definition_quality_report(types, properties, name)

    # Step 9: Assemble and write catalog
    print(f"\nStep 9: Assembling catalog...")
    catalog = build_catalog(
        types, properties, namespace_map, augmentation_map,
        property_index, name, version, source_files, codelists_enriched,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    size_kb = output_path.stat().st_size // 1024
    print(f"  Reference catalog: {output_path} ({size_kb} KB)")

    # Summary
    summary_path = specs_dir / f"{name}_catalog_summary_{version}.json"
    summary = build_catalog_summary(types)
    summary_wrapped = {
        "version": version,
        "generatedAt": catalog["generatedAt"],
        "stats": catalog["stats"],
        "namespaces": summary,
    }
    summary_path.write_text(
        json.dumps(summary_wrapped, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    size_kb = summary_path.stat().st_size // 1024
    print(f"  Catalog summary: {summary_path} ({size_kb} KB)")

    # Type directory
    dir_path = specs_dir / f"{name}_type_directory_{version}.txt"
    dir_path.write_text(build_type_directory(types), encoding="utf-8")
    size_kb = dir_path.stat().st_size // 1024
    print(f"  Type directory: {dir_path} ({size_kb} KB)")

    # Quality report
    quality_path = specs_dir / f"{name}_definition_quality_{version}.json"
    quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Quality report: {quality_path}")

    print(f"\nDone. Catalog for {name} v{version} generated.")
    return output_path


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a reference catalog from a CMF XML file"
    )
    parser.add_argument("--input", required=True,
                        help="Path to the CMF XML file (e.g., nods.cmf)")
    parser.add_argument("--codelists", default=None,
                        help="Path to directory containing .gc codelist files")
    parser.add_argument("--name", required=True,
                        help="Catalog name (e.g., nods)")
    parser.add_argument("--version", required=True,
                        help="Catalog version (e.g., 1.0)")
    parser.add_argument("--niem-version", required=True,
                        help="NIEM structures namespace version (e.g., 6.0)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing catalog")
    args = parser.parse_args()

    generate(
        input_path=args.input,
        name=args.name,
        version=args.version,
        codelists_dir=args.codelists,
        niem_version=args.niem_version,
        force=args.force,
    )


if __name__ == "__main__":
    main()
