#!/usr/bin/env python3
"""Source ontology adapter — extracts classes and properties from a
concept-inventory.json into generic OntologyEntry format for vector indexing.

The concept inventory is the pipeline's normalized representation of any
source ontology (OWL, SHACL, CSV, etc.).  This adapter reads it and
produces type and property entries suitable for embedding.

Usage:
    from ontology_mapper.adapters.source_adapter import extract_types, extract_properties
    types = extract_types(run_dir)
    props = extract_properties(run_dir)
"""

import json
from pathlib import Path

from ontology_mapper.vector_index import OntologyEntry


def _load_inventory(run_dir) -> dict:
    """Load concept-inventory.json from a run directory."""
    inv_path = Path(run_dir) / "concept-inventory.json"
    if not inv_path.exists():
        raise FileNotFoundError(
            f"concept-inventory.json not found in {run_dir}. "
            f"Run om-extract first."
        )
    return json.loads(inv_path.read_text(encoding="utf-8"))


def extract_types(run_dir) -> list[OntologyEntry]:
    """Extract source classes as OntologyEntry objects.

    Embedding text combines: qualified name, comment/definition,
    and property names for context.
    """
    inv = _load_inventory(run_dir)
    entries = []

    for cls in inv.get("classes", []):
        qname = cls.get("qname", "")
        comment = cls.get("comment", "")
        parent = cls.get("subClassOf", "")

        # Collect properties that belong to this class
        class_props = []
        for key in ("objectProperties", "datatypeProperties"):
            for prop in inv.get(key, []):
                if qname in prop.get("domain", []):
                    local = prop.get("qname", "").split(":")[-1]
                    if local:
                        class_props.append(local)

        # Build path (inheritance chain not available in inventory, so just the type)
        path = f"{parent}/{qname}" if parent else qname

        # Build context
        context_parts = []
        if parent:
            context_parts.append(f"Subclass of {parent}")
        if class_props:
            context_parts.append(f"Properties: {', '.join(class_props[:10])}")

        entries.append(OntologyEntry(
            id=qname,
            definition=comment,
            kind="type",
            context=". ".join(context_parts),
            metadata={
                "subClassOf": parent,
                "path": path,
                "propertyCount": len(class_props),
                "properties": class_props,
            },
        ))

    return entries


def extract_properties(run_dir) -> list[OntologyEntry]:
    """Extract source properties as OntologyEntry objects.

    Combines object properties and datatype properties into a single list.
    Embedding text includes: qualified name, comment, domain, and range.
    """
    inv = _load_inventory(run_dir)
    entries = []
    seen = set()

    for key in ("objectProperties", "datatypeProperties"):
        for prop in inv.get(key, []):
            qname = prop.get("qname", "")
            if not qname or qname in seen:
                continue
            seen.add(qname)

            comment = prop.get("comment", "")
            domain = prop.get("domain", [])
            range_ = prop.get("range", [])
            prop_type = "object" if key == "objectProperties" else "datatype"

            # Build paths: {domain}/{property} for each domain class
            paths = [f"{d}/{qname}" for d in domain]

            # Build context
            context_parts = []
            if paths:
                context_parts.append(f"Path: {paths[0]}")
            elif domain:
                context_parts.append(f"Domain: {', '.join(domain[:5])}")
            if range_:
                context_parts.append(f"Range: {', '.join(str(r) for r in range_[:5])}")
            context_parts.append(f"Property type: {prop_type}")

            entries.append(OntologyEntry(
                id=qname,
                definition=comment,
                kind="property",
                context=". ".join(context_parts),
                metadata={
                    "localName": qname.split(":")[-1] if ":" in qname else qname,
                    "domain": domain,
                    "range": range_,
                    "paths": paths,
                    "propertyType": prop_type,
                },
            ))

    # Also extract SHACL shape properties not covered above
    for shape in inv.get("shaclShapes", []):
        target_class = shape.get("targetClass", "")
        for sp in shape.get("properties", []):
            path = sp.get("path", "")
            if not path or path in seen:
                continue
            seen.add(path)

            sh_datatype = sp.get("datatype", "")
            sh_class = sp.get("class", "")
            domain = [target_class] if target_class else []
            paths = [f"{target_class}/{path}"] if target_class else []

            context_parts = []
            if paths:
                context_parts.append(f"Path: {paths[0]}")
            elif target_class:
                context_parts.append(f"Domain: {target_class}")
            if sh_datatype:
                context_parts.append(f"Range: {sh_datatype}")
            elif sh_class:
                context_parts.append(f"Range: {sh_class}")

            entries.append(OntologyEntry(
                id=path,
                definition="",
                kind="property",
                context=". ".join(context_parts),
                metadata={
                    "localName": path.split(":")[-1] if ":" in path else path,
                    "domain": domain,
                    "range": [sh_datatype or sh_class] if (sh_datatype or sh_class) else [],
                    "paths": paths,
                    "propertyType": "shacl",
                },
            ))

    return entries


def ontology_name(run_dir) -> str:
    """Derive the ontology name from the run directory's state file."""
    state_path = Path(run_dir) / ".mapper-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        source = state.get("inputs", {}).get("source", "")
        if source:
            return source
    # Fallback: use run directory name prefix
    name = Path(run_dir).name
    parts = name.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) >= 8:
        return parts[0]
    return name
