#!/usr/bin/env python3
"""Generic catalog adapter — extracts types and properties from any reference
catalog into OntologyEntry format for vector indexing.

Works with catalogs from all three generators:
  - om-generate-catalog       (NIEM)
  - om-generate-owl-catalog   (OWL ontologies like SALI/FOLIO)
  - om-generate-cmf-catalog   (CMF-based ontologies like NODS)

All generators produce the same JSON schema, so a single adapter handles them.

The catalogs carry the full ontology representation — augmentation types,
abstract properties, and all structural metadata. This adapter selects only
what should be embedded in the vector index for semantic matching:

  - Augmentation-pattern types are excluded from indexing because they are
    not direct alignment targets. The evaluator aligns against the base
    type; the augmentation map tells it what properties are contributed.
  - Abstract properties are excluded from indexing because they are
    substitution group heads, not concrete elements. Their concrete
    substitutions are indexed instead.

Usage:
    from ontology_mapper.adapters.catalog_adapter import extract_types, extract_properties
    types = extract_types("niem", "6.0")
    props = extract_properties("sali-folio", "2.0")
    types = extract_types("nods", "1.0")
"""

import json
from pathlib import Path

from ontology_mapper.run_dir_utils import resolve_specs_dir
from ontology_mapper.vector_index import OntologyEntry


def _find_catalog(name: str, version: str) -> Path:
    """Locate the reference catalog file."""
    specs_dir = resolve_specs_dir()
    catalog_path = specs_dir / f"{name}_reference_catalog_{version}.json"
    if not catalog_path.exists():
        raise FileNotFoundError(
            f"Reference catalog not found: {catalog_path}. "
            f"Generate it with om-generate-catalog, om-generate-owl-catalog, "
            f"or om-generate-cmf-catalog."
        )
    return catalog_path


def extract_types(name: str, version: str) -> list[OntologyEntry]:
    """Extract all indexable types as OntologyEntry objects.

    Skips augmentation-pattern types (not matchable targets — they
    contribute properties to base types via the augmentation map).

    Embedding text combines: qualified name, definition, base type,
    pattern, inheritance path, and top properties for richer semantic signal.
    """
    catalog = json.loads(_find_catalog(name, version).read_text(encoding="utf-8"))

    # Build a label lookup so context strings use labels instead of opaque IDs.
    # Falls back to qname when no label is available (e.g., NIEM types).
    label_lookup: dict[str, str] = {}
    for t in catalog.get("types", []):
        qn = t.get("qname", "")
        lbl = t.get("label", "")
        if lbl:
            label_lookup[qn] = lbl
    for ns_data in catalog.get("propertyIndex", {}).values():
        for p in ns_data.get("properties", []):
            qn = p.get("qualifiedProperty", "")
            lbl = p.get("label", "")
            if lbl:
                label_lookup[qn] = lbl

    def _display(qname: str) -> str:
        """Return label if available, otherwise the qname itself."""
        return label_lookup.get(qname, qname)

    entries = []
    for t in catalog.get("types", []):
        qname = t.get("qname", "")
        pattern = t.get("pattern", "")
        if pattern == "augmentation":
            continue

        label = t.get("label", "")
        definition = t.get("definition", "")

        # Skip entries with no label and no definition — they carry zero
        # semantic signal and would embed only an opaque ID.
        if not label and not definition:
            continue

        base_type = t.get("baseType") or ""
        properties = t.get("properties", [])
        ns = qname.split(":")[0] if ":" in qname else ""

        # Build inheritance path using labels where available
        inheritance_chain = t.get("inheritanceChain", [])
        display_chain = [_display(c) for c in inheritance_chain]
        display_name = label or qname
        path = "/".join(display_chain + [display_name]) if display_chain else display_name

        context_parts = []
        if base_type:
            context_parts.append(f"Extends {_display(base_type)}")
        if pattern:
            context_parts.append(f"Pattern: {pattern}")
        if len(inheritance_chain) > 1:
            context_parts.append(f"Path: {path}")
        if properties:
            display_props = [_display(p) for p in properties[:10]]
            context_parts.append(f"Properties: {', '.join(display_props)}")

        entries.append(OntologyEntry(
            id=qname,
            label=label,
            definition=definition,
            kind="type",
            context=". ".join(context_parts),
            metadata={
                "namespace": ns,
                "baseType": base_type,
                "pattern": pattern,
                "inheritanceChain": inheritance_chain,
                "path": path,
                "isAugmentation": t.get("isAugmentation", False),
                "isAdapter": t.get("isAdapter", False),
                "isMetadata": t.get("isMetadata", False),
                "propertyCount": len(properties),
                "properties": properties,
                "altLabels": t.get("altLabels", []),
            },
        ))

    return entries


def extract_properties(name: str, version: str) -> list[OntologyEntry]:
    """Extract all indexable properties as OntologyEntry objects.

    Skips abstract properties (substitution group heads, not concrete).

    Embedding text combines: qualified name, definition, type, and
    containing types for domain context.
    """
    catalog = json.loads(_find_catalog(name, version).read_text(encoding="utf-8"))

    # Reuse the same label lookup pattern for properties
    label_lookup: dict[str, str] = {}
    for t in catalog.get("types", []):
        qn = t.get("qname", "")
        lbl = t.get("label", "")
        if lbl:
            label_lookup[qn] = lbl
    for ns_data in catalog.get("propertyIndex", {}).values():
        for p in ns_data.get("properties", []):
            qn = p.get("qualifiedProperty", "")
            lbl = p.get("label", "")
            if lbl:
                label_lookup[qn] = lbl

    def _display(qname: str) -> str:
        return label_lookup.get(qname, qname)

    entries = []
    for ns_name, ns_data in catalog.get("propertyIndex", {}).items():
        for p in ns_data.get("properties", []):
            if p.get("isAbstract", False):
                continue

            qprop = p.get("qualifiedProperty", "")
            label = p.get("label", "")
            definition = p.get("definition", "")

            # Skip entries with no label and no definition — zero semantic signal.
            if not label and not definition:
                continue

            qual_type = p.get("qualifiedType", "")
            containing = p.get("containingTypes", [])

            # Build paths using labels where available
            local_name = p.get("name", "")
            display_prop = label or qprop
            display_containing = [_display(ct) for ct in containing]
            paths = [f"{dc}/{display_prop}" for dc in display_containing]

            context_parts = []
            if qual_type:
                context_parts.append(f"Type: {_display(qual_type)}")
            if paths:
                context_parts.append(f"Path: {paths[0]}")
            elif containing:
                context_parts.append(f"On: {', '.join(display_containing[:5])}")

            entries.append(OntologyEntry(
                id=qprop,
                label=label,
                definition=definition,
                kind="property",
                context=". ".join(context_parts),
                metadata={
                    "namespace": ns_name,
                    "localName": local_name,
                    "qualifiedType": qual_type,
                    "containingTypes": containing,
                    "paths": paths,
                },
            ))

    return entries
