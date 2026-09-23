"""Build a CmfModel directly from the mapping matrix and concept inventory.

Builds local CMF declarations and target references for any source/target
combination. cmf_reference completes the serialized model with native definitions.

The builder reads the same inputs as generate_edge_ontology.py (concept
inventory, mapping matrix, target catalog namespace map) and populates
CmfModel dataclasses. It does NOT depend on or modify the OWL generator.
"""

from ontology_mapper.owl_cmf_bridge import (
    CmfAugmentationRecord,
    CmfClass,
    CmfFacet,
    CmfHasProperty,
    CmfModel,
    CmfNamespace,
    CmfProperty,
    CmfRestriction,
)
from ontology_mapper.generation_utils import (
    emitted_class_action,
    range_class_for,
    local_name,
    edge_class_name,
    infer_domains_from_shapes,
    assign_properties_to_classes,
    detect_consolidations,
    property_mapping_index,
    property_qname_resolver,
    accepted_reuse_target,
    shape_target_classes,
    shape_property_is_evaluated,
    source_namespace_bindings,
    created_property_qname,
    source_prefix,
    target_qname,
    is_full_iri,
    qualified_target_property,
    shape_only_class_properties,
)
from ontology_mapper.ontology_specific import extension_conformance_target


# XSD IRI prefix → CMF datatype ref
_XSD_PREFIX = "http://www.w3.org/2001/XMLSchema#"
_XSD_SHORT = "xs:"

# Common XSD IRIs that map to CMF xs.* datatype refs
_XSD_TO_CMF = {
    f"{_XSD_PREFIX}string": "xs.string",
    f"{_XSD_PREFIX}boolean": "xs.boolean",
    f"{_XSD_PREFIX}integer": "xs.integer",
    f"{_XSD_PREFIX}int": "xs.int",
    f"{_XSD_PREFIX}long": "xs.long",
    f"{_XSD_PREFIX}decimal": "xs.decimal",
    f"{_XSD_PREFIX}float": "xs.float",
    f"{_XSD_PREFIX}double": "xs.double",
    f"{_XSD_PREFIX}date": "xs.date",
    f"{_XSD_PREFIX}dateTime": "xs.dateTime",
    f"{_XSD_PREFIX}time": "xs.time",
    f"{_XSD_PREFIX}anyURI": "xs.anyURI",
    f"{_XSD_PREFIX}token": "xs.token",
    f"{_XSD_PREFIX}nonNegativeInteger": "xs.nonNegativeInteger",
    f"{_XSD_PREFIX}positiveInteger": "xs.positiveInteger",
    f"{_XSD_PREFIX}gYear": "xs.gYear",
    f"{_XSD_PREFIX}gYearMonth": "xs.gYearMonth",
    f"{_XSD_PREFIX}duration": "xs.duration",
    f"{_XSD_PREFIX}base64Binary": "xs.base64Binary",
    f"{_XSD_PREFIX}hexBinary": "xs.hexBinary",
}


def _xsd_to_cmf_datatype(iri: str) -> str:
    """Convert an XSD IRI or xs: shorthand to a CMF datatype ref (e.g. 'xs.string')."""
    if iri in _XSD_TO_CMF:
        return _XSD_TO_CMF[iri]
    if iri.startswith(_XSD_SHORT):
        return "xs." + iri[len(_XSD_SHORT):]
    if iri.startswith(_XSD_PREFIX):
        return "xs." + iri[len(_XSD_PREFIX):]
    return "xs.string"  # safe fallback


def _cmf_id(prefix: str, name: str) -> str:
    """Build a CMF structures:id like 'dbpi.PermitApplicationType'."""
    return f"{prefix}.{name}"


def _qname_prefix(qname: str) -> str:
    """Extract namespace prefix from a qualified name (e.g. 'nc:PersonType' → 'nc').

    A full IRI has no prefix — `is_full_iri` answers that for every emitter;
    testing for "http" read `urn:example:x` as the prefix `urn`.
    """
    if ":" in qname and not is_full_iri(qname):
        return qname.split(":", 1)[0]
    return ""


class MatrixToCmfBuilder:
    """Build a CmfModel directly from the mapping matrix and concept inventory.

    Target-ontology agnostic; reference completion follows serialization.
    """

    def __init__(self, matrix: dict, inventory: dict, ctx, target_ns_map: dict):
        self.matrix = matrix
        self.inventory = inventory
        self.ctx = ctx
        self.target_ns_map = target_ns_map

        # Lookups built during init
        self._mapping_by_concept = {m["sourceConcept"]: m for m in matrix["mappings"]}
        self._class_by_qname = {c["qname"]: c for c in inventory["classes"]}
        self._obj_by_qname = {p["qname"]: p for p in inventory["objectProperties"]}
        self._dt_by_qname = {p["qname"]: p for p in inventory["datatypeProperties"]}

        # Primary source prefix (one home: generation_utils.source_prefix).
        # Reading it from the first sorted class let an augmenting namespace
        # that sorts first reclassify every primary property as external.
        primary = source_prefix(inventory)
        self._source_prefix = f"{primary}:" if primary else ""

        # Property mapping lookup, keyed by the property's QNAME — the
        # identity the matrix records. Shared home with the OWL emitter so
        # the two cannot drift (generation_utils.property_mapping_index).
        self._prop_mapping = property_mapping_index(matrix, inventory)
        self._resolve_prop_qname = property_qname_resolver(inventory)

        # Edge/ext prefix for CMF ids (strip trailing ':' and '-edge:')
        self._edge_prefix = ctx.edge_prefix.rstrip(":")  # e.g. "dbpi-edge"
        self._ext_prefix = "ext"
        self._source_bindings = source_namespace_bindings(inventory, target_ns_map, self._edge_prefix)

        # Classified concepts (populated by _classify_concepts)
        self._reuse = []     # (qname, target_type, label, comment)
        self._extend = []    # (qname, base_type, label, comment)
        self._augment = []   # (qname, target_type, label, comment, augmented_type)
        self._active_qnames = set()

        # SHACL cardinality lookup: (class_qname, prop_path) → {minCount, maxCount}
        self._shacl_cardinality = {}
        for shape in inventory.get("shaclShapes", []):
            if not shape_property_is_evaluated(shape):
                continue
            for cls in shape_target_classes(shape):
                for prop in shape.get("properties", []):
                    if not prop.get("path") or not shape_property_is_evaluated(prop):
                        continue        # a SHACL path expression names no property
                    bounds = self._shacl_cardinality.setdefault((cls, prop["path"]), {})
                    for key, combine in (("minCount", max), ("maxCount", min)):
                        value = prop.get(key)
                        if value is not None:
                            bounds[key] = combine(bounds.get(key, value), value)

    def build(self) -> CmfModel:
        """Build local components and references from the accepted matrix."""
        model = CmfModel()
        self._classify_concepts()
        self._build_namespaces(model)
        self._build_classes(model)
        self._build_properties(model)
        self._build_augmentations(model)
        self._build_codelists(model)
        return model

    # ------------------------------------------------------------------
    # Concept classification
    # ------------------------------------------------------------------

    def _classify_concepts(self):
        """Classify inventory classes by their matrix action."""
        for cls in self.inventory["classes"]:
            qname = cls["qname"]
            m = self._mapping_by_concept.get(qname)
            action = emitted_class_action(m)
            if action is None:
                continue
            target = m.get("targetType")
            if action == "reuse":
                self._reuse.append((qname, target, cls["label"], cls["comment"]))
            elif action == "extend":
                base = m.get("baseType") or target
                self._extend.append((qname, base, cls["label"], cls["comment"]))
            elif action == "augment":
                augmented = m.get("augmentsType") or target
                self._augment.append((qname, target, cls["label"], cls["comment"], augmented))

        self._active_qnames = (
            {q for q, _, _, _ in self._reuse}
            | {q for q, _, _, _ in self._extend}
            | {q for q, _, _, _, _ in self._augment}
        )

    # ------------------------------------------------------------------
    # Namespaces
    # ------------------------------------------------------------------

    def _build_namespaces(self, model: CmfModel):
        """Create CmfNamespace entries for edge, ext, and target namespaces."""
        conformance = extension_conformance_target(
            self.ctx.target_ontology, self.ctx.target_version)

        # Edge namespace (always present)
        model.namespaces.append(CmfNamespace(
            ns_id=self._edge_prefix,
            uri=self.ctx.edge_ns_hash,
            prefix=self._edge_prefix,
            documentation=f"Edge ontology for {self.ctx.source}",
            category="EXTENSION",
            conformance_target=conformance,
        ))

        # Extension namespace. Declared for augment classes too, not only
        # extend ones: `_property_prefix` returns the EXT prefix for EVERY
        # non-reuse action, so an augment-only run emitted properties into
        # a namespace the model never declared.
        if self._extend or self._augment:
            model.namespaces.append(CmfNamespace(
                ns_id=self._ext_prefix,
                uri=self.ctx.ext_ns_hash,
                prefix=self._ext_prefix,
                documentation=f"Extension types for {self.ctx.source}",
                category="EXTENSION",
                conformance_target=conformance,
            ))

        # Target namespaces referenced by reuse/augment mappings
        seen_prefixes = {self._edge_prefix, self._ext_prefix}
        for qname, target, _, _ in self._reuse:
            self._add_target_ns(model, target, seen_prefixes)
        for qname, target, _, _, augmented in self._augment:
            self._add_target_ns(model, target, seen_prefixes)
            self._add_target_ns(model, augmented, seen_prefixes)
        for qname, base, _, _ in self._extend:
            self._add_target_ns(model, base, seen_prefixes)
        for mapping in self.matrix["mappings"]:
            for pm in mapping.get("propertyMappings") or []:
                self._add_target_ns(model, qualified_target_property(
                    accepted_reuse_target(pm), mapping.get("targetType")), seen_prefixes)

        # Source namespace for cross-namespace properties
        properties = self.inventory["objectProperties"] + self.inventory["datatypeProperties"]
        # A full-IRI range `_resolve_range` grounds to a target class names
        # that class's namespace; it reads the first range only, so only
        # that one can.
        for prop in properties:
            for r in prop.get("range", [])[:1]:
                if is_full_iri(r):
                    self._add_target_ns(model, r, seen_prefixes)
        source_refs = {prop["qname"] for prop in properties}
        source_refs.update(r for prop in properties for r in prop.get("range", [])
                           if _qname_prefix(r) in self._source_bindings)
        for qname in sorted(source_refs):
            if not qname.startswith(self._source_prefix):
                prefix = _qname_prefix(qname)
                prefix, uri = self._source_bindings.get(prefix, (
                    prefix, self.target_ns_map.get(prefix, f"urn:unknown:{prefix}")))
                if prefix and prefix not in seen_prefixes:
                    model.namespaces.append(CmfNamespace(
                        ns_id=prefix, uri=uri, prefix=prefix,
                        category="EXTERNAL",
                    ))
                    seen_prefixes.add(prefix)

    def _add_target_ns(self, model: CmfModel, qname: str, seen: set):
        """Add a target namespace if not already present."""
        if not qname:
            return
        prefix = _qname_prefix(target_qname(qname, self.target_ns_map))
        if not prefix or prefix in seen:
            return
        uri = self.target_ns_map.get(prefix, f"urn:unknown:{prefix}")
        model.namespaces.append(CmfNamespace(
            ns_id=prefix, uri=uri, prefix=prefix,
            category="EXTERNAL",
        ))
        seen.add(prefix)

    # ------------------------------------------------------------------
    # Classes
    # ------------------------------------------------------------------

    def _build_classes(self, model: CmfModel):
        """Create CmfClass entries for reuse and extend actions."""
        for qname, target, label, comment in self._reuse:
            type_name = edge_class_name(qname)
            target_id = self._qname_to_cmf_id(target) if target else ""
            model.classes.append(CmfClass(
                class_id=_cmf_id(self._edge_prefix, type_name),
                name=type_name,
                namespace_ref=self._edge_prefix,
                documentation=comment or label or "",
                sub_class_of=target_id,
            ))

        for qname, base, label, comment in self._extend:
            type_name = edge_class_name(qname)
            base_id = self._qname_to_cmf_id(base) if base else ""
            model.classes.append(CmfClass(
                class_id=_cmf_id(self._ext_prefix, type_name),
                name=type_name,
                namespace_ref=self._ext_prefix,
                documentation=comment or label or "",
                sub_class_of=base_id,
            ))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def _build_properties(self, model: CmfModel):
        """Create CmfProperty + CmfHasProperty for all active classes."""
        # Assign properties to classes using domain + SHACL inference
        shape_domains = infer_domains_from_shapes(
            self.inventory["objectProperties"] + self.inventory["datatypeProperties"],
            self.inventory.get("shaclShapes", []),
        )
        obj_assigned, _ = assign_properties_to_classes(
            self.inventory["objectProperties"], self._active_qnames, shape_domains)
        dt_assigned, _ = assign_properties_to_classes(
            self.inventory["datatypeProperties"], self._active_qnames, shape_domains)

        # Include cross-namespace properties with explicit domains
        for prop in self.inventory["datatypeProperties"]:
            if not prop["qname"].startswith(self._source_prefix) and prop["domain"]:
                active = [d for d in prop["domain"] if d in self._active_qnames]
                if active and prop["qname"] not in dt_assigned:
                    dt_assigned[prop["qname"]] = active

        shape_only = shape_only_class_properties(self.inventory)

        # Build class_id lookup for property assignment
        class_id_by_qname = {}
        for qname, _, _, _ in self._reuse:
            class_id_by_qname[qname] = _cmf_id(self._edge_prefix, edge_class_name(qname))
        for qname, _, _, _ in self._extend:
            class_id_by_qname[qname] = _cmf_id(self._ext_prefix, edge_class_name(qname))

        # Track emitted properties to avoid duplicates
        emitted_props = set()

        # Process each active class
        for cls_qname in sorted(self._active_qnames):
            cls_cmf_id = class_id_by_qname.get(cls_qname)
            if not cls_cmf_id:
                continue  # augment classes don't get a CmfClass

            cmf_cls = self._find_class(model, cls_cmf_id)
            if not cmf_cls:
                continue

            m = self._mapping_by_concept.get(cls_qname, {})
            action = m.get("action", "")

            # Collect properties for this class
            obj_props = [(pq, self._obj_by_qname[pq])
                         for pq in sorted(obj_assigned)
                         if cls_qname in obj_assigned[pq] and pq in self._obj_by_qname]
            dt_props = [(pq, self._dt_by_qname[pq])
                        for pq in sorted(dt_assigned)
                        if cls_qname in dt_assigned[pq] and pq in self._dt_by_qname]

            for pq, prop_data in obj_props:
                self._emit_property(model, cmf_cls, cls_qname, action,
                                    pq, prop_data, is_object=True, emitted=emitted_props)

            for pq, prop_data in dt_props:
                self._emit_property(model, cmf_cls, cls_qname, action,
                                    pq, prop_data, is_object=False, emitted=emitted_props)

            # A property only a shape names is never minted, but its accepted
            # reuse is a reference to the target property like any other;
            # completion gives the reference the native property's kind.
            for pq in shape_only.get(cls_qname, []):
                if accepted_reuse_target(self._prop_mapping.get((cls_qname, pq))):
                    self._emit_property(model, cmf_cls, cls_qname, action,
                                        pq, {}, is_object=False, emitted=emitted_props)

    def _property_prefix(self, cls_action: str, prop_qname: str) -> str:
        """The CMF namespace a created property is emitted under.

        The augmentation records must name exactly the ids
        `_emit_property` declares. The augment branch previously built its
        refs with the EDGE prefix while the declaration side uses EXT for
        every non-reuse action, so every augment record pointed at an id
        the model does not contain.
        """
        return created_property_qname(
            prop_qname, cls_action, self._source_prefix.rstrip(":"),
            self._source_bindings, self._edge_prefix).split(":", 1)[0]

    def _emit_property(self, model: CmfModel, cmf_cls: CmfClass,
                       cls_qname: str, cls_action: str,
                       prop_qname: str, prop_data: dict,
                       is_object: bool, emitted: set):
        """Emit a CmfProperty and add a CmfHasProperty to the class."""
        prop_local = local_name(prop_qname)

        # Check for reuse-property mapping
        target_prop = accepted_reuse_target(self._prop_mapping.get((cls_qname, prop_qname)))
        if target_prop:
            # Property already exists on target — just reference it
            target_id = self._qname_to_cmf_id(qualified_target_property(
                target_prop, self._mapping_by_concept.get(cls_qname, {}).get("targetType")))
            min_occ, max_occ = self._get_cardinality(cls_qname, prop_qname)
            cmf_cls.properties.append(CmfHasProperty(
                property_ref=target_id,
                is_object=is_object,
                min_occurs=min_occ,
                max_occurs=max_occ,
            ))
            return

        prop_prefix = self._property_prefix(cls_action, prop_qname)
        prop_name = prop_local
        prop_id = _cmf_id(prop_prefix, prop_name)

        # Emit the property definition (once)
        if prop_id not in emitted:
            emitted.add(prop_id)

            class_ref = ""
            datatype_ref = ""
            if is_object:
                class_ref = self._resolve_range(prop_data.get("range", []))
            else:
                datatype_ref = self._resolve_datatype(prop_data.get("range", []))

            model.properties.append(CmfProperty(
                prop_id=prop_id,
                name=prop_name,
                namespace_ref=prop_prefix,
                documentation=prop_data.get("label", ""),
                is_object=is_object,
                class_ref=class_ref,
                datatype_ref=datatype_ref,
            ))

        # Add ChildPropertyAssociation to the class
        min_occ, max_occ = self._get_cardinality(cls_qname, prop_qname)
        cmf_cls.properties.append(CmfHasProperty(
            property_ref=prop_id,
            is_object=is_object,
            min_occurs=min_occ,
            max_occurs=max_occ,
        ))

    def _resolve_range(self, ranges: list) -> str:
        """Resolve object property range to a CMF class ref.

        The first range only, as the OWL emitter's `object_range_ref` reads
        it: resolving a later one named a range the OWL left open.
        """
        for r in ranges[:1]:
            if r.startswith(_XSD_PREFIX) or r.startswith(_XSD_SHORT):
                continue
            if r.startswith(self._source_prefix) or r in self._class_by_qname:
                mapped = self._map_source_class_ref(r)
                if mapped:
                    return mapped
            else:
                # A full IRI in a namespace the target catalog binds is
                # grounded as the OWL emitter's `map_range_ref` grounds it,
                # so both models name the same range.
                grounded = target_qname(r, self.target_ns_map)
                if grounded != r:
                    return self._qname_to_cmf_id(grounded)
                # External range — use as-is
                prefix = _qname_prefix(r)
                if prefix:
                    prefix = self._source_bindings.get(prefix, (prefix, ""))[0]
                    return _cmf_id(prefix, local_name(r))
        return ""

    def _resolve_datatype(self, ranges: list) -> str:
        """Resolve datatype property range to a CMF datatype ref."""
        for r in ranges:
            if r.startswith(_XSD_PREFIX) or r.startswith(_XSD_SHORT):
                return _xsd_to_cmf_datatype(r)
        return "xs.string"  # default

    def _map_source_class_ref(self, qname: str) -> str:
        """Map a source class reference to a CMF class id via the mapping matrix.

        An excluded class resolves through `range_class_for`, the redirect
        the OWL emitter uses too.
        """
        emitted = range_class_for(qname, self._mapping_by_concept, self._class_by_qname)
        if emitted is None:
            return ""
        m = self._mapping_by_concept[emitted]
        action = emitted_class_action(m)
        target = m.get("targetType")

        if action == "reuse" and target:
            return self._qname_to_cmf_id(target)
        elif action == "extend":
            return _cmf_id(self._ext_prefix, edge_class_name(emitted))
        elif action == "augment" and target:
            return self._qname_to_cmf_id(target)
        return ""

    def _get_cardinality(self, cls_qname: str, prop_qname: str) -> tuple:
        """Get (min_occurs, max_occurs) from SHACL shapes."""
        card = self._shacl_cardinality.get((cls_qname, prop_qname))
        if card:
            min_c = card.get("minCount")
            max_c = card.get("maxCount")
            return (min_c if min_c is not None else 0,
                    str(max_c) if max_c is not None else "unbounded")
        return (0, "unbounded")

    # ------------------------------------------------------------------
    # Augmentations
    # ------------------------------------------------------------------

    def _build_augmentations(self, model: CmfModel):
        """Create AugmentationRecords for new properties on reuse/augment classes."""
        edge_ns = self._find_namespace(model, self._edge_prefix)
        if not edge_ns:
            return
        declared = {p.prop_id for p in model.properties}
        # Only identical records are redundant. Different occurrences
        # carry different source assertions and must not be selected by
        # inventory order or silently merged into a new policy.
        recorded = {(a.class_ref, a.property_ref, a.is_object, a.min_occurs, a.max_occurs)
                    for a in edge_ns.augmentations}

        def record(class_ref, property_ref, is_object, min_occurs, max_occurs):
            key = (class_ref, property_ref, is_object, min_occurs, max_occurs)
            if key in recorded:
                return
            recorded.add(key)
            edge_ns.augmentations.append(CmfAugmentationRecord(
                class_ref=class_ref,
                property_ref=property_ref,
                is_object=is_object,
                min_occurs=min_occurs,
                max_occurs=max_occurs,
            ))

        # Reuse classes: new (non-reused) properties augment the target type
        for qname, target, _, _ in self._reuse:
            if not target:
                continue
            target_id = self._qname_to_cmf_id(target)
            cls_cmf_id = _cmf_id(self._edge_prefix, edge_class_name(qname))
            cmf_cls = self._find_class(model, cls_cmf_id)
            if not cmf_cls:
                continue

            for hp in cmf_cls.properties:
                # Skip reuse-property refs (they're already on the target).
                # A created property is one this model declares, whichever
                # namespace it was emitted under: a property owned by an
                # augmenting source namespace is declared under that
                # namespace's prefix, not the edge prefix.
                if hp.property_ref in declared:
                    record(target_id, hp.property_ref, hp.is_object,
                           hp.min_occurs, hp.max_occurs)

        # A property only a shape names is never minted, but its accepted
        # reuse augments the target type as a declared one's does.
        shape_only = shape_only_class_properties(self.inventory)

        # Augment classes: all new properties augment the augmented type
        for qname, target, _, _, augmented in self._augment:
            augmented_id = self._qname_to_cmf_id(augmented) if augmented else ""
            if not augmented_id:
                continue

            # Find properties assigned to this augment class. An augment
            # class has no CmfClass (augmentation is transparent), so its
            # created properties are declared here — without this they were
            # referenced by every record and defined by none.
            m = self._mapping_by_concept.get(qname, {})
            for pm in m.get("propertyMappings") or []:
                # Resolve through the same reconciliation the property
                # index uses. Reading the raw `sourceProperty` here meant a
                # mis-qualified augmenting-namespace name failed the
                # inventory lookup and the decision vanished silently.
                prop_qname = self._resolve_prop_qname(pm.get("sourceProperty", ""), qname)
                prop_data = (self._obj_by_qname.get(prop_qname)
                             or self._dt_by_qname.get(prop_qname))
                if prop_data is None and prop_qname not in shape_only.get(qname, []):
                    continue  # not a property of the source inventory
                is_object = prop_qname in self._obj_by_qname
                target_prop = accepted_reuse_target(pm)
                if target_prop:
                    # Augment is selected when a match exists elsewhere in the
                    # target ontology. Reference it; do not declare it again.
                    min_occ, max_occ = self._get_cardinality(qname, prop_qname)
                    record(augmented_id, self._qname_to_cmf_id(qualified_target_property(
                               target_prop, self._mapping_by_concept.get(qname, {}).get("targetType"))),
                           is_object, min_occ, max_occ)
                    continue
                if prop_data is None:
                    continue  # a shape-only term is referenced, never minted
                prop_prefix = self._property_prefix("augment", prop_qname)
                prop_id = _cmf_id(prop_prefix, local_name(prop_qname))
                if prop_id not in declared:
                    declared.add(prop_id)
                    model.properties.append(CmfProperty(
                        prop_id=prop_id,
                        name=local_name(prop_qname),
                        namespace_ref=prop_prefix,
                        documentation=prop_data.get("label", ""),
                        is_object=is_object,
                        class_ref=(self._resolve_range(prop_data.get("range", []))
                                   if is_object else ""),
                        datatype_ref=("" if is_object
                                      else self._resolve_datatype(prop_data.get("range", []))),
                    ))
                # The occurrence the source asserts, not a hardcoded default.
                min_occ, max_occ = self._get_cardinality(qname, prop_qname)
                record(augmented_id, prop_id, is_object, min_occ, max_occ)

        edge_ns.augmentations.sort(key=lambda a: (
            a.class_ref, a.property_ref, a.is_object, a.min_occurs, a.max_occurs))

    # ------------------------------------------------------------------
    # Codelists
    # ------------------------------------------------------------------

    def _build_codelists(self, model: CmfModel):
        """Create CmfRestriction entries for codelist schemes."""
        for scheme in self.inventory.get("codelistSchemes", []):
            scheme_local = local_name(scheme["iri"])
            restriction_id = _cmf_id(self._edge_prefix, scheme_local)

            facets = []
            for concept in scheme.get("concepts", []):
                concept_local = local_name(concept["iri"])
                facets.append(CmfFacet(
                    category="enumeration",
                    value=concept_local,
                    documentation=concept.get("label", ""),
                ))

            model.restrictions.append(CmfRestriction(
                restriction_id=restriction_id,
                name=scheme_local,
                namespace_ref=self._edge_prefix,
                documentation=f"Codelist for {scheme_local}",
                restriction_base="xs.token",
                facets=facets,
            ))

        # Consolidated subtype schemes
        consolidations = detect_consolidations(self.matrix, self._class_by_qname)
        for parent, absorbed, scheme_name in consolidations:
            restriction_id = _cmf_id(self._edge_prefix, scheme_name)
            facets = []
            for absorbed_qname in sorted(absorbed):
                role_local = local_name(absorbed_qname)
                facets.append(CmfFacet(
                    category="enumeration",
                    value=role_local,
                    documentation=role_local,
                ))
            model.restrictions.append(CmfRestriction(
                restriction_id=restriction_id,
                name=scheme_name,
                namespace_ref=self._edge_prefix,
                documentation=f"Role scheme from subtype consolidation of {local_name(parent)}",
                restriction_base="xs.token",
                facets=facets,
            ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _qname_to_cmf_id(self, qname: str) -> str:
        """Convert a qualified name (e.g. 'nc:PersonType') to CMF id ('nc.PersonType').

        An accepted full IRI is grounded to its catalog QName first; the class
        policy admits IRIs, so the emitter must carry them. An IRI outside the
        catalog namespaces is left as-is for reference validation to report.
        """
        if not qname:
            return ""
        qname = target_qname(qname, self.target_ns_map)
        if ":" in qname and not is_full_iri(qname):
            prefix, name = qname.split(":", 1)
            return _cmf_id(prefix, name)
        return qname

    def _find_class(self, model: CmfModel, class_id: str):
        """Find a CmfClass by its id."""
        for cls in model.classes:
            if cls.class_id == class_id:
                return cls
        return None

    def _find_namespace(self, model: CmfModel, ns_id: str):
        """Find a CmfNamespace by its id."""
        for ns in model.namespaces:
            if ns.ns_id == ns_id:
                return ns
        return None
