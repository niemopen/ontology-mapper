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
from rdflib import URIRef

from ontology_mapper.pipeline_context import load_context

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
from ontology_mapper.generation_utils import (XSD, colliding_edge_class_names,
                                              shape_target_classes, source_prefix)
SKOS_CONCEPT = "http://www.w3.org/2004/02/skos/core#Concept"
OWL_CLASS = "http://www.w3.org/2002/07/owl#Class"


# ---------------------------------------------------------------------------
# Pure helpers — extracted to generation_utils.py, re-exported for compatibility
# ---------------------------------------------------------------------------
from ontology_mapper.run_dir_utils import utc_stamp
from ontology_mapper.generation_utils import (
    component_iri,
    qualified_target_property,
    range_class_for,
    source_declared_properties,
    target_qname,
    emitted_class_action,
    is_full_iri,
    local_name,
    edge_class_name,
    target_to_qname,
    xsd_qname,
    infer_domains_from_shapes,
    assign_properties_to_classes,
    detect_consolidations,
    property_mapping_index,
    accepted_reuse_target,
    shape_property_is_evaluated,
    source_namespace_bindings,
    created_property_qname,
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

    # The generator is the seam every driver passes through — the runner, the
    # web executor and a by-hand `om-generate-ontology` all start here — so a
    # saved class target the policy rejects stops the package before any file
    # is written, whichever driver asked for it.
    from ontology_mapper.ontology_specific import invalid_class_targets
    rejected = invalid_class_targets(matrix, ctx.target_ontology, catalog)
    if rejected:
        details = "\n".join(f"  - {concept}: {message}" for concept, _, message in rejected)
        raise ValueError(
            f"{len(rejected)} saved class target(s) rejected by the "
            f"{ctx.target_ontology} policy; reopen review:\n{details}")

    target_ns_map = catalog.get("namespaces", {})

    # Build qname→URI lookup for target types that lack a namespace prefix
    # (e.g. SALI-Folio uses bare hash identifiers like "Ri4VCm5wJTuwU7RBeBEFfi")
    target_type_uris = {t["qname"]: t["uri"] for t in catalog.get("types", []) if t.get("uri")}

    # Ground reuse restrictions in the target catalog's declarations.
    target_property_types = {}
    target_property_uris = {}
    for namespace in (catalog.get("propertyIndex") or {}).values():
        for decl in namespace.get("properties", []):
            qualified, typed = decl.get("qualifiedProperty"), decl.get("qualifiedType")
            if qualified and typed:
                target_property_types[qualified] = typed
            # A catalog whose property ids are bare (SALI-Folio ships 177)
            # cannot be written into Turtle as a name; its URI can.
            if qualified and decl.get("uri"):
                target_property_uris[qualified] = decl["uri"]

    return (inv, matrix, target_ns_map, target_type_uris, target_property_types,
            target_property_uris)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def undeclared_shape_paths(core_ttl, ext_ttl, shapes_ttl, own_namespaces):
    """Shape paths in the package's own namespaces that it never declares.

    A shape constraining a term no ontology file defines rejects data that is
    correct and accepts data using a predicate nothing describes, and the run
    still exits 0: Turtle parses, SHACL conforms, and none of Stage 7's checks
    asks. Terms in target or source namespaces are references, not this
    package's to declare, so only its own two namespaces are asked about.
    """
    from rdflib import Graph
    from rdflib.namespace import SH

    declared = set()
    for text in (core_ttl, ext_ttl):
        for subject in Graph().parse(data=text, format="turtle").subjects():
            declared.add(str(subject))
    shapes = Graph().parse(data=shapes_ttl, format="turtle")
    paths = {str(o) for o in shapes.objects(None, SH.path)}
    for alternatives in shapes.objects(None, SH.alternativePath):
        # The object of sh:alternativePath is a list head, never a term.
        paths |= {str(item) for item in shapes.items(alternatives)}
    return sorted(term for term in paths
                  if term.startswith(tuple(own_namespaces)) and term not in declared)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 6a: Generate edge ontology TTL files")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    parser.add_argument("--package-dir", default=None, help="Edge package directory path")
    args = parser.parse_args()

    ctx = load_context(args.run_dir, args.package_dir)
    (inv, matrix, target_ns_map, target_type_uris, target_property_types,
     target_property_uris) = load_stage_data(ctx)

    # Convenience locals from context
    EDGE_NS = ctx.edge_ns_hash
    EXT_NS = ctx.ext_ns_hash
    EDGE_PREFIX = ctx.edge_prefix
    LABEL_PREFIX = ctx.label_prefix
    SOURCE = ctx.source
    TARGET_ONTOLOGY = ctx.target_ontology
    TARGET_VERSION = ctx.target_version
    PKG = ctx.pkg_dir


    # Detect source ontology prefix (one home: generation_utils.source_prefix)
    _source = source_prefix(inv)
    SOURCE_PREFIX = f"{_source}:" if _source else ""
    source_bindings = source_namespace_bindings(inv, target_ns_map, EDGE_PREFIX)

    # Build lookups
    mapping_by_concept = {m["sourceConcept"]: m for m in matrix["mappings"]}
    class_by_qname = {c["qname"]: c for c in inv["classes"]}
    obj_by_qname = {p["qname"]: p for p in inv["objectProperties"]}
    dt_by_qname = {p["qname"]: p for p in inv["datatypeProperties"]}

    # --- Closures that reference loaded data ---

    # namespaceMap is what both producers (extraction, CSV ingest) record.
    primary_uri = next((uri for uri, prefix in inv.get("namespaceMap", {}).items()
                        if prefix.rstrip(":") == _source), None)

    def source_term_ref(qname):
        if is_full_iri(qname):
            return URIRef(qname).n3()
        prefix, separator, name = qname.partition(":")
        if separator and prefix in source_bindings:
            return f"{source_bindings[prefix][0]}:{name}"
        # The primary prefix is never bound in the output (its terms are
        # minted under edge/ext), so a primary term only referenced — one no
        # source property list declares — is written as its full IRI.
        if separator and prefix == _source and primary_uri:
            return URIRef(component_iri(primary_uri, name)).n3()
        return qname

    def _target_to_qname(target_type):
        """Resolve class targets through the same grounding as property targets."""
        rendered = target_term_ref(target_type, target_type_uris)
        if target_type and rendered is None:
            dropped_target_terms.append(f"class -> {target_type}")
        return rendered

    dropped_target_terms = []

    def target_term_ref(term, uris):
        """Render a TARGET term as something Turtle can actually parse, or
        None when nothing grounded can be written.

        A qname whose prefix the
        emitted header binds is written as-is. A bare identifier — SALI-Folio
        ships 177 such property ids, and every type id too — is written as
        its `<uri>` from the catalog. Anything else is DROPPED and recorded,
        because emitting the bare name produces a document that does not
        parse while the emitter still exits 0.
        """
        if not term:
            return None
        if is_full_iri(term):
            return URIRef(term).n3()
        if term in uris:
            return URIRef(uris[term]).n3()
        if ":" in term:
            return term if term.split(":")[0] in bound_prefixes else None
        return None

    def emitting_identities(prop_qname, context, emitting_leaf):
        """Every (declaring class, action) a shape's property was emitted under.

        The identity belongs to the active class that DECLARES the term —
        the one whose class block writes it — not to whichever ancestor a
        walk happens to reach first. `subClassOf` is a set in the source
        model, so an ancestor walk let statement order decide which term a
        shape constrains, and which of two parents' namespaces it came from.

        Both halves of the identity come from that one class. The action
        decides the namespace and the class's own property decision decides
        whether an accepted reuse target replaces the source term; taking
        the action from the owner while resolving the decision under the
        shape's class named neither class's term.

        When a declaring class is in scope its identity is the answer.
        Otherwise every declaring class is one: owners that mint the term
        differently emit several, and the shape names them all (the caller
        unions them into an `sh:alternativePath`). Picking one by sort order
        left the others unconstrained.
        """
        owners = set(obj_assigned.get(prop_qname, ())) | set(dt_assigned.get(prop_qname, ()))
        for candidate in (emitting_leaf, context):
            if candidate in owners:
                return [(candidate, classify_concept(candidate)[0])]
        if owners:
            return [(owner, classify_concept(owner)[0]) for owner in sorted(owners)]
        if not declared_by_source(prop_qname):
            # Constrained by a shape but declared by no source property list
            # (`build_class_properties` harvests shape paths too), so no
            # class block and no global block writes it. The only decision
            # about it is the one under the shape's own class; resolving it
            # there lets an accepted reuse name the target property, and
            # `resolve_property_ref` writes an unaccepted one as the term it
            # is rather than minting a term nothing declares.
            return [(context, classify_concept(context)[0])]
        # No active class owns the property. `emit_global_properties` writes
        # it under the edge prefix whatever any class decided, so the shape
        # names that same term — "reuse" is how `created_property_qname`
        # spells the edge prefix. Asking the inheriting leaf instead minted
        # `ext:` under an extending child and named a term nothing declares.
        return [(None, "reuse")]

    source_declared = source_declared_properties(inv)

    def declared_by_source(prop_qname):
        return prop_qname in source_declared

    def classify_concept(qname):
        m = mapping_by_concept.get(qname)
        if not m:
            return None, None
        action = emitted_class_action(m)
        if action is None:
            return None, None
        return action, m.get("targetType")

    def is_source_class_ref(iri):
        return iri.startswith(SOURCE_PREFIX)

    def object_range_ref(range_vals):
        """The `rdfs:range` for an emitted object property.

        A range this package does not emit — an excluded class, a term in a
        namespace it never declares — leaves the property open rather than
        dropping it. The property is still the source's, the CMF declares it
        either way, and a shape may constrain it; dropping the declaration
        here makes the two models disagree about what the package contains
        and leaves the shape pointing at an undeclared path.
        """
        if not range_vals:
            return "owl:Thing"
        return map_range_ref(range_vals[0]) or "owl:Thing"

    def map_range_ref(range_iri):
        if range_iri.startswith(XSD):
            return None
        if range_iri == SKOS_CONCEPT:
            return "skos:Concept"
        if range_iri == OWL_CLASS:
            return "owl:Class"
        if is_source_class_ref(range_iri) or range_iri in class_by_qname:
            emitted = range_class_for(range_iri, mapping_by_concept, class_by_qname)
            action, target = classify_concept(emitted) if emitted else (None, None)
            if action == "reuse" and target:
                return _target_to_qname(target)
            elif action == "extend":
                return "ext:" + edge_class_name(emitted)
            elif action == "augment" and target:
                return _target_to_qname(target)
            return None
        if range_iri.partition(":")[0] in source_bindings:
            return source_term_ref(range_iri)
        # A range the TARGET catalog binds is grounded the same way a class
        # target is. Only a bound namespace: `target_term_ref` would hand back
        # any full IRI verbatim, which would point the range at a source class
        # this package deliberately does not emit.
        grounded = target_qname(range_iri, target_ns_map)
        if grounded != range_iri:
            return target_term_ref(grounded, target_type_uris)
        return None

    # Property mapping lookup, keyed by the property's QNAME — the identity
    # the matrix records. Built by the shared
    # generation_utils home so this emitter and the CMF emitter cannot drift.
    _prop_mapping_lookup = property_mapping_index(matrix, inv)

    def _is_reuse_property(cls_qname, prop_qname):
        """Is this property carried by the target because an ACCEPTED
        decision put it there?

        One predicate, shared with `resolve_property_ref`.
        Testing `action == "reuse-property"` alone withheld a property from
        the emitted ontology whenever the decision was still
        `pending-review` or carried `[undecided]` — while the shapes went on
        referencing it and the CMF went on declaring it, so the package's own
        `sh:path` pointed at a term no ontology file declared.
        """
        return accepted_reuse_target(
            _prop_mapping_lookup.get((cls_qname, prop_qname))) is not None

    def resolve_property_ref(prop_qname, cls_qname, cls_action):
        """Resolve the emitted property reference, checking for reuse-property mappings.

        If the property has an accepted reuse-property mapping with a target property,
        return the target qualified property name. Otherwise fall back to the
        edge/ext prefixed local name.
        """
        pm = _prop_mapping_lookup.get((cls_qname, prop_qname))
        target_prop = accepted_reuse_target(pm)
        if target_prop:
            rendered = target_term_ref(target_prop, target_property_uris)
            if rendered:
                return rendered
            # An unprefixed target property may be a LOCAL NAME the class's
            # target namespace qualifies, or a bare catalog id (SALI). Try
            # the class's prefix first, then the catalog's URI.
            qualified = qualified_target_property(
                target_prop, mapping_by_concept.get(cls_qname, {}).get("targetType"))
            if qualified != target_prop:
                rendered = target_term_ref(qualified, target_property_uris)
                if rendered:
                    return rendered
            # The source declaration was withheld by the accepted reuse
            # decision. Falling back to it would leave a dangling sh:path.
            dropped_target_terms.append(f"{cls_qname}/{prop_qname} -> {target_prop}")
            return None

        # A declared source namespace is referenced through its binding; a
        # term carrying its own scheme is one this package does not declare,
        # so it is minted here exactly as the CMF builder and the extension
        # catalog mint it — the three must name one identity. A term no
        # source property list declares (a shape path such as `rdfs:label`)
        # is only referenced: minting it put `edge:label` in the shape for a
        # term no ontology file declares, and the closure guard refused the
        # package.
        if ((not prop_qname.startswith(SOURCE_PREFIX) and not is_full_iri(prop_qname))
                or not declared_by_source(prop_qname)):
            return source_term_ref(prop_qname)
        return created_property_qname(
            prop_qname, cls_action, _source, source_bindings, EDGE_PREFIX)

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
            # Render after the prefix header is built, exactly once.
            augmented_type = raw_augmented or "owl:Thing"
            augment_classes.append((qname, target, cls["label"], cls["comment"],
                                   augmented_type))

    all_active_qnames = (
        {q for q, _, _, _ in reuse_classes}
        | {q for q, _, _, _ in extend_classes}
        | {q for q, _, _, _, _ in augment_classes}
    )

    # Reuse and extend only: an augmentation declares no class of its own in
    # OWL (`emit_augmentation_props` puts the properties on the augmented
    # target), so two augmentations, or an augmentation beside a reuse class,
    # share no emitted name and must not be refused.
    collisions = colliding_edge_class_names(
        [q for q, _, _, _ in reuse_classes] + [q for q, _, _, _ in extend_classes])
    if collisions:
        details = "\n".join(f"  - {name}: {', '.join(qnames)}"
                            for name, qnames in collisions.items())
        raise ValueError(
            f"{len(collisions)} edge class name(s) would be emitted for more "
            f"than one source concept; exclude one or rename the source "
            f"class:\n" + details)

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

    def reuse_restrictions(cls_qname):
        """The accepted `reuse-property` decisions of this class, as
        `owl:Restriction` superclass axioms.

        The decision belongs in the emitted ontology: without it an
        OWL-only consumer cannot tell "decided reuse" from "decided
        nothing", and whether the decision is visible would otherwise
        depend on the accident of the source shipping a SHACL shape for
        that class. A restriction is the OWL-correct way to say "this type
        uses that property": it is an anonymous superclass, so it asserts
        nothing about the target property globally — unlike `rdfs:domain`,
        which is why the property itself is never re-declared here.

        Only grounded fillers are emitted. `owl:allValuesFrom` carries the
        target property's own declared type when the catalog gives one; a
        property the catalog leaves untyped (an abstract substitution head)
        yields a nonrestrictive minimum cardinality of zero, which records
        the reference without inventing a range. No existential filler is
        emitted: `owl:someValuesFrom` would assert a value must exist,
        which no accepted decision says.
        """
        seen = set()
        out = []
        obj, dt = props_for_class(cls_qname)
        for pq, _ in obj + dt:
            target = accepted_reuse_target(_prop_mapping_lookup.get((cls_qname, pq)))
            if not target or target in seen:
                continue
            seen.add(target)
            ref = resolve_property_ref(pq, cls_qname, mapping_by_concept[cls_qname]["action"])
            if ref is None:
                # Not writable as a Turtle reference; the decision is still
                # carried by the CMF and the matrix.
                dropped_target_terms.append(f"{cls_qname} restriction -> {target}")
                continue
            filler = target_property_types.get(target)
            filler_ref = target_term_ref(filler, target_type_uris) if filler else None
            out.append((ref, filler_ref))
        return sorted(out)

    def emit_reuse_restrictions(cls_qname, type_ref):
        lines = []
        for prop_ref, filler in reuse_restrictions(cls_qname):
            # minCardinality 0 is nonrestrictive: record the accepted property
            # without inventing a range or requiring a value. A bare
            # owl:onProperty node is not a complete OWL restriction.
            constraint = (f"owl:allValuesFrom {filler}" if filler
                          else 'owl:minCardinality "0"^^xsd:nonNegativeInteger')
            lines.append(f"{type_ref} rdfs:subClassOf [ a owl:Restriction ; "
                         f"owl:onProperty {prop_ref} ; {constraint} ] .")
        return lines

    def declared_props_for_class(cls_qname):
        """The properties this class DECLARES: everything it carries, minus
        the ones an accepted `reuse-property` decision placed on the target.

        A reused property is owned by the target ontology. Declaring it here
        would re-declare a NIEM-owned term, and `rdfs:domain` is a global
        assertion in OWL — `nc:ActivityDueDate rdfs:domain edge:FooType`
        narrows that NIEM property to the edge type everywhere it is used,
        and the accompanying `rdfs:range`/`rdfs:label` overwrite its NIEM
        ones. The edge type reaches the property through `rdfs:subClassOf`
        the target type; the decision is carried by the SHACL shape's
        `sh:path` and the CMF's `HasProperty` reference. The augment path
        has always filtered this way — reuse and extend now do the same
        (all class actions use the same predicate).
        """
        obj, dt = props_for_class(cls_qname)
        return ([(pq, p) for pq, p in obj if not _is_reuse_property(cls_qname, pq)],
                [(pq, p) for pq, p in dt if not _is_reuse_property(cls_qname, pq)])

    # Detect consolidations
    consolidations = detect_consolidations(matrix, class_by_qname)

    # --- TTL emitters ---

    def build_prefixes():
        lines = [
            # Pad to 10 and add an explicit separator: a prefix longer than the
            # padding width must still be separated from the IRI.
            f"@prefix {EDGE_PREFIX:<10s} <{EDGE_NS}> .",
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
        for prefix, ns in source_bindings.values():
            if prefix not in declared:
                lines.append(f"@prefix {prefix + ':':<10s} <{ns}> .")
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
            # Independently settable, and the emitters read it: without
            # its prefix bound, an augmentation whose `augmentsType`
            # differs from `targetType` loses its SHACL constraint and
            # its property is emitted with no domain.
            augmented = m.get("augmentsType")
            if augmented:
                qnames_to_check.append(augmented)
            for pm in (m.get("propertyMappings") or []):
                target_prop = pm.get("targetProperty")
                if target_prop:
                    qnames_to_check.append(target_prop)
                    # Reuse emits `owl:allValuesFrom <the property's declared
                    # type>`, which may live in a namespace no decision
                    # names directly (a code-list namespace, say).
                    filler = target_property_types.get(target_prop)
                    if filler:
                        qnames_to_check.append(filler)
            for qname in qnames_to_check:
                if ":" in qname:
                    prefix = qname.split(":")[0]
                    if prefix not in declared and prefix in target_ns_map:
                        ns_uri = target_ns_map[prefix]
                        lines.append(f"@prefix {prefix + ':':<10s} <{ns_uri}> .")
                        declared.add(prefix)
        lines.append("")
        bound_prefixes.update(declared)
        return "\n".join(lines)

    # Prefixes the emitted header actually binds. A qname whose prefix is
    # not here cannot be written into the TTL (the catalog's namespace map
    # omits some code-list namespaces), so drop such a filler rather
    # than emitting an unparseable document.
    bound_prefixes = set()
    PREFIXES = build_prefixes()

    def target_ref_identity(ref):
        """Expand a rendered target QName so aliases and IRIs compare equally.

        Through `component_iri`, the one home for namespace + name: three
        of the eight namespaces the NODS catalog binds do not end in a
        separator, and concatenating there produced a second spelling of
        one target in the same file.
        """
        prefix, _, name = ref.partition(":")
        namespace = target_ns_map.get(prefix)
        return URIRef(component_iri(namespace, name)).n3() if namespace else ref

    # Every action can place instances under a base target's shapes. Extension
    # shapes still target their own types and retain their specific constraints.
    class_targets = [(q, target) for q, target, _, _ in reuse_classes + extend_classes]
    class_targets.extend((q, augmented) for q, _, _, _, augmented in augment_classes)
    target_type_users = {}
    for cls_qname, target in class_targets:
        ref = target_term_ref(target, target_type_uris)
        if ref:
            target_type_users.setdefault(target_ref_identity(ref), []).append(cls_qname)
    shared_targets = {t for t, users in target_type_users.items() if len(users) > 1}

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
        if superclass:
            lines.append(f"    rdfs:subClassOf {superclass} ;")
        lines.append(f'    rdfs:label "{label or local_name(cls_qname)}" ;')
        if comment:
            safe_comment = comment.replace('"', '\\"').replace('\n', ' ')
            lines.append(f'    rdfs:comment "{safe_comment}" ;')
        lines.append(f'    dcterms:source "{SOURCE}" .')
        lines.extend(emit_reuse_restrictions(cls_qname, type_name))
        lines.append("")

        for pqname, prop in dt_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, action)
            range_vals = prop["range"]
            xsd_type = source_term_ref(xsd_qname(range_vals[0])) if range_vals else "xsd:string"
            plabel = prop.get("label", prop_local)
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:DatatypeProperty ;")
            if cls_qname in prop.get("domain", []):
                lines.append(f"    rdfs:domain {type_name} ;")
            lines.append(f"    rdfs:range {xsd_type} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")

        for pqname, prop in obj_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, action)
            plabel = prop.get("label", prop_local)
            range_ref = object_range_ref(prop["range"])
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:ObjectProperty ;")
            if cls_qname in prop.get("domain", []):
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
        type_ref = _target_to_qname(augmented_type)
        if type_ref:
            lines.extend(emit_reuse_restrictions(cls_qname, type_ref))

        for pqname, prop in dt_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, "augment")
            range_vals = prop["range"]
            xsd_type = source_term_ref(xsd_qname(range_vals[0])) if range_vals else "xsd:string"
            plabel = prop.get("label", prop_local)
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:DatatypeProperty ;")
            if type_ref and cls_qname in prop.get("domain", []):
                lines.append(f"    rdfs:domain {type_ref} ;")
            lines.append(f"    rdfs:range {xsd_type} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")

        for pqname, prop in obj_props:
            prop_local = local_name(pqname)
            prop_ref = resolve_property_ref(pqname, cls_qname, "augment")
            plabel = prop.get("label", prop_local)
            range_ref = object_range_ref(prop["range"])
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:ObjectProperty ;")
            if type_ref and cls_qname in prop.get("domain", []):
                lines.append(f"    rdfs:domain {type_ref} ;")
            lines.append(f"    rdfs:range {range_ref} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")

        return "\n".join(lines)

    def emit_global_properties(unassigned_obj, unassigned_dt, prefix):
        # No reuse-property resolution here, by construction rather than by
        # omission: a property reaches this block only when it belongs to no
        # active class (no rdfs:domain, no SHACL path), and a propertyMapping
        # exists only under a class entry whose property list is derived from
        # exactly those two relations (build_strategy_reports.build_class_properties).
        # Therefore these properties have no per-class reuse decision.
        #
        # Which unassigned properties belong to this package, answered in
        # one place rather than at the call site: the ones this package
        # mints a term for. That is `created_property_qname`'s rule — a
        # primary-namespace term, or one extraction left as a full IRI
        # because the manifest names no prefix for it, which is minted here
        # exactly as a primary one. A term in a source namespace the package
        # binds is referenced through that binding and declared elsewhere;
        # writing it under the edge prefix would declare a term the CMF
        # model never declares.
        #
        # Not `startswith(SOURCE_PREFIX)` alone: the shape emitter resolves
        # an unowned path through `created_property_qname` and named
        # `edge:<local>` for a full-IRI property this block then skipped,
        # so the closure guard refused the package.
        def minted_here(qname):
            return qname.startswith(SOURCE_PREFIX) or is_full_iri(qname)

        unassigned_dt = [p for p in unassigned_dt if minted_here(p)]
        unassigned_obj = [p for p in unassigned_obj if minted_here(p)]
        lines = []
        if not unassigned_obj and not unassigned_dt:
            return ""
        lines.append("\n# ══ Global Properties (no specific domain) ══")
        for pqname in sorted(unassigned_dt):
            if pqname not in dt_by_qname:
                continue
            prop = dt_by_qname[pqname]
            prop_local = local_name(pqname)
            prop_ref = created_property_qname(
                pqname, "reuse", _source, source_bindings, prefix)
            range_vals = prop["range"]
            xsd_type = source_term_ref(xsd_qname(range_vals[0])) if range_vals else "xsd:string"
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
            prop_ref = created_property_qname(
                pqname, "reuse", _source, source_bindings, prefix)
            plabel = prop.get("label", prop_local)
            range_ref = object_range_ref(prop["range"])
            lines.append(f"{prop_ref}")
            lines.append(f"    a owl:ObjectProperty ;")
            lines.append(f"    rdfs:range {range_ref} ;")
            lines.append(f'    rdfs:label "{plabel}" .')
            lines.append("")
        return "\n".join(lines)

    emitted_shape_names = set()
    emitted_source_shapes = {}

    def emit_shape_block(source_shape, prefix, target_src, declaring_sources):
        if not shape_property_is_evaluated(source_shape):
            return ""
        action, target = classify_concept(target_src)
        if action == "reuse" and target:
            target_type = _target_to_qname(target)
        elif action == "extend":
            target_type = "ext:" + edge_class_name(target_src)
        elif action == "augment":
            m = mapping_by_concept.get(target_src, {})
            augmented = m.get("augmentsType") or target
            target_type = _target_to_qname(augmented) if augmented else "owl:Thing"
        else:
            return ""
        if target_type is None:
            return ""

        # Distinct source shapes must not merge severities or constraints.
        base_name = prefix + local_name(target_src) + "Shape"
        shape_name = base_name
        suffix = 2
        while shape_name in emitted_shape_names:
            shape_name = f"{base_name}_{suffix}"
            suffix += 1
        emitted_shape_names.add(shape_name)
        emitted_source_shapes.setdefault(target_src, []).append(shape_name)
        is_shared = target_ref_identity(target_type) in shared_targets

        lines = []
        lines.append(f"\n# ── {local_name(target_src)} Shape ──")
        lines.append(f"{shape_name}")
        lines.append(f"    a sh:NodeShape ;")
        # Shared base targets are validated by the complete source alternatives
        # below. Extension targets still enforce their own complete profile.
        if not is_shared:
            lines.append(f"    sh:targetClass {target_type} ;")
        lines.append(f'    rdfs:label "{local_name(target_src)} Shape" ;')
        severity = source_shape.get("severity")
        if severity:
            severity_iri = severity if ":" in severity else "http://www.w3.org/ns/shacl#" + severity
            lines.append(f"    sh:severity {URIRef(severity_iri).n3()} ;")

        # A property shape whose sh:path is a path EXPRESSION names no
        # property, so there is nothing to emit a constraint on. Filtering
        # first keeps the last-entry terminator correct.
        emittable = []
        for prop in source_shape["properties"]:
            if prop.get("path") and shape_property_is_evaluated(prop):
                # Strategy decisions cover directly assigned properties. An
                # inherited property with no child decision keeps its declaring
                # context; an explicit child decision still takes precedence.
                contexts = ([target_src] if (target_src, prop["path"]) in _prop_mapping_lookup
                            else declaring_sources)
                path_refs = set()
                for context in contexts:
                    for owner, action in emitting_identities(
                            prop["path"], context, target_src):
                        path_refs.add(resolve_property_ref(
                            prop["path"], owner, action))
                refs = sorted(ref for ref in path_refs if ref is not None)
                if refs:
                    emittable.append((prop, refs))
        if not emittable:
            lines[-1] = lines[-1].removesuffix(" ;") + " ."
        def constraint_parts_for(prop, refs, indent):
            """The SHACL constraints for one source property.

            Several emitted identities — two declaring parents that
            mapped the property to different target properties — are one
            `sh:alternativePath`: the source model states the bounds for
            the source property, so they apply across the alternatives
            together, not once per emitted form.
            """
            pad = " " * indent
            path = (refs[0] if len(refs) == 1
                    else "[ sh:alternativePath (" + " ".join(refs) + ") ]")
            parts = [f"{pad}sh:path {path}",
                     f'{pad}sh:name "{local_name(prop["path"])}"']
            severity = prop.get("severity")
            if severity:
                severity_iri = (severity if ":" in severity
                                else "http://www.w3.org/ns/shacl#" + severity)
                parts.append(f"{pad}sh:severity {URIRef(severity_iri).n3()}")
            if prop.get("datatype"):
                parts.append(
                    f'{pad}sh:datatype {source_term_ref(xsd_qname(prop["datatype"]))}')
            elif prop.get("class"):
                mapped_cls = map_range_ref(prop["class"])
                if mapped_cls:
                    parts.append(f"{pad}sh:class {mapped_cls}")
            if prop.get("minCount") is not None:
                parts.append(f'{pad}sh:minCount {prop["minCount"]}')
            if prop.get("maxCount") is not None:
                parts.append(f'{pad}sh:maxCount {prop["maxCount"]}')
            return parts

        for i, (prop, refs) in enumerate(emittable):
            terminator = " ." if i == len(emittable) - 1 else " ;"
            lines.append("    sh:property [")
            lines.append(" ;\n".join(constraint_parts_for(prop, refs, 8)))
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
        obj, dt = declared_props_for_class(cls_qname)
        core_body.append(emit_class_block(cls_qname, target, label, comment, EDGE_PREFIX, obj, dt))

    core_globals = emit_global_properties(obj_unassigned, dt_unassigned, EDGE_PREFIX)

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
        obj, dt = declared_props_for_class(cls_qname)
        ext_body.append(emit_class_block(cls_qname, target, label, comment, "ext:", obj, dt))

    # Augment: emit new properties directly on the augmented type (NIEM pattern —
    # augmentation types are transparent in OWL/RDF, no class declaration needed)
    for cls_qname, target, label, comment, augmented_type in sorted(augment_classes, key=lambda x: x[0]):
        obj_filtered, dt_filtered = declared_props_for_class(cls_qname)
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
    rdfs:comment "SHACL validation shapes. Shared target types accept complete source constraint alternatives." ;
    dcterms:created "{now_iso}"^^xsd:date ;
    owl:versionInfo "1.0.0" .

# Shared targets (multiple source types → same target type):
"""
    for st in sorted(shared_targets):
        users = target_type_users[st]
        shapes_header += f"#   {st} ← {', '.join(users)}\n"

    shapes_body = []
    shared_source_classes = {q for target in shared_targets for q in target_type_users[target]}
    for source_class in sorted(all_active_qnames):
        applicable_classes = {source_class}
        if source_class in shared_source_classes:
            # sh:targetClass applies to subclass instances. Re-render inherited
            # constraints with the child's explicit property decisions, keeping
            # the declaring context for properties without a child decision.
            pending = list(class_by_qname[source_class].get("subClassOf", []))
            while pending:
                parent = pending.pop()
                if parent not in applicable_classes:
                    applicable_classes.add(parent)
                    pending.extend(class_by_qname.get(parent, {}).get("subClassOf", []))
        for shape in inv["shaclShapes"]:
            declaring_sources = applicable_classes.intersection(shape_target_classes(shape))
            if declaring_sources:
                block = emit_shape_block(shape, EDGE_PREFIX, source_class, sorted(declaring_sources))
                if block:
                    shapes_body.append(block)

    for target in sorted(shared_targets):
        branches = []
        for source_class in sorted(target_type_users[target]):
            refs = emitted_source_shapes.get(source_class, [])
            # Multiple shapes on one source class are conjunctive. A class
            # with no active constraints remains a valid unconstrained branch.
            branches.append(f"        [ sh:and ({' '.join(refs)}) ]" if refs else "        []")
        shapes_body.append(
            f"\n[] a sh:NodeShape ;\n    sh:targetClass {target} ;\n    sh:or (\n"
            + "\n".join(branches) + "\n    ) .\n")

    shapes_ttl = shapes_header + "\n".join(shapes_body) + "\n"

    undeclared = undeclared_shape_paths(core_ttl, ext_ttl, shapes_ttl,
                                        (EDGE_NS, EXT_NS))
    if undeclared:
        raise ValueError(
            f"{len(undeclared)} SHACL path(s) name a term in this package's own "
            f"namespaces that no ontology file declares:\n"
            + "\n".join(f"  - {term}" for term in undeclared))

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
        "generatedAt": utc_stamp(),
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
    for term in sorted(set(dropped_target_terms)):
        print(f"  WARNING: target term not emitted (no bound prefix or catalog URI): {term}")
    print(f"  Shared targets (source alternatives): {sorted(shared_targets)}")
    print(f"  Codelists: {len(inv['codelistSchemes'])} schemes, {total_concepts} concepts")
    if consolidations:
        for parent, absorbed, scheme in consolidations:
            print(f"  Synthetic scheme: {scheme} ({len(absorbed)} roles from subtype consolidation)")

    # --- CMF generation (from matrix, all targets) ---
    print(f"\n  Generating CMF artifacts...")
    from ontology_mapper.generate_cmf_from_matrix import MatrixToCmfBuilder
    from ontology_mapper.owl_cmf_bridge import CmfXmlSerializer, cmf_xml_to_json, set_niem_version
    from ontology_mapper.cmf_reference import complete_cmf_references, load_reference_cmf
    from ontology_mapper.ontology_specific import cmf_implicit_roots, cmf_structures_version

    set_niem_version(cmf_structures_version(TARGET_ONTOLOGY, TARGET_VERSION))

    cmf_model = MatrixToCmfBuilder(matrix, inv, ctx, target_ns_map).build()

    cmf_xml_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf"
    cmf_json_path = cmf_dir / f"{ctx.cmf_model_stem}.cmf.json"

    cmf_xml = complete_cmf_references(
        CmfXmlSerializer(cmf_model).serialize(),
        load_reference_cmf(TARGET_ONTOLOGY, TARGET_VERSION),
        implicit_roots=cmf_implicit_roots(TARGET_ONTOLOGY, TARGET_VERSION),
    )
    write_artifact(cmf_xml_path, cmf_xml)
    write_artifact(cmf_json_path, cmf_xml_to_json(cmf_xml))

    print(f"    {cmf_xml_path} ({files_written[str(cmf_xml_path)]:,} bytes)")
    print(f"    {cmf_json_path} ({files_written[str(cmf_json_path)]:,} bytes)")
    print(f"    Namespaces: {len(cmf_model.namespaces)}, Classes: {len(cmf_model.classes)}, Properties: {len(cmf_model.properties)}")


if __name__ == "__main__":
    main()
