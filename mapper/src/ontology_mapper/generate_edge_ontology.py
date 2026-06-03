#!/usr/bin/env python3
"""Stage 6a: Generate edge ontology — deterministic OWL/TTL, SHACL, and SKOS generation.

Reads the concept inventory and mapping matrix from the pipeline run,
then emits all ontology artifacts with every source property carried forward.
This replaces LLM-driven generation for ontology files, ensuring consistent
output across runs.

All behavior is derived from the data — no domain-specific hardcoding.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from ontology_mapper.pipeline_context import load_context

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
from ontology_mapper.generation_utils import XSD
SKOS_CONCEPT = "http://www.w3.org/2004/02/skos/core#Concept"
OWL_CLASS = "http://www.w3.org/2002/07/owl#Class"


# ---------------------------------------------------------------------------
# Pure helpers — extracted to generation_utils.py, re-exported for compatibility
# ---------------------------------------------------------------------------
from ontology_mapper.generation_utils import (
    local_name,
    edge_class_name,
    target_to_qname,
    xsd_qname,
    infer_domains_from_shapes,
    assign_properties_to_classes,
    detect_consolidations,
)


# ---------------------------------------------------------------------------
# Stage-specific data loading (catalog, inventory, matrix)
# ---------------------------------------------------------------------------
def load_stage_data(ctx):
    """Load concept inventory, mapping matrix, and target catalog namespace map."""
    inv = json.loads((ctx.run_dir / "concept-inventory.json").read_text(encoding="utf-8"))
    matrix = json.loads((ctx.run_dir / "mapping-matrix.json").read_text(encoding="utf-8"))

    from ontology_mapper.run_dir_utils import resolve_specs_dir
    catalog_path = resolve_specs_dir() / f"{ctx.target_ontology}_reference_catalog_{ctx.target_version}.json"
    if not catalog_path.exists():
        raise FileNotFoundError(
            f"No reference catalog found for {ctx.target_ontology} {ctx.target_version}. "
            f"Generate one first (NIEM: om-generate-catalog, OWL: om-generate-owl-catalog)"
        )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    target_ns_map = catalog.get("namespaces", {})

    # Build qname→URI lookup for target types that lack a namespace prefix
    # (e.g. SALI-Folio uses bare hash identifiers like "Ri4VCm5wJTuwU7RBeBEFfi")
    target_type_uris = {t["qname"]: t["uri"] for t in catalog.get("types", []) if t.get("uri")}

    return inv, matrix, target_ns_map, target_type_uris


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 6a: Generate edge ontology TTL files")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    parser.add_argument("--package-dir", default=None, help="Edge package directory path")
    args = parser.parse_args()

    ctx = load_context(args.run_dir, args.package_dir)
    inv, matrix, target_ns_map, target_type_uris = load_stage_data(ctx)

    # Convenience locals from context
    EDGE_NS = ctx.edge_ns_hash
    EXT_NS = ctx.ext_ns_hash
    EDGE_PREFIX = ctx.edge_prefix
    LABEL_PREFIX = ctx.label_prefix
    SOURCE = ctx.source
    TARGET_ONTOLOGY = ctx.target_ontology
    TARGET_VERSION = ctx.target_version
    PKG = ctx.pkg_dir


    # Detect source ontology prefix
    _sample_class = inv["classes"][0] if inv["classes"] else None
    SOURCE_PREFIX = (_sample_class["qname"].split(":")[0] + ":") if _sample_class else ""

    # Build lookups
    mapping_by_concept = {m["sourceConcept"]: m for m in matrix["mappings"]}
    class_by_qname = {c["qname"]: c for c in inv["classes"]}
    obj_by_qname = {p["qname"]: p for p in inv["objectProperties"]}
    dt_by_qname = {p["qname"]: p for p in inv["datatypeProperties"]}

    # --- Closures that reference loaded data ---

    def _target_to_qname(target_type):
        """Return a valid Turtle reference for a target type.

        Prefixed qnames (e.g. "nc:AddressType") pass through.
        Bare identifiers (e.g. SALI hashes) are wrapped as full IRIs
        using the catalog's URI lookup.
        """
        if not target_type or ":" in target_type:
            return target_to_qname(target_type)
        uri = target_type_uris.get(target_type)
        if uri:
            return f"<{uri}>"
        return target_to_qname(target_type)

    def classify_concept(qname):
        m = mapping_by_concept.get(qname)
        if not m:
            return None, None
        return m["action"], m.get("targetType")

    def is_source_class_ref(iri):
        return iri.startswith(SOURCE_PREFIX)

    def map_range_ref(range_iri):
        if range_iri.startswith(XSD):
            return None
        if range_iri == SKOS_CONCEPT:
            return "skos:Concept"
        if range_iri == OWL_CLASS:
            return "owl:Class"
        if is_source_class_ref(range_iri):
            action, target = classify_concept(range_iri)
            if action == "reuse" and target:
                return _target_to_qname(target)
            elif action == "extend":
                return "ext:" + edge_class_name(range_iri)
            elif action == "augment" and target:
                return _target_to_qname(target)
            elif action == "exclude":
                cls = class_by_qname.get(range_iri)
                if cls and cls.get("subClassOf"):
                    parent = cls["subClassOf"][0]
                    parent_action, parent_niem = classify_concept(parent)
                    if parent_action == "reuse" and parent_niem:
                        return _target_to_qname(parent_niem)
                    elif parent_action == "extend":
                        return "ext:" + edge_class_name(parent)
                return None
            else:
                return None
        return None

    def edge_prop_prefix(prop_qname, cls_action):
        if not prop_qname.startswith(SOURCE_PREFIX):
            return ""
        if cls_action == "reuse":
            return EDGE_PREFIX
        return "ext:"

    # Build property mapping lookup: (class_qname, prop_local_name) -> propertyMapping
    # This lets emit_class_block and emit_shape_block resolve reuse-property decisions
    _prop_mapping_lookup = {}
    for m in matrix["mappings"]:
        cls_qname = m["sourceConcept"]
        for pm in (m.get("propertyMappings") or []):
            _prop_mapping_lookup[(cls_qname, pm["sourceProperty"])] = pm

    def _is_reuse_property(cls_qname, prop_qname):
        """Check if a property has a reuse-property mapping (already exists on target)."""
        pm = _prop_mapping_lookup.get((cls_qname, local_name(prop_qname)))
        return pm is not None and pm.get("action") == "reuse-property"

    def resolve_property_ref(prop_qname, cls_qname, cls_action):
        """Resolve the emitted property reference, checking for reuse-property mappings.

        If the property has an accepted reuse-property mapping with a target property,
        return the target qualified property name. Otherwise fall back to the
        edge/ext prefixed local name.
        """
        prop_local = local_name(prop_qname)
        pm = _prop_mapping_lookup.get((cls_qname, prop_local))
        if (pm and pm["action"] == "reuse-property"
                and pm.get("targetProperty")
                and pm.get("reviewStatus") == "accepted"):
            target_prop = pm["targetProperty"]
            # Ensure it's qualified (has a prefix)
            if ":" not in target_prop:
                cls_mapping = mapping_by_concept.get(cls_qname, {})
                target_type = cls_mapping.get("targetType", "")
                if ":" in target_type:
                    prefix = target_type.split(":")[0]
                    return f"{prefix}:{target_prop}"
            return target_prop

        if not prop_qname.startswith(SOURCE_PREFIX):
            return prop_qname
        return edge_prop_prefix(prop_qname, cls_action) + prop_local

    # --- Classify concepts ---
    reuse_classes = []
    extend_classes = []
    augment_classes = []  # (qname, target, label, comment, augmented_type)
    for cls in inv["classes"]:
        qname = cls["qname"]
        action, target = classify_concept(qname)
        if action == "reuse":
            reuse_classes.append((qname, target, cls["label"], cls["comment"]))
        elif action == "extend":
            m_entry = mapping_by_concept[qname]
            base = m_entry.get("baseType") or target
            extend_classes.append((qname, base, cls["label"], cls["comment"]))
        elif action == "augment":
            m = mapping_by_concept[qname]
            raw_augmented = m.get("augmentsType") or target
            augmented_type = _target_to_qname(raw_augmented) if raw_augmented else "owl:Thing"
            augment_classes.append((qname, target, cls["label"], cls["comment"],
                                   augmented_type))

    all_active_qnames = (
        {q for q, _, _, _ in reuse_classes}
        | {q for q, _, _, _ in extend_classes}
        | {q for q, _, _, _, _ in augment_classes}
    )

    # Infer property domains from SHACL shapes
    shape_domains = infer_domains_from_shapes(
        inv["objectProperties"] + inv["datatypeProperties"],
        inv["shaclShapes"]
    )

    # Assign properties
    obj_assigned, obj_unassigned = assign_properties_to_classes(
        inv["objectProperties"], all_active_qnames, shape_domains)
    dt_assigned, dt_unassigned = assign_properties_to_classes(
        inv["datatypeProperties"], all_active_qnames, shape_domains)

    # Include augmenting namespace properties with explicit domains
    for prop in inv["datatypeProperties"]:
        if not prop["qname"].startswith(SOURCE_PREFIX) and prop["domain"]:
            active = [d for d in prop["domain"] if d in all_active_qnames]
            if active and prop["qname"] not in dt_assigned:
                dt_assigned[prop["qname"]] = active

    def props_for_class(cls_qname):
        obj = []
        dt = []
        seen_obj = set()
        seen_dt = set()
        for pq, domains in obj_assigned.items():
            if cls_qname in domains and pq in obj_by_qname:
                obj.append((pq, obj_by_qname[pq]))
                seen_obj.add(pq)
        for pq, domains in dt_assigned.items():
            if cls_qname in domains and pq in dt_by_qname:
                dt.append((pq, dt_by_qname[pq]))
                seen_dt.add(pq)
        for p in inv["objectProperties"]:
            if cls_qname in p["domain"] and p["qname"] not in seen_obj:
                obj.append((p["qname"], p))
        for p in inv["datatypeProperties"]:
            if cls_qname in p["domain"] and p["qname"] not in seen_dt:
                dt.append((p["qname"], p))
        return sorted(obj, key=lambda x: x[0]), sorted(dt, key=lambda x: x[0])

    # Detect consolidations and shared targets
    consolidations = detect_consolidations(matrix, class_by_qname)

    target_type_users = {}
    for cls_qname, target, _, _ in reuse_classes:
        if target:
            target_type_users.setdefault(target, []).append(cls_qname)
    shared_targets = {t for t, users in target_type_users.items() if len(users) > 1}

    # --- TTL emitters ---

    def build_prefixes():
        lines = [
            f"@prefix {EDGE_PREFIX:<11s}<{EDGE_NS}> .",
            f"@prefix ext:       <{EXT_NS}> .",
            "@prefix owl:       <http://www.w3.org/2002/07/owl#> .",
            "@prefix rdfs:      <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix xsd:       <http://www.w3.org/2001/XMLSchema#> .",
            "@prefix skos:      <http://www.w3.org/2004/02/skos/core#> .",
            "@prefix dcterms:   <http://purl.org/dc/terms/> .",
            "@prefix sh:        <http://www.w3.org/ns/shacl#> .",
        ]
        # Declare augmenting namespace prefixes
        declared = {EDGE_PREFIX.rstrip(":"), "ext", "owl", "rdfs",
                     "xsd", "skos", "dcterms", "sh"}
        for aug in inv.get("augmentingNamespaces", []):
            prefix = aug["prefix"]
            ns = aug["namespace"]
            lines.append(f"@prefix {prefix + ':':<11s}<{ns}> .")
            declared.add(prefix)
        # Scan mapping matrix for target ontology prefixes not yet declared
        # (class targets AND reused property qualified names)
        for m in matrix["mappings"]:
            qnames_to_check = []
            target = m.get("targetType")
            if target:
                qnames_to_check.append(target)
            base = m.get("baseType")
            if base:
                qnames_to_check.append(base)
            for pm in (m.get("propertyMappings") or []):
                target_prop = pm.get("targetProperty")
                if target_prop:
                    qnames_to_check.append(target_prop)
            for qname in qnames_to_check:
                if ":" in qname:
                    prefix = qname.split(":")[0]
                    if prefix not in declared and prefix in target_ns_map:
                        ns_uri = target_ns_map[prefix]
                        lines.append(f"@prefix {prefix + ':':<11s}<{ns_uri}> .")
                        declared.add(prefix)
        lines.append("")
        return "\n".join(lines)

    PREFIXES = build_prefixes()

    def emit_class_block(cls_qname, target_type, label, comment, prefix, obj_props, dt_props):
        type_name = prefix + edge_class_name(cls_qname)
        if target_type:
            superclass = _target_to_qname(target_type)
        else:
            superclass = "owl:Thing"
        action = "reuse" if prefix == EDGE_PREFIX else "extend"

        lines = []
        lines.append(f"\n# ── {label or local_name(cls_qname)} ──")
        lines.append(f"{type_name}")
        lines.append(f"    a owl:Class ;")
        lines.append(f"    rdfs:subClassOf {superclass} ;")
        lines.append(f'    rdfs:label "{label or local_name(cls_qname)}" ;')
        if comment:
            safe_comment = comment.replace('"', '\\"').replace('\n', ' ')
            lines.append(f'    rdfs:comment "{safe_comment}" ;')
        lines.append(f'    dcterms:source "{SOURCE}" .')
        lines.append("")

        for pqname, prop in dt_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, action)
            range_vals = prop["range"]
            xsd_type = xsd_qname(range_vals[0]) if range_vals else "xsd:string"
            plabel = prop.get("label", prop_local)
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:DatatypeProperty ;")
            lines.append(f"    rdfs:domain {type_name} ;")
            lines.append(f"    rdfs:range {xsd_type} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")

        for pqname, prop in obj_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, action)
            plabel = prop.get("label", prop_local)
            range_vals = prop["range"]
            if range_vals:
                range_ref = map_range_ref(range_vals[0])
                if range_ref is None:
                    continue
            else:
                range_ref = "owl:Thing"
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:ObjectProperty ;")
            lines.append(f"    rdfs:domain {type_name} ;")
            lines.append(f"    rdfs:range {range_ref} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")

        return "\n".join(lines)

    def emit_augmentation_props(cls_qname, augmented_type, obj_props, dt_props):
        """Emit augmentation properties directly on the augmented type.

        In NIEM OWL/RDF, augmentation types are transparent — no augmentation
        type class is declared.  New properties are emitted with rdfs:domain
        pointing to the augmented type.
        """
        lines = []
        lines.append(f"\n# ── Augmentation of {augmented_type} (from {local_name(cls_qname)}) ──")

        for pqname, prop in dt_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, "augment")
            range_vals = prop["range"]
            xsd_type = xsd_qname(range_vals[0]) if range_vals else "xsd:string"
            plabel = prop.get("label", prop_local)
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:DatatypeProperty ;")
            lines.append(f"    rdfs:domain {augmented_type} ;")
            lines.append(f"    rdfs:range {xsd_type} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")

        for pqname, prop in obj_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, "augment")
            plabel = prop.get("label", prop_local)
            range_vals = prop["range"]
            if range_vals:
                range_ref = map_range_ref(range_vals[0])
                if range_ref is None:
                    continue
            else:
                range_ref = "owl:Thing"
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:ObjectProperty ;")
            lines.append(f"    rdfs:domain {augmented_type} ;")
            lines.append(f"    rdfs:range {range_ref} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")

        return "\n".join(lines)

    def emit_global_properties(unassigned_obj, unassigned_dt, prefix):
        lines = []
        if not unassigned_obj and not unassigned_dt:
            return ""
        lines.append("\n# ══ Global Properties (no specific domain) ══")
        for pqname in sorted(unassigned_dt):
            if pqname not in dt_by_qname:
                continue
            prop = dt_by_qname[pqname]
            prop_local = local_name(pqname)
            if not pqname.startswith(SOURCE_PREFIX):
                prop_ref = pqname
            else:
                prop_ref = prefix + prop_local
            range_vals = prop["range"]
            xsd_type = xsd_qname(range_vals[0]) if range_vals else "xsd:string"
            plabel = prop.get("label", prop_local)
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:DatatypeProperty ;")
            lines.append(f"    rdfs:range {xsd_type} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")
        for pqname in sorted(unassigned_obj):
            if pqname not in obj_by_qname:
                continue
            prop = obj_by_qname[pqname]
            prop_local = local_name(pqname)
            prop_ref = prefix + prop_local
            plabel = prop.get("label", prop_local)
            range_vals = prop["range"]
            if range_vals:
                range_ref = map_range_ref(range_vals[0])
                if range_ref is None:
                    continue
            else:
                range_ref = "owl:Thing"
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:ObjectProperty ;")
            lines.append(f"    rdfs:range {range_ref} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")
        return "\n".join(lines)

    def emit_shape_block(source_shape, prefix):
        target_src = source_shape["targetClass"]
        action, target = classify_concept(target_src)
        if action == "reuse" and target:
            target_type = _target_to_qname(target)
            shape_name = prefix + local_name(target_src) + "Shape"
        elif action == "extend":
            target_type = "ext:" + edge_class_name(target_src)
            shape_name = prefix + local_name(target_src) + "Shape"
        elif action == "augment":
            m = mapping_by_concept.get(target_src, {})
            augmented = m.get("augmentsType") or target
            target_type = _target_to_qname(augmented) if augmented else "owl:Thing"
            shape_name = prefix + local_name(target_src) + "Shape"
        else:
            return ""

        is_shared = target_type in shared_targets

        lines = []
        lines.append(f"\n# ── {local_name(target_src)} Shape ──")
        lines.append(f"{shape_name}")
        lines.append(f"    a sh:NodeShape ;")
        lines.append(f"    sh:targetClass {target_type} ;")
        lines.append(f'    rdfs:label "{local_name(target_src)} Shape" ;')

        for i, prop in enumerate(source_shape["properties"]):
            path_local = local_name(prop["path"])
            path_ref = resolve_property_ref(prop["path"], target_src, action)
            min_count = prop.get("minCount")
            if is_shared and min_count and min_count > 0:
                min_count = 0
            max_count = prop.get("maxCount")
            dt = prop.get("datatype")
            cls = prop.get("class")
            is_last = (i == len(source_shape["properties"]) - 1)
            terminator = " ." if is_last else " ;"
            constraint_parts = []
            constraint_parts.append(f"        sh:path {path_ref}")
            constraint_parts.append(f'        sh:name "{path_local}"')
            if dt:
                constraint_parts.append(f"        sh:datatype {xsd_qname(dt)}")
            elif cls:
                mapped_cls = map_range_ref(cls)
                if mapped_cls:
                    constraint_parts.append(f"        sh:class {mapped_cls}")
            if min_count is not None:
                constraint_parts.append(f"        sh:minCount {min_count}")
            if max_count is not None:
                constraint_parts.append(f"        sh:maxCount {max_count}")
            lines.append(f"    sh:property [")
            lines.append(f" ;\n".join(constraint_parts))
            lines.append(f"    ]{terminator}")

        lines.append("")
        return "\n".join(lines)

    # --- Generate all files ---

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ontology/{SOURCE}-edge-core.ttl
    core_header = f"""{PREFIXES}
<{EDGE_NS.rstrip('#')}>
    a owl:Ontology ;
    rdfs:label "{LABEL_PREFIX} Edge Core Ontology" ;
    rdfs:comment "{TARGET_ONTOLOGY} {TARGET_VERSION} aligned edge ontology — reuse classes mapped from the {SOURCE} agency ontology." ;
    dcterms:created "{now_iso}"^^xsd:date ;
    owl:versionInfo "1.0.0" .
"""

    core_body = []
    for cls_qname, target, label, comment in sorted(reuse_classes, key=lambda x: x[0]):
        obj, dt = props_for_class(cls_qname)
        core_body.append(emit_class_block(cls_qname, target, label, comment, EDGE_PREFIX, obj, dt))

    core_globals = emit_global_properties(
        [p for p in obj_unassigned if p.startswith(SOURCE_PREFIX)],
        [p for p in dt_unassigned if p.startswith(SOURCE_PREFIX)],
        EDGE_PREFIX
    )

    core_ttl = core_header + "\n".join(core_body) + "\n" + core_globals + "\n"

    # ontology/{SOURCE}-edge-extensions.ttl
    ext_header = f"""{PREFIXES}
<{EXT_NS.rstrip('#')}>
    a owl:Ontology ;
    rdfs:label "{LABEL_PREFIX} Edge Extensions Ontology" ;
    rdfs:comment "Extension types for {TARGET_ONTOLOGY} {TARGET_VERSION} gaps — domain-specific classes not available in the target ontology." ;
    dcterms:created "{now_iso}"^^xsd:date ;
    owl:versionInfo "1.0.0" .
"""

    ext_body = []
    for cls_qname, target, label, comment in sorted(extend_classes, key=lambda x: x[0]):
        obj, dt = props_for_class(cls_qname)
        ext_body.append(emit_class_block(cls_qname, target, label, comment, "ext:", obj, dt))

    # Augment: emit new properties directly on the augmented type (NIEM pattern —
    # augmentation types are transparent in OWL/RDF, no class declaration needed)
    for cls_qname, target, label, comment, augmented_type in sorted(augment_classes, key=lambda x: x[0]):
        obj, dt = props_for_class(cls_qname)
        obj_filtered = [(pq, p) for pq, p in obj if not _is_reuse_property(cls_qname, pq)]
        dt_filtered = [(pq, p) for pq, p in dt if not _is_reuse_property(cls_qname, pq)]
        ext_body.append(emit_augmentation_props(cls_qname, augmented_type, obj_filtered, dt_filtered))

    ext_ttl = ext_header + "\n".join(ext_body) + "\n"

    # ontology/{SOURCE}-edge-all.ttl
    all_ttl = f"""{PREFIXES}
<{EDGE_NS.rstrip('#')}/all>
    a owl:Ontology ;
    rdfs:label "{LABEL_PREFIX} Edge — All Modules" ;
    owl:imports <{EDGE_NS.rstrip('#')}> ;
    owl:imports <{EXT_NS.rstrip('#')}> .
"""

    # ontology/{SOURCE}-edge-combined.ttl
    combined_header = f"""{PREFIXES}
<{EDGE_NS.rstrip('#')}/combined>
    a owl:Ontology ;
    rdfs:label "{LABEL_PREFIX} Edge — Combined (Flattened)" ;
    rdfs:comment "All edge core and extension triples in a single file." ;
    dcterms:created "{now_iso}"^^xsd:date ;
    owl:versionInfo "1.0.0" .
"""

    combined_ttl = combined_header + "\n# ═══ CORE (Target Reuse) ═══\n" + "\n".join(core_body)
    combined_ttl += "\n" + core_globals
    combined_ttl += "\n\n# ═══ EXTENSIONS ═══\n" + "\n".join(ext_body) + "\n"

    # shapes/{SOURCE}-edge-shapes.ttl
    shapes_header = f"""{PREFIXES}
<{EDGE_NS.rstrip('#')}/shapes>
    a owl:Ontology ;
    rdfs:label "{LABEL_PREFIX} Edge SHACL Shapes" ;
    rdfs:comment "SHACL validation shapes. Shared target types have relaxed minCount constraints." ;
    dcterms:created "{now_iso}"^^xsd:date ;
    owl:versionInfo "1.0.0" .

# Shared targets (multiple source types → same target type):
"""
    for st in sorted(shared_targets):
        users = target_type_users[st]
        shapes_header += f"#   {st} ← {', '.join(users)}\n"

    shapes_body = []
    for shape in inv["shaclShapes"]:
        block = emit_shape_block(shape, EDGE_PREFIX)
        if block:
            shapes_body.append(block)

    shapes_ttl = shapes_header + "\n".join(shapes_body) + "\n"

    # vocab/{SOURCE}-edge-codelists.ttl
    codelists_header = f"""{PREFIXES}
<{EDGE_NS.rstrip('#')}/vocab>
    a owl:Ontology ;
    rdfs:label "{LABEL_PREFIX} Edge Codelists" ;
    rdfs:comment "SKOS concept schemes for enumerated domain values." ;
    dcterms:created "{now_iso}"^^xsd:date ;
    owl:versionInfo "1.0.0" .
"""

    codelists_body = []
    for scheme in inv["codelistSchemes"]:
        scheme_local = local_name(scheme["iri"])
        scheme_label = scheme.get("label") or scheme_local
        codelists_body.append(f"\n# ── {scheme_label} ──")
        codelists_body.append(f"{EDGE_PREFIX}{scheme_local}")
        codelists_body.append(f"    a skos:ConceptScheme ;")
        codelists_body.append(f'    rdfs:label "{scheme_label}" .')
        codelists_body.append("")

        for concept in scheme["concepts"]:
            concept_local = local_name(concept["iri"])
            concept_label = concept.get("label", concept_local)
            codelists_body.append(f"{EDGE_PREFIX}{concept_local}")
            codelists_body.append(f"    a skos:Concept ;")
            codelists_body.append(f"    skos:inScheme {EDGE_PREFIX}{scheme_local} ;")
            codelists_body.append(f'    skos:prefLabel "{concept_label}" .')
            codelists_body.append("")

    # Synthetic codelist schemes for consolidated subtypes
    for parent_qname, absorbed_qnames, scheme_name in consolidations:
        parent_local = local_name(parent_qname)
        codelists_body.append(f"\n# ── {parent_local} Role Scheme (from subtype consolidation) ──")
        codelists_body.append(f"{EDGE_PREFIX}{scheme_name}")
        codelists_body.append(f"    a skos:ConceptScheme ;")
        codelists_body.append(f'    rdfs:label "{parent_local} Role Scheme" .')
        codelists_body.append("")

        for absorbed in sorted(absorbed_qnames):
            role_local = local_name(absorbed)
            slug = ""
            for i, c in enumerate(role_local):
                if c.isupper() and i > 0:
                    slug += "-" + c.lower()
                else:
                    slug += c.lower()
            label = ""
            for i, c in enumerate(role_local):
                if c.isupper() and i > 0:
                    label += " " + c
                else:
                    label += c
            codelists_body.append(f"{EDGE_PREFIX}{parent_local}Role-{slug}")
            codelists_body.append(f"    a skos:Concept ;")
            codelists_body.append(f"    skos:inScheme {EDGE_PREFIX}{scheme_name} ;")
            codelists_body.append(f'    skos:prefLabel "{label.strip()}" .')
            codelists_body.append("")

    codelists_ttl = codelists_header + "\n".join(codelists_body) + "\n"

    # vocab/codelist-mappings.json
    codelist_mappings = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "description": f"Maps internal {SOURCE} codelist schemes to target ontology equivalents where applicable.",
        "schemes": []
    }
    for scheme in inv["codelistSchemes"]:
        scheme_local = local_name(scheme["iri"])
        entry = {
            "internalScheme": f"{EDGE_PREFIX}{scheme_local}",
            "conceptCount": scheme["conceptCount"],
            "niemCodeTable": None,
            "values": []
        }
        for concept in scheme["concepts"]:
            entry["values"].append({
                "internal": f"{EDGE_PREFIX}{local_name(concept['iri'])}",
                "label": concept.get("label", ""),
                "niemMapping": None
            })
        codelist_mappings["schemes"].append(entry)

    # --- Write all files ---
    ont_dir = PKG / "ontology"
    shapes_dir = PKG / "shapes"
    vocab_dir = PKG / "vocab"
    cmf_dir = PKG / "cmf"

    for d in [ont_dir, shapes_dir, vocab_dir, cmf_dir]:
        d.mkdir(parents=True, exist_ok=True)

    files_written = {}

    def write_artifact(path, content):
        path.write_text(content, encoding="utf-8")
        files_written[str(path)] = len(content)

    write_artifact(ont_dir / ctx.ontology_filename("core"), core_ttl)
    write_artifact(ont_dir / ctx.ontology_filename("extensions"), ext_ttl)
    write_artifact(ont_dir / ctx.ontology_filename("all"), all_ttl)
    write_artifact(ont_dir / ctx.ontology_filename("combined"), combined_ttl)
    write_artifact(shapes_dir / ctx.ontology_filename("shapes"), shapes_ttl)
    write_artifact(vocab_dir / ctx.ontology_filename("codelists"), codelists_ttl)
    write_artifact(vocab_dir / "codelist-mappings.json",
                   json.dumps(codelist_mappings, indent=2) + "\n")

    # --- Summary ---
    def count_class_props(class_list):
        obj_count = 0
        dt_count = 0
        for q, _, _, _ in class_list:
            o, d = props_for_class(q)
            obj_count += len(o)
            dt_count += len(d)
        return obj_count, dt_count

    core_obj, core_dt = count_class_props(reuse_classes)
    ext_obj, ext_dt = count_class_props(extend_classes)
    aug_obj, aug_dt = 0, 0
    for q, _, _, _, _ in augment_classes:
        o, d = props_for_class(q)
        aug_obj += sum(1 for pq, _ in o if not _is_reuse_property(q, pq))
        aug_dt += sum(1 for pq, _ in d if not _is_reuse_property(q, pq))
    total_concepts = sum(s["conceptCount"] for s in inv["codelistSchemes"])
    synth_roles = sum(len(a) for _, a, _ in consolidations)

    print(f"\n  Stage 6a: Deterministic ontology generation complete")
    print(f"  Run: {ctx.run_dir}")
    print(f"  Output: {PKG}")
    print(f"  Organization: {ctx.organization}, Source: {SOURCE}, Target: {TARGET_ONTOLOGY} {TARGET_VERSION}")
    print(f"  Source prefix: {SOURCE_PREFIX}")
    print(f"  Files written: {len(files_written)}")
    for path, size in sorted(files_written.items()):
        print(f"    {path} ({size:,} bytes)")
    print(f"\n  Core: {len(reuse_classes)} classes, {core_obj} object props, {core_dt} datatype props")
    print(f"  Extensions: {len(extend_classes)} classes, {ext_obj} object props, {ext_dt} datatype props")
    if augment_classes:
        print(f"  Augmentations: {len(augment_classes)} classes, {aug_obj} new object props, {aug_dt} new datatype props")
    print(f"  Global properties: {len(obj_unassigned)} object, {len(dt_unassigned)} datatype (no domain assigned)")
    print(f"  SHACL shapes: {len(shapes_body)}")
    print(f"  Shared targets (relaxed minCount): {sorted(shared_targets)}")
    print(f"  Codelists: {len(inv['codelistSchemes'])} schemes, {total_concepts} concepts")
    if consolidations:
        for parent, absorbed, scheme in consolidations:
            print(f"  Synthetic scheme: {scheme} ({len(absorbed)} roles from subtype consolidation)")

    # --- CMF generation (from matrix, all targets) ---
    print(f"\n  Generating CMF artifacts...")
    from ontology_mapper.generate_cmf_from_matrix import MatrixToCmfBuilder
    from ontology_mapper.owl_cmf_bridge import CmfXmlSerializer, CmfJsonSerializer, set_niem_version

    set_niem_version(TARGET_VERSION)

    cmf_model = MatrixToCmfBuilder(matrix, inv, ctx, target_ns_map).build()

    cmf_xml_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf"
    cmf_json_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf.json"

    write_artifact(cmf_xml_path, CmfXmlSerializer(cmf_model).serialize())
    write_artifact(cmf_json_path, CmfJsonSerializer(cmf_model).serialize())

    print(f"    {cmf_xml_path} ({files_written[str(cmf_xml_path)]:,} bytes)")
    print(f"    {cmf_json_path} ({files_written[str(cmf_json_path)]:,} bytes)")
    print(f"    Namespaces: {len(cmf_model.namespaces)}, Classes: {len(cmf_model.classes)}, Properties: {len(cmf_model.properties)}")


if __name__ == "__main__":
    main()
