"""Tests for generate_cmf_from_matrix.MatrixToCmfBuilder.

Uses synthetic matrix/inventory dicts — no real pipeline runs or fixtures.
Validates spec compliance per NIEM NDR v6.0 CMF rules.
"""

import pytest
from pathlib import Path
from types import SimpleNamespace

from ontology_mapper.generate_cmf_from_matrix import MatrixToCmfBuilder
from ontology_mapper.owl_cmf_bridge import (
    CmfXmlSerializer,
    CmfXmlParser,
    set_niem_version,
)


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------

def _make_matrix(mappings):
    return {"mappings": mappings}


def _make_mapping(source, action, target_type=None, base_type=None,
                  augments_type=None, property_mappings=None):
    m = {
        "sourceConcept": source,
        "action": action,
        "targetType": target_type,
        "rationale": "test",
        "reviewStatus": "accepted",
    }
    if base_type:
        m["baseType"] = base_type
    if augments_type:
        m["augmentsType"] = augments_type
    if property_mappings:
        m["propertyMappings"] = property_mappings
    return m


def _make_prop_mapping(source_prop, action="create-property",
                       target_prop=None, review="accepted"):
    return {
        "sourceProperty": source_prop,
        "action": action,
        "targetProperty": target_prop,
        "reviewStatus": review,
    }


def _make_class(qname, label="", comment="", sub_class_of=None):
    return {
        "qname": qname,
        "label": label,
        "comment": comment,
        "subClassOf": sub_class_of or [],
    }


def _make_obj_prop(qname, label="", domain=None, range_list=None):
    return {
        "qname": qname,
        "label": label,
        "domain": domain or [],
        "range": range_list or [],
    }


def _make_dt_prop(qname, label="", domain=None, range_list=None):
    return {
        "qname": qname,
        "label": label,
        "domain": domain or [],
        "range": range_list or ["http://www.w3.org/2001/XMLSchema#string"],
    }


def _make_shape(target_class, properties):
    return {
        "targetClass": target_class,
        "properties": properties,
    }


def _make_shape_prop(path, min_count=None, max_count=None):
    p = {"path": path}
    if min_count is not None:
        p["minCount"] = min_count
    if max_count is not None:
        p["maxCount"] = max_count
    return p


def _make_codelist(iri, concepts):
    return {
        "iri": iri,
        "conceptCount": len(concepts),
        "concepts": concepts,
    }


def _make_concept(iri, label=""):
    return {"iri": iri, "label": label}


def _make_inventory(classes=None, obj_props=None, dt_props=None,
                    shapes=None, codelists=None):
    return {
        "classes": classes or [],
        "objectProperties": obj_props or [],
        "datatypeProperties": dt_props or [],
        "shaclShapes": shapes or [],
        "codelistSchemes": codelists or [],
    }


def _make_ctx(edge_prefix="test-edge:", source="test",
              organization="testorg",
              target_ontology="niem", target_version="6.0"):
    return SimpleNamespace(
        edge_ns_hash=f"http://{organization}.gov/{source}/edge#",
        ext_ns_hash=f"http://{organization}.gov/{source}/ext#",
        edge_prefix=edge_prefix,
        source=source,
        organization=organization,
        target_ontology=target_ontology,
        target_version=target_version,
        cmf_model_stem=f"{source}-model",
    )


def _build(matrix, inventory, ctx=None, target_ns_map=None):
    if ctx is None:
        ctx = _make_ctx()
    if target_ns_map is None:
        target_ns_map = {"nc": "http://example.org/niem-core/6.0"}
    builder = MatrixToCmfBuilder(matrix, inventory, ctx, target_ns_map)
    return builder.build()


def test_explicit_domain_and_subclass_shape_keep_both_reviewed_occurrences():
    from rdflib import Graph, RDFS, OWL, URIRef
    from .test_generate_edge_ontology import TestNiemOWLPatterns

    inv = _make_inventory(
        classes=[_make_class("src:A"), _make_class("src:B", sub_class_of=["src:A"])],
        dt_props=[_make_dt_prop("src:code", domain=["src:A"])],
        shapes=[_make_shape("src:B", [_make_shape_prop("src:code", 1, 1)])])
    matrix = _make_matrix([_make_mapping(q, "reuse", target, property_mappings=[
        _make_prop_mapping("src:code", "reuse-property", "nc:CodeText")])
        for q, target in [("src:A", "nc:BaseType"), ("src:B", "nc:SpecialType")]])
    [b] = [cls for cls in _build(matrix, inv).classes if cls.name == "BType"]
    assert [(p.property_ref, p.min_occurs, p.max_occurs) for p in b.properties] == [("nc.CodeText", 1, "1")]
    files = TestNiemOWLPatterns._run_generation(inv, matrix)
    graph = Graph().parse(data=files["test-edge-core.ttl"], format="turtle")
    b_ref = URIRef("http://testorg.gov/test/edge#BType")
    assert any(graph.value(r, OWL.onProperty) is not None for r in graph.objects(b_ref, RDFS.subClassOf))


@pytest.mark.parametrize("action", ["reuse", "extend", "augment"])
@pytest.mark.parametrize("collision", [False, True])
@pytest.mark.parametrize("object_property", [False, True])
def test_source_and_target_namespace_identities_agree_in_both_formats(action, collision, object_property):
    from rdflib import Graph, RDFS, SH, OWL, URIRef
    from .test_generate_edge_ontology import TestNiemOWLPatterns

    target_uri = "https://example.org/target-nc/"
    source_uri = "https://example.org/source-nc/" if collision else target_uri
    inv = _make_inventory(classes=[_make_class("src:X")],
        dt_props=[_make_dt_prop("nc:custom", domain=["src:X"]), _make_dt_prop("src:standard", domain=["src:X"])],
        shapes=[_make_shape("src:X", [_make_shape_prop("nc:custom", 1, 1), _make_shape_prop("src:standard")])])
    if object_property:
        inv["datatypeProperties"] = inv["datatypeProperties"][1:]
        inv["objectProperties"] = [_make_obj_prop("nc:custom", domain=["src:X"], range_list=["nc:OtherType"])]
    inv["namespaceMap"] = {source_uri: "nc:"}
    inv["augmentingNamespaces"] = [{"prefix": "nc", "namespace": source_uri}]
    matrix = _make_matrix([_make_mapping("src:X", action, "nc:BaseType", property_mappings=[
        _make_prop_mapping("nc:custom"), _make_prop_mapping("src:standard", "reuse-property", "nc:KnownText")])])
    model = _build(matrix, inv, target_ns_map={"nc": target_uri})
    namespaces = {ns.ns_id: ns.uri for ns in model.namespaces}
    assert namespaces["nc"] == target_uri
    [created] = model.properties
    assert namespaces[created.namespace_ref] + created.name == source_uri + "custom"
    if object_property:
        prefix, local = created.class_ref.split(".", 1)
        assert namespaces[prefix] + local == source_uri + "OtherType"
    refs = [p.property_ref for cls in model.classes for p in cls.properties]
    refs += [a.property_ref for ns in model.namespaces for a in ns.augmentations]
    assert created.prop_id in refs and "nc.KnownText" in refs

    files = TestNiemOWLPatterns._run_generation(inv, matrix, catalog={"namespaces": {"nc": target_uri}})
    graph = Graph()
    for name in ("test-edge-core.ttl", "test-edge-extensions.ttl", "test-edge-shapes.ttl"):
        graph.parse(data=files[name], format="turtle")
    assert (URIRef(source_uri + "custom"), None, None) in graph
    assert URIRef(source_uri + "custom") in set(graph.objects(None, SH.path))
    assert URIRef(target_uri + "KnownText") in set(graph.objects(None, OWL.onProperty))
    if object_property:
        assert graph.value(URIRef(source_uri + "custom"), RDFS.range) == URIRef(source_uri + "OtherType")
    if action == "augment":
        assert graph.value(URIRef(source_uri + "custom"), RDFS.domain) == URIRef(target_uri + "BaseType")


@pytest.mark.parametrize("bounds", [(1, 2), (0, 0), (1, None), (None, 2)])
def test_cmf_conjoins_all_active_bounds_independently_of_shape_order(bounds):
    minimum, maximum = bounds
    shapes = [_make_shape("src:A", [_make_shape_prop("src:p", min_count=minimum)]),
              _make_shape("src:A", [_make_shape_prop("src:p", max_count=maximum)]),
              {**_make_shape("src:A", [_make_shape_prop("src:p", 50, 50)]), "deactivated": True}]
    matrix = _make_matrix([_make_mapping("src:A", "extend", "nc:BaseType")])
    for ordering in (shapes, list(reversed(shapes))):
        inv = _make_inventory(classes=[_make_class("src:A")],
            dt_props=[_make_dt_prop("src:p", domain=["src:A"])], shapes=ordering)
        [prop] = _build(matrix, inv).classes[0].properties
        assert (prop.min_occurs, prop.max_occurs) == (minimum or 0, str(maximum) if maximum is not None else "unbounded")


def test_namespace_used_only_by_object_range_is_declared():
    inv = _make_inventory(classes=[_make_class("src:X")],
        obj_props=[_make_obj_prop("src:link", domain=["src:X"], range_list=["nc:OtherType"])])
    inv["namespaceMap"] = {"https://example.org/source/": "nc:"}
    matrix = _make_matrix([_make_mapping("src:X", "extend", "nc:BaseType")])
    model = _build(matrix, inv, target_ns_map={"nc": "https://example.org/target/"})
    [prop] = model.properties
    prefix, local = prop.class_ref.split(".", 1)
    namespaces = {ns.ns_id: ns.uri for ns in model.namespaces}
    assert namespaces[prefix] + local == "https://example.org/source/OtherType"


# ---------------------------------------------------------------------------
# Tests: Namespaces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("deactivate", ["shape", "property", None])
def test_cmf_uses_only_active_shape_bounds(deactivate):
    prop = {"path": "src:value", "minCount": 1, "maxCount": 1,
            "severity": "Warning", "deactivated": deactivate == "property"}
    inv = _make_inventory(classes=[_make_class("src:Foo")],
                          dt_props=[_make_dt_prop("src:value", domain=["src:Foo"])],
                          shapes=[{"targetClass": "src:Foo", "properties": [prop],
                                   "deactivated": deactivate == "shape"}])
    model = _build(_make_matrix([_make_mapping("src:Foo", "reuse", "nc:PersonType")]), inv)
    [hp] = model.classes[0].properties
    assert (hp.min_occurs, hp.max_occurs) == ((1, "1") if deactivate is None else (0, "unbounded"))


class TestConformanceTarget:
    """every EXTENSION-category namespace asserts the target ontology's
    conformance target, taken from its ontology-specific policy."""
    EXPECTED = "https://docs.oasis-open.org/niemopen/ns/specification/NDR/6.0/#ExtensionSchemaDocument"

    def test_extension_namespaces_assert_it(self):
        inv = _make_inventory(classes=[_make_class("src:Foo"), _make_class("src:Bar")])
        matrix = _make_matrix([
            _make_mapping("src:Foo", "reuse", "nc:PersonType"),
            _make_mapping("src:Bar", "extend", "nc:PersonType", base_type="nc:PersonType"),
        ])
        model = _build(matrix, inv)
        extensions = [n for n in model.namespaces if n.category == "EXTENSION"]
        assert len(extensions) == 2
        assert all(n.conformance_target == self.EXPECTED for n in extensions)

    def test_external_namespaces_do_not(self):
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        model = _build(_make_matrix([_make_mapping("src:Foo", "reuse", "nc:PersonType")]), inv)
        for n in model.namespaces:
            if n.category != "EXTENSION":
                assert not n.conformance_target

    def test_a_target_without_a_pack_asserts_nothing(self):
        """No invented URI for an ontology whose pack declares no such rule."""
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        ctx = _make_ctx(target_ontology="sali-folio", target_version="2.0")
        model = _build(_make_matrix([_make_mapping("src:Foo", "reuse", "nc:PersonType")]),
                       inv, ctx=ctx)
        assert all(not n.conformance_target for n in model.namespaces)


class TestNamespaces:
    def test_edge_namespace_always_created(self):
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        edge_ns = [n for n in model.namespaces if n.ns_id == "test-edge"]
        assert len(edge_ns) == 1
        assert edge_ns[0].category == "EXTENSION"
        assert edge_ns[0].uri == "http://testorg.gov/test/edge#"

    def test_ext_namespace_only_when_extend_exists(self):
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        ext_ns = [n for n in model.namespaces if n.ns_id == "ext"]
        assert len(ext_ns) == 0

    def test_ext_namespace_created_for_extend(self):
        inv = _make_inventory(classes=[_make_class("src:Bar")])
        matrix = _make_matrix([_make_mapping("src:Bar", "extend", base_type="nc:BaseType")])
        model = _build(matrix, inv)

        ext_ns = [n for n in model.namespaces if n.ns_id == "ext"]
        assert len(ext_ns) == 1
        assert ext_ns[0].category == "EXTENSION"

    def test_target_namespace_created_for_reuse(self):
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        nc_ns = [n for n in model.namespaces if n.ns_id == "nc"]
        assert len(nc_ns) == 1
        assert nc_ns[0].category == "EXTERNAL"

    def test_no_duplicate_namespaces(self):
        inv = _make_inventory(classes=[
            _make_class("src:A"),
            _make_class("src:B"),
        ])
        matrix = _make_matrix([
            _make_mapping("src:A", "reuse", "nc:AType"),
            _make_mapping("src:B", "reuse", "nc:BType"),
        ])
        model = _build(matrix, inv)

        nc_count = sum(1 for n in model.namespaces if n.ns_id == "nc")
        assert nc_count == 1

    def test_namespace_category_values_are_valid(self):
        valid = {"BUILTIN", "CLI", "CORE", "DOMAIN", "EXTENSION",
                 "EXTERNAL", "OTHERNIEM", "UNKNOWN", "XML", "XSD"}
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        for ns in model.namespaces:
            assert ns.category in valid, f"Invalid category: {ns.category}"


# ---------------------------------------------------------------------------
# Tests: Classes
# ---------------------------------------------------------------------------

class TestClasses:
    def test_reuse_creates_class_with_subclass(self):
        inv = _make_inventory(classes=[_make_class("src:Person", comment="A person.")])
        matrix = _make_matrix([_make_mapping("src:Person", "reuse", "nc:PersonType")])
        model = _build(matrix, inv)

        assert len(model.classes) == 1
        cls = model.classes[0]
        assert cls.name == "PersonType"
        assert cls.class_id == "test-edge.PersonType"
        assert cls.sub_class_of == "nc.PersonType"
        assert cls.namespace_ref == "test-edge"
        assert cls.documentation == "A person."

    def test_extend_creates_class_in_ext_namespace(self):
        inv = _make_inventory(classes=[_make_class("src:Permit", comment="A permit.")])
        matrix = _make_matrix([
            _make_mapping("src:Permit", "extend", base_type="nc:ActivityType"),
        ])
        model = _build(matrix, inv)

        assert len(model.classes) == 1
        cls = model.classes[0]
        assert cls.name == "PermitType"
        assert cls.class_id == "ext.PermitType"
        assert cls.sub_class_of == "nc.ActivityType"
        assert cls.namespace_ref == "ext"

    def test_augment_creates_no_class(self):
        inv = _make_inventory(classes=[_make_class("src:Geo")])
        matrix = _make_matrix([
            _make_mapping("src:Geo", "augment", "nc:LocationType",
                          augments_type="nc:LocationType"),
        ])
        model = _build(matrix, inv)

        assert len(model.classes) == 0

    def test_exclude_creates_no_class(self):
        inv = _make_inventory(classes=[_make_class("src:Old")])
        matrix = _make_matrix([_make_mapping("src:Old", "exclude")])
        model = _build(matrix, inv)

        assert len(model.classes) == 0

    def test_class_names_end_in_type(self):
        inv = _make_inventory(classes=[
            _make_class("src:Foo"),
            _make_class("src:Bar"),
        ])
        matrix = _make_matrix([
            _make_mapping("src:Foo", "reuse", "nc:FooType"),
            _make_mapping("src:Bar", "extend", base_type="nc:BarType"),
        ])
        model = _build(matrix, inv)

        for cls in model.classes:
            assert cls.name.endswith("Type"), f"Class name should end in Type: {cls.name}"

    def test_class_ids_follow_prefix_dot_name(self):
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        for cls in model.classes:
            assert "." in cls.class_id, f"Class id should contain dot: {cls.class_id}"
            prefix, name = cls.class_id.split(".", 1)
            assert prefix, "Prefix should not be empty"
            assert name, "Name should not be empty"


# ---------------------------------------------------------------------------
# Tests: Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_object_property_created(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            obj_props=[_make_obj_prop("src:hasPart", domain=["src:Foo"],
                                     range_list=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        obj_props = [p for p in model.properties if p.is_object]
        assert len(obj_props) == 1
        assert obj_props[0].name == "hasPart"

    def test_datatype_property_created(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:name", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        dt_props = [p for p in model.properties if not p.is_object]
        assert len(dt_props) == 1
        assert dt_props[0].name == "name"
        assert dt_props[0].datatype_ref == "xs.string"

    def test_property_assigned_via_shacl(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:label", domain=[])],  # no explicit domain
            shapes=[_make_shape("src:Foo", [
                _make_shape_prop("src:label", min_count=1, max_count=1),
            ])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        # Property should be assigned to the class via SHACL
        cls = model.classes[0]
        assert len(cls.properties) == 1
        assert cls.properties[0].min_occurs == 1
        assert cls.properties[0].max_occurs == "1"

    def test_reuse_property_uses_target_ref(self):
        """the matrix names the property by QNAME, so the lookup that
        resolves the decision must key on the qname too."""
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:personName", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping(
            "src:Foo", "reuse", "nc:PersonType",
            property_mappings=[_make_prop_mapping(
                "src:personName", action="reuse-property",
                target_prop="nc:PersonName", review="accepted",
            )],
        )])
        model = _build(matrix, inv)

        cls = model.classes[0]
        assert len(cls.properties) == 1
        assert cls.properties[0].property_ref == "nc.PersonName"

    def test_reuse_property_resolves_a_misqualified_matrix_name(self):
        """A matrix written before the Stage-3 qname fix names an
        augmenting-namespace property under the source prefix."""
        inv = _make_inventory(
            classes=[_make_class("src:Fee")],
            dt_props=[_make_dt_prop("fin:fiscalYearCode", domain=["src:Fee"])],
        )
        matrix = _make_matrix([_make_mapping(
            "src:Fee", "reuse", "nc:ObligationType",
            property_mappings=[_make_prop_mapping(
                "src:fiscalYearCode", action="reuse-property",
                target_prop="nc:FiscalYearDate", review="accepted",
            )],
        )])
        cls = _build(matrix, inv).classes[0]
        assert [p.property_ref for p in cls.properties] == ["nc.FiscalYearDate"]

    def test_unaccepted_reuse_property_is_still_declared(self):
        """Only an ACCEPTED decision defers to the target."""
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:personName", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping(
            "src:Foo", "reuse", "nc:PersonType",
            property_mappings=[_make_prop_mapping(
                "src:personName", action="reuse-property",
                target_prop="nc:PersonName", review="pending-review",
            )],
        )])
        cls = _build(matrix, inv).classes[0]
        assert [p.property_ref for p in cls.properties] != ["nc.PersonName"]

    def test_cardinality_from_shacl(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:code", domain=["src:Foo"])],
            shapes=[_make_shape("src:Foo", [
                _make_shape_prop("src:code", min_count=1, max_count=5),
            ])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        cls = model.classes[0]
        assert cls.properties[0].min_occurs == 1
        assert cls.properties[0].max_occurs == "5"

    def test_default_cardinality_without_shacl(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:note", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        cls = model.classes[0]
        assert cls.properties[0].min_occurs == 0
        assert cls.properties[0].max_occurs == "unbounded"

    def test_all_properties_have_name_and_namespace(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            obj_props=[_make_obj_prop("src:ref", domain=["src:Foo"])],
            dt_props=[_make_dt_prop("src:val", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        for p in model.properties:
            assert p.name, f"Property name is empty: {p.prop_id}"
            assert p.namespace_ref, f"Property namespace_ref is empty: {p.prop_id}"

    def test_property_ids_follow_prefix_dot_name(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:val", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        for p in model.properties:
            assert "." in p.prop_id, f"Property id should contain dot: {p.prop_id}"


# ---------------------------------------------------------------------------
# Tests: Augmentations
# ---------------------------------------------------------------------------

class TestAugmentations:
    def test_new_property_on_reuse_creates_augmentation(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:extra", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        edge_ns = [n for n in model.namespaces if n.ns_id == "test-edge"][0]
        assert len(edge_ns.augmentations) >= 1
        aug = edge_ns.augmentations[0]
        assert aug.class_ref == "nc.FooType"
        assert "extra" in aug.property_ref

    # -- the augment branch ------------------------------------------
    @staticmethod
    def _augment_model(shapes=None, obj=False):
        prop = _make_obj_prop("src:extra", domain=["src:Foo"], range_list=["src:Bar"]) if obj \
            else _make_dt_prop("src:extra", domain=["src:Foo"])
        inv = _make_inventory(
            classes=[_make_class("src:Foo"), _make_class("src:Bar")],
            obj_props=[prop] if obj else [],
            dt_props=[] if obj else [prop],
            shapes=shapes or [],
        )
        matrix = _make_matrix([_make_mapping(
            "src:Foo", "augment", "nc:PersonType", augments_type="nc:PersonType",
            property_mappings=[_make_prop_mapping("src:extra", action="create-property")],
        )])
        return _build(matrix, inv)

    def test_augment_created_property_is_declared_not_just_referenced(self):
        """An augment class has no CmfClass, so its created properties were
        referenced by every record and declared by none."""
        model = self._augment_model()
        declared = {p.prop_id for p in model.properties}
        records = [a for ns in model.namespaces for a in ns.augmentations]
        assert records, "fixture must produce an augmentation record"
        assert all(a.property_ref in declared for a in records), (
            f"dangling: {[a.property_ref for a in records if a.property_ref not in declared]}")

    def test_augment_record_uses_the_extension_prefix(self):
        """The declaration side puts a non-reuse property in EXT; the record
        must name the same id, not an EDGE-prefixed one."""
        model = self._augment_model()
        [record] = [a for ns in model.namespaces for a in ns.augmentations]
        assert record.property_ref.startswith("ext.")

    def test_augment_record_carries_the_asserted_occurrence(self):
        """Not a hardcoded 0..unbounded."""
        shapes = [_make_shape("src:Foo", [_make_shape_prop("src:extra", min_count=1, max_count=1)])]
        [record] = [a for ns in self._augment_model(shapes).namespaces for a in ns.augmentations]
        assert (record.min_occurs, record.max_occurs) == (1, "1")

    def test_augment_record_is_object_reflects_the_property_kind(self):
        """Not a hardcoded True."""
        [dt] = [a for ns in self._augment_model().namespaces for a in ns.augmentations]
        assert dt.is_object is False
        [obj] = [a for ns in self._augment_model(obj=True).namespaces for a in ns.augmentations]
        assert obj.is_object is True

    def test_augment_reuse_property_keeps_target_reference_without_redeclaration(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:existingProp", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping(
            "src:Foo", "augment", "nc:PersonType", augments_type="nc:PersonType",
            property_mappings=[_make_prop_mapping(
                "src:existingProp", action="reuse-property",
                target_prop="nc:PersonName", review="accepted")],
        )])
        model = _build(matrix, inv)
        assert [a.property_ref for ns in model.namespaces for a in ns.augmentations] == ["nc.PersonName"]
        assert not any("existingProp" in p.prop_id for p in model.properties)

    def test_augment_borrowed_property_preserves_bounds_and_namespace(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:flag", domain=["src:Foo"])],
            shapes=[_make_shape("src:Foo", [_make_shape_prop("src:flag", 0, 0)])],
        )
        matrix = _make_matrix([_make_mapping(
            "src:Foo", "augment", "nc:BaseType", property_mappings=[
                _make_prop_mapping("src:flag", "reuse-property", "other:FlagText")])])
        model = _build(matrix, inv, target_ns_map={"nc": "https://example.org/nc/", "other": "https://example.org/other/"})
        [record] = [a for ns in model.namespaces for a in ns.augmentations]
        assert (record.class_ref, record.property_ref, record.is_object, record.min_occurs, record.max_occurs) == (
            "nc.BaseType", "other.FlagText", False, 0, "0")
        assert not model.properties
        assert any(n.ns_id == "other" and n.uri == "https://example.org/other/" for n in model.namespaces)

    def test_reuse_property_no_augmentation(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:existingProp", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping(
            "src:Foo", "reuse", "nc:FooType",
            property_mappings=[_make_prop_mapping(
                "src:existingProp", action="reuse-property",
                target_prop="nc:ExistingProp", review="accepted",
            )],
        )])
        model = _build(matrix, inv)

        edge_ns = [n for n in model.namespaces if n.ns_id == "test-edge"][0]
        # Reuse-property should NOT create an augmentation
        aug_for_existing = [a for a in edge_ns.augmentations
                           if "ExistingProp" in a.property_ref or "existingProp" in a.property_ref]
        assert len(aug_for_existing) == 0

    def test_augmentation_on_augmenting_namespace(self):
        """Spec: AugmentationRecord lives on the augmenting namespace."""
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            dt_props=[_make_dt_prop("src:newField", domain=["src:Foo"])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        # Augmentations should be on the edge namespace, not on target
        edge_ns = [n for n in model.namespaces if n.ns_id == "test-edge"][0]
        nc_ns = [n for n in model.namespaces if n.ns_id == "nc"]
        assert len(edge_ns.augmentations) >= 1
        if nc_ns:
            assert len(nc_ns[0].augmentations) == 0


# ---------------------------------------------------------------------------
# Tests: Codelists
# ---------------------------------------------------------------------------

class TestCodelists:
    def test_codelist_creates_restriction(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            codelists=[_make_codelist("http://ex.org/StatusScheme", [
                _make_concept("http://ex.org/Active", "Active"),
                _make_concept("http://ex.org/Inactive", "Inactive"),
            ])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        assert len(model.restrictions) == 1
        r = model.restrictions[0]
        assert r.name == "StatusScheme"
        assert r.restriction_base == "xs.token"
        assert len(r.facets) == 2

    def test_codelist_facets_are_enumerations(self):
        inv = _make_inventory(
            classes=[_make_class("src:Foo")],
            codelists=[_make_codelist("http://ex.org/Colors", [
                _make_concept("http://ex.org/Red", "Red"),
                _make_concept("http://ex.org/Blue", "Blue"),
            ])],
        )
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        for facet in model.restrictions[0].facets:
            assert facet.category == "enumeration"

    def test_consolidated_subtypes_create_restriction(self):
        inv = _make_inventory(classes=[
            _make_class("src:Parent"),
            _make_class("src:ChildA", sub_class_of=["src:Parent"]),
            _make_class("src:ChildB", sub_class_of=["src:Parent"]),
        ])
        matrix = _make_matrix([
            _make_mapping("src:Parent", "reuse", "nc:ParentType"),
            _make_mapping("src:ChildA", "exclude"),
            _make_mapping("src:ChildB", "exclude"),
        ])
        model = _build(matrix, inv)

        # Should have a synthetic role scheme
        role_restrictions = [r for r in model.restrictions if "RoleScheme" in r.name]
        assert len(role_restrictions) == 1
        assert len(role_restrictions[0].facets) == 2


# ---------------------------------------------------------------------------
# Tests: Spec compliance
# ---------------------------------------------------------------------------

class TestSpecCompliance:
    def test_all_classes_have_required_fields(self):
        inv = _make_inventory(classes=[
            _make_class("src:A"),
            _make_class("src:B"),
        ])
        matrix = _make_matrix([
            _make_mapping("src:A", "reuse", "nc:AType"),
            _make_mapping("src:B", "extend", base_type="nc:BType"),
        ])
        model = _build(matrix, inv)

        for cls in model.classes:
            assert cls.name, f"Class missing Name: {cls.class_id}"
            assert cls.namespace_ref, f"Class missing Namespace: {cls.class_id}"
            assert cls.class_id, "Class missing id"

    def test_all_namespaces_have_required_fields(self):
        inv = _make_inventory(classes=[_make_class("src:Foo")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        model = _build(matrix, inv)

        for ns in model.namespaces:
            assert ns.uri, f"Namespace missing URI: {ns.ns_id}"
            assert ns.prefix, f"Namespace missing prefix: {ns.ns_id}"
            assert ns.category, f"Namespace missing category: {ns.ns_id}"

    def test_xml_serialization_roundtrip(self):
        """Build → serialize XML → parse back → compare counts."""
        set_niem_version("6.0")

        inv = _make_inventory(
            classes=[_make_class("src:Permit", comment="A building permit.")],
            dt_props=[_make_dt_prop("src:permitNumber", label="Permit Number",
                                   domain=["src:Permit"])],
            codelists=[_make_codelist("http://ex.org/StatusScheme", [
                _make_concept("http://ex.org/Active", "Active"),
            ])],
        )
        matrix = _make_matrix([_make_mapping("src:Permit", "reuse", "nc:PermitType")])
        model = _build(matrix, inv)

        # Serialize to XML
        xml_str = CmfXmlSerializer(model).serialize()
        assert xml_str  # non-empty

        # Parse back
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".cmf", delete=False, mode="w",
                                          encoding="utf-8") as f:
            f.write(xml_str)
            cmf_path = f.name

        try:
            parsed = CmfXmlParser().parse(Path(cmf_path))
            assert len(parsed.namespaces) == len(model.namespaces)
            assert len(parsed.classes) == len(model.classes)
            assert len(parsed.properties) == len(model.properties)
            assert len(parsed.restrictions) == len(model.restrictions)
        finally:
            import os
            os.unlink(cmf_path)

    def test_mixed_actions_full_model(self):
        """Integration test: reuse + extend + augment + exclude + properties + codelists."""
        inv = _make_inventory(
            classes=[
                _make_class("src:Address", comment="A postal address."),
                _make_class("src:Permit", comment="A building permit."),
                _make_class("src:Geo", comment="Geographic data."),
                _make_class("src:Old", comment="Deprecated.", sub_class_of=["src:Address"]),
                _make_class("src:OldB", comment="Also deprecated.", sub_class_of=["src:Address"]),
            ],
            obj_props=[
                _make_obj_prop("src:hasAddress", domain=["src:Permit"],
                               range_list=["src:Address"]),
            ],
            dt_props=[
                _make_dt_prop("src:streetName", domain=["src:Address"]),
                _make_dt_prop("src:permitId", domain=["src:Permit"]),
            ],
            codelists=[_make_codelist("http://ex.org/PermitStatus", [
                _make_concept("http://ex.org/Active", "Active"),
                _make_concept("http://ex.org/Expired", "Expired"),
            ])],
        )
        matrix = _make_matrix([
            _make_mapping("src:Address", "reuse", "nc:AddressType"),
            _make_mapping("src:Permit", "extend", base_type="nc:ActivityType"),
            _make_mapping("src:Geo", "augment", "nc:LocationType",
                          augments_type="nc:LocationType"),
            _make_mapping("src:Old", "exclude"),
            _make_mapping("src:OldB", "exclude"),
        ])
        model = _build(matrix, inv)

        # 2 classes: Address (reuse) + Permit (extend)
        assert len(model.classes) == 2

        # Namespaces: edge, ext (for extend), nc (target)
        ns_ids = {n.ns_id for n in model.namespaces}
        assert "test-edge" in ns_ids
        assert "ext" in ns_ids
        assert "nc" in ns_ids

        # Properties exist
        assert len(model.properties) >= 2

        # Codelist + consolidated role scheme
        assert len(model.restrictions) >= 2  # PermitStatus + AddressRoleScheme

        # Object property range should resolve
        has_addr = [p for p in model.properties if p.name == "hasAddress"]
        assert len(has_addr) == 1
        assert has_addr[0].class_ref == "nc.AddressType"  # reuse target


# ---------------------------------------------------------------------------
# Tests: CMF community reference conformance
# ---------------------------------------------------------------------------

class TestCmfReferenceConformance:
    """Validate our parser and serializer against community CMF 1.0 files.

    Uses model.cmf from the niemopen/common-model-format repo — the CMF spec
    describing itself as a CMF document (CMF 1.0 namespace).

    Note: CrashDriver.cmf.xml uses the old CMF 0.5 namespace
    (http://reference.niem.gov/specification/cmf/0.5/) and is kept for
    future reference but is not tested here — our parser targets CMF 1.0.
    """

    FIXTURE = Path(__file__).parent / "fixtures" / "cmf_reference" / "model.cmf"

    @pytest.fixture(autouse=True)
    def _set_version(self):
        set_niem_version("6.0")

    def test_fixture_exists(self):
        assert self.FIXTURE.exists(), "model.cmf fixture missing"

    def test_parse_namespace_count(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        assert len(model.namespaces) == 4

    def test_parse_namespace_prefixes(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        prefixes = {ns.prefix for ns in model.namespaces}
        assert prefixes == {"cmf", "nc", "xml", "xs"}

    def test_parse_namespace_categories(self):
        """Every namespace in the reference file has a valid category code."""
        valid = {"BUILTIN", "CLI", "CORE", "DOMAIN", "EXTENSION",
                 "EXTERNAL", "OTHERNIEM", "UNKNOWN", "XML", "XSD"}
        model = CmfXmlParser().parse(self.FIXTURE)
        for ns in model.namespaces:
            assert ns.category in valid, f"Invalid category {ns.category} on {ns.ns_id}"

    def test_parse_class_count(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        assert len(model.classes) == 19

    def test_parse_property_count(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        assert len(model.properties) == 58

    def test_parse_restriction_count(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        assert len(model.restrictions) == 6

    def test_class_ids_use_prefix_dot_name(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        for cls in model.classes:
            assert "." in cls.class_id, f"Class id missing dot: {cls.class_id}"
            prefix, name = cls.class_id.split(".", 1)
            assert prefix and name

    def test_class_type_inherits_component_type(self):
        """ClassType extends ComponentType — a known structural fact."""
        model = CmfXmlParser().parse(self.FIXTURE)
        cls = next(c for c in model.classes if c.name == "ClassType")
        assert cls.sub_class_of == "cmf.ComponentType"

    def test_namespace_type_has_required_properties(self):
        """NamespaceType must have URI, prefix, and category properties."""
        model = CmfXmlParser().parse(self.FIXTURE)
        ns_cls = next(c for c in model.classes if c.name == "NamespaceType")
        prop_refs = {p.property_ref for p in ns_cls.properties}
        assert "cmf.NamespaceURI" in prop_refs
        assert "cmf.NamespacePrefixText" in prop_refs
        assert "cmf.NamespaceCategoryCode" in prop_refs

    def test_namespace_category_code_restriction_has_all_values(self):
        """The NamespaceCategoryCodeType restriction enumerates all 10 valid codes."""
        model = CmfXmlParser().parse(self.FIXTURE)
        r = next(r for r in model.restrictions if r.name == "NamespaceCategoryCodeType")
        values = {f.value for f in r.facets}
        expected = {"BUILTIN", "CLI", "CORE", "DOMAIN", "EXTENSION",
                    "EXTERNAL", "OTHERNIEM", "UNKNOWN", "XML", "XSD"}
        assert values == expected

    def test_all_facets_have_category(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        for r in model.restrictions:
            for f in r.facets:
                assert f.category, f"Facet missing category in {r.name}"

    def test_property_ids_use_prefix_dot_name(self):
        model = CmfXmlParser().parse(self.FIXTURE)
        for p in model.properties:
            assert "." in p.prop_id, f"Property id missing dot: {p.prop_id}"

    def test_child_property_cardinality_is_set(self):
        """Every ChildPropertyAssociation has min/max occurs set."""
        model = CmfXmlParser().parse(self.FIXTURE)
        for cls in model.classes:
            for hp in cls.properties:
                assert isinstance(hp.min_occurs, int), (
                    f"min_occurs not int on {cls.class_id}/{hp.property_ref}")
                assert hp.max_occurs, (
                    f"max_occurs empty on {cls.class_id}/{hp.property_ref}")

    def test_serialize_roundtrip_preserves_counts(self):
        """Parse reference → serialize → parse again → same entity counts."""
        original = CmfXmlParser().parse(self.FIXTURE)

        xml_str = CmfXmlSerializer(original).serialize()
        assert xml_str

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".cmf", delete=False,
                                          mode="w", encoding="utf-8") as f:
            f.write(xml_str)
            tmp = f.name
        try:
            reparsed = CmfXmlParser().parse(Path(tmp))
            assert len(reparsed.namespaces) == len(original.namespaces)
            assert len(reparsed.classes) == len(original.classes)
            assert len(reparsed.properties) == len(original.properties)
            assert len(reparsed.restrictions) == len(original.restrictions)
        finally:
            os.unlink(tmp)

    def test_builder_output_uses_same_id_format_as_reference(self):
        """MatrixToCmfBuilder output follows the same prefix.Name format as model.cmf."""
        reference = CmfXmlParser().parse(self.FIXTURE)
        ref_class_id = reference.classes[0].class_id  # e.g. "cmf.AnyPropertyAssociationType"
        ref_prefix, ref_name = ref_class_id.split(".", 1)
        assert ref_name[0].isupper()  # Name starts uppercase

        # Build a model and verify same convention
        inv = _make_inventory(classes=[_make_class("src:Foo", comment="Test.")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        built = _build(matrix, inv)

        for cls in built.classes:
            prefix, name = cls.class_id.split(".", 1)
            assert name[0].isupper(), f"Class name should start uppercase: {name}"
            assert name.endswith("Type"), f"Class name should end in Type: {name}"

    def test_builder_categories_match_reference_vocabulary(self):
        """Builder uses only category codes found in the reference spec."""
        reference = CmfXmlParser().parse(self.FIXTURE)
        r = next(r for r in reference.restrictions if r.name == "NamespaceCategoryCodeType")
        valid_codes = {f.value for f in r.facets}

        inv = _make_inventory(classes=[_make_class("src:Foo")])
        matrix = _make_matrix([_make_mapping("src:Foo", "reuse", "nc:FooType")])
        built = _build(matrix, inv)

        for ns in built.namespaces:
            assert ns.category in valid_codes, (
                f"Builder category {ns.category} not in spec: {valid_codes}")


# ---------------------------------------------------------------------------
# Tests: ntac-admin community CMF examples
# ---------------------------------------------------------------------------

# Augmentation examples from niemopen/ntac-admin — small focused models
# demonstrating each augmentation pattern in CMF 1.0.
NTAC_DIR = Path(__file__).parent / "fixtures" / "cmf_reference" / "ntac-admin"

NTAC_FILES = [
    ("02-NoAug.cmf", 3, 3, 6, 1, 0),   # no augmentation baseline
    ("03-CCwE.cmf", 4, 3, 7, 1, 1),     # augment with data property (extension ns)
    ("04-CCwA.cmf", 3, 3, 8, 1, 1),     # augment with data property (same ns)
    ("05-SCwA.cmf", 3, 4, 8, 0, 1),     # augment targeting simple type
    ("06-SCwE.cmf", 3, 5, 9, 0, 1),     # augment with object property
    ("reuseModel.cmf", 5, 3, 7, 0, 0),  # multi-namespace reuse
]


class TestNtacAdminExamples:
    """Validate parser against augmentation/reuse examples from ntac-admin."""

    @pytest.fixture(autouse=True)
    def _set_version(self):
        set_niem_version("6.0")

    @pytest.mark.parametrize("filename,ns,cls,prop,rst,aug", NTAC_FILES,
                             ids=[t[0] for t in NTAC_FILES])
    def test_parse_entity_counts(self, filename, ns, cls, prop, rst, aug):
        model = CmfXmlParser().parse(NTAC_DIR / filename)
        assert len(model.namespaces) == ns, f"namespace count mismatch in {filename}"
        assert len(model.classes) == cls, f"class count mismatch in {filename}"
        assert len(model.properties) == prop, f"property count mismatch in {filename}"
        assert len(model.restrictions) == rst, f"restriction count mismatch in {filename}"
        total_aug = sum(len(n.augmentations) for n in model.namespaces)
        assert total_aug == aug, f"augmentation count mismatch in {filename}"

    @pytest.mark.parametrize("filename", [t[0] for t in NTAC_FILES])
    def test_all_ids_use_prefix_dot_name(self, filename):
        model = CmfXmlParser().parse(NTAC_DIR / filename)
        for cls in model.classes:
            assert "." in cls.class_id, f"{filename}: class id {cls.class_id}"
        for p in model.properties:
            assert "." in p.prop_id, f"{filename}: prop id {p.prop_id}"

    @pytest.mark.parametrize("filename", [t[0] for t in NTAC_FILES])
    def test_namespace_categories_valid(self, filename):
        valid = {"BUILTIN", "CLI", "CORE", "DOMAIN", "EXTENSION",
                 "EXTERNAL", "OTHERNIEM", "UNKNOWN", "XML", "XSD"}
        model = CmfXmlParser().parse(NTAC_DIR / filename)
        for ns in model.namespaces:
            assert ns.category in valid, f"{filename}: invalid category {ns.category}"

    @pytest.mark.parametrize("filename", [t[0] for t in NTAC_FILES])
    def test_serialize_roundtrip(self, filename):
        """Parse → serialize → reparse preserves counts for each community file."""
        original = CmfXmlParser().parse(NTAC_DIR / filename)
        xml_str = CmfXmlSerializer(original).serialize()

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".cmf", delete=False,
                                          mode="w", encoding="utf-8") as f:
            f.write(xml_str)
            tmp = f.name
        try:
            reparsed = CmfXmlParser().parse(Path(tmp))
            assert len(reparsed.namespaces) == len(original.namespaces)
            assert len(reparsed.classes) == len(original.classes)
            assert len(reparsed.properties) == len(original.properties)
        finally:
            os.unlink(tmp)

    def test_augmentation_on_extension_namespace(self):
        """03-CCwE: augmentation record lives on the 'j' extension namespace."""
        model = CmfXmlParser().parse(NTAC_DIR / "03-CCwE.cmf")
        j_ns = next(n for n in model.namespaces if n.prefix == "j")
        assert len(j_ns.augmentations) == 1
        aug = j_ns.augmentations[0]
        assert aug.class_ref == "nc.EducationType"
        assert aug.property_ref == "j.EducationTotalYearsText"
        assert aug.is_object is False

    def test_augmentation_with_object_property(self):
        """06-SCwE: augmentation adds an object property."""
        model = CmfXmlParser().parse(NTAC_DIR / "06-SCwE.cmf")
        augs = []
        for ns in model.namespaces:
            augs.extend(ns.augmentations)
        assert len(augs) == 1
        assert augs[0].is_object is True
        assert augs[0].property_ref == "my.PrivacyAssertion"

    def test_no_augmentation_baseline(self):
        """02-NoAug: zero augmentation records anywhere."""
        model = CmfXmlParser().parse(NTAC_DIR / "02-NoAug.cmf")
        total = sum(len(ns.augmentations) for ns in model.namespaces)
        assert total == 0

    def test_multi_namespace_reuse(self):
        """reuseModel.cmf has 5 namespaces from different sources."""
        model = CmfXmlParser().parse(NTAC_DIR / "reuseModel.cmf")
        prefixes = {ns.prefix for ns in model.namespaces}
        assert len(prefixes) == 5
        # Should include xs (XSD) and at least one CORE/DOMAIN namespace
        assert "xs" in prefixes


class TestAugmentNamespaceAndRecords:
    """Span-9 F6/F8/F9: three defects in the augment path of the CMF model."""

    @staticmethod
    def _dt(qname, label="p"):
        return {"qname": qname, "label": label, "domain": [], "range": []}

    def test_ext_namespace_is_declared_for_an_augment_only_run(self):
        """`_property_prefix` returns EXT for every non-reuse action, so an
        augment class emits properties under `ext` — but `ext` was declared
        only when an EXTEND class existed. A run with augments and no
        extends put properties in a namespace the model never declared."""
        inv = _make_inventory(
            classes=[_make_class("src:Geo")],
            dt_props=[self._dt("src:geoCode")])
        matrix = _make_matrix([
            _make_mapping("src:Geo", "augment", "nc:LocationType",
                          augments_type="nc:LocationType",
                          property_mappings=[_make_prop_mapping("src:geoCode")]),
        ])
        model = _build(matrix, inv)

        declared = {n.ns_id for n in model.namespaces}
        used = {p.namespace_ref for p in model.properties}
        assert used, "expected the augment class to declare a property"
        assert used <= declared, (
            f"properties emitted into undeclared namespaces: {used - declared}")

    def test_a_misqualified_augment_property_is_still_found(self):
        """The matrix names the property with the parent concept's prefix
        (`src:fiscalYearCode`) while the inventory owns it under an
        augmenting namespace (`fin:fiscalYearCode`). Reading the raw name
        failed the inventory lookup and dropped the decision in silence."""
        inv = _make_inventory(
            classes=[_make_class("src:Fee")],
            dt_props=[self._dt("fin:fiscalYearCode")])
        matrix = _make_matrix([
            _make_mapping("src:Fee", "augment", "nc:ObligationType",
                          augments_type="nc:ObligationType",
                          property_mappings=[
                              _make_prop_mapping("src:fiscalYearCode")]),
        ])
        model = _build(matrix, inv)

        names = {p.name for p in model.properties}
        assert "fiscalYearCode" in names, (
            "the augment property was dropped because its recorded qname "
            f"did not match the inventory; got {names}")

    def test_an_ambiguous_name_is_not_guessed(self):
        """Two inventory properties share the local name, so there is no
        single right answer and the decision stays unapplied."""
        inv = _make_inventory(
            classes=[_make_class("src:Fee")],
            dt_props=[self._dt("fin:code"), self._dt("geo:code")])
        matrix = _make_matrix([
            _make_mapping("src:Fee", "augment", "nc:ObligationType",
                          augments_type="nc:ObligationType",
                          property_mappings=[_make_prop_mapping("src:code")]),
        ])
        model = _build(matrix, inv)
        assert [p for p in model.properties if p.name == "code"] == []

    def test_one_augmentation_record_per_class_and_property(self):
        """Two source classes augmenting the same target with the same
        property said it twice. The record means "this property may appear
        on this type"; repeating it adds nothing and miscounts."""
        inv = _make_inventory(
            classes=[_make_class("src:Geo"), _make_class("src:Place")],
            dt_props=[self._dt("src:geoCode")])
        matrix = _make_matrix([
            _make_mapping("src:Geo", "augment", "nc:LocationType",
                          augments_type="nc:LocationType",
                          property_mappings=[_make_prop_mapping("src:geoCode")]),
            _make_mapping("src:Place", "augment", "nc:LocationType",
                          augments_type="nc:LocationType",
                          property_mappings=[_make_prop_mapping("src:geoCode")]),
        ])
        model = _build(matrix, inv)

        records = [a for ns in model.namespaces for a in ns.augmentations]
        pairs = [(a.class_ref, a.property_ref) for a in records]
        assert len(pairs) == len(set(pairs)), f"duplicate records: {pairs}"
        assert len(pairs) == 1

    def test_distinct_properties_still_each_get_a_record(self):
        """The dedupe must not collapse genuinely different records."""
        inv = _make_inventory(
            classes=[_make_class("src:Geo")],
            dt_props=[self._dt("src:geoCode"), self._dt("src:geoName")])
        matrix = _make_matrix([
            _make_mapping("src:Geo", "augment", "nc:LocationType",
                          augments_type="nc:LocationType",
                          property_mappings=[
                              _make_prop_mapping("src:geoCode"),
                              _make_prop_mapping("src:geoName")]),
        ])
        model = _build(matrix, inv)
        records = [a for ns in model.namespaces for a in ns.augmentations]
        assert len({a.property_ref for a in records}) == 2

    def test_source_namespace_uri_is_taken_from_inventory(self):
        inv = _make_inventory(classes=[_make_class("src:Fee")],
                              dt_props=[self._dt("fin:fiscalYearCode")])
        inv["namespaceMap"] = {"https://example.org/finance/": "fin:"}
        matrix = _make_matrix([_make_mapping("src:Fee", "augment", "nc:ObligationType",
            property_mappings=[_make_prop_mapping("fin:fiscalYearCode")])])
        model = _build(matrix, inv)
        namespace = next(n for n in model.namespaces if n.ns_id == "fin")
        assert namespace.uri == "https://example.org/finance/"
        assert model.properties[0].namespace_ref == "fin"

    def test_differing_occurrences_are_preserved_in_either_inventory_order(self):
        inv = _make_inventory(classes=[_make_class("src:Geo"), _make_class("src:Place")],
                              dt_props=[self._dt("src:geoCode")],
                              shapes=[_make_shape("src:Geo", [_make_shape_prop("src:geoCode", 1, 1)])])
        matrix = _make_matrix([_make_mapping(c["qname"], "augment", "nc:LocationType",
            property_mappings=[_make_prop_mapping("src:geoCode")]) for c in inv["classes"]])
        def records():
            return [(a.class_ref, a.property_ref, a.min_occurs, a.max_occurs)
                    for n in _build(matrix, inv).namespaces for a in n.augmentations]
        forward = records()
        inv["classes"].reverse()
        assert records() == forward
        assert {(r[2], r[3]) for r in forward} == {(1, "1"), (0, "unbounded")}


class TestDeclaredPrimaryNamespace:
    """The declared primary namespace, not class sort order, is the source prefix."""

    def test_augmenting_class_sorting_first_keeps_primary_properties_in_edge_namespace(self):
        inv = _make_inventory(
            classes=[_make_class("abc:Thing"), _make_class("dbpi:Fee")],
            dt_props=[_make_dt_prop("dbpi:amount", domain=["dbpi:Fee"]),
                      _make_dt_prop("abc:note", domain=["dbpi:Fee"])])
        inv["primaryNamespace"] = {"prefix": "dbpi", "uri": "https://example.test/dbpi#"}
        inv["namespaceMap"] = {"https://example.test/dbpi#": "dbpi:",
                               "https://example.test/abc#": "abc:"}
        inv["augmentingNamespaces"] = [{"prefix": "abc", "namespace": "https://example.test/abc#",
                                        "propertyCount": 1, "properties": ["abc:note"]}]
        matrix = _make_matrix([_make_mapping("dbpi:Fee", "reuse", "nc:FeeType", property_mappings=[
            _make_prop_mapping("dbpi:amount"), _make_prop_mapping("abc:note")])])

        model = _build(matrix, inv)

        [fee] = [cls for cls in model.classes if cls.name == "FeeType"]
        assert sorted(p.property_ref for p in fee.properties) == ["abc.note", "test-edge.amount"]
        external = {n.ns_id: n.uri for n in model.namespaces if n.category == "EXTERNAL"}
        assert external == {"abc": "https://example.test/abc#",
                            "nc": "http://example.org/niem-core/6.0"}
        assert "dbpi" not in {n.ns_id for n in model.namespaces}

    def test_created_augmenting_namespace_property_on_reuse_class_gets_augmentation_record(self):
        """Every property this model declares for a reuse class augments the target,
        including one emitted under an augmenting source namespace's prefix."""
        inv = _make_inventory(
            classes=[_make_class("dbpi:Fee")],
            dt_props=[_make_dt_prop("dbpi:amount", domain=["dbpi:Fee"]),
                      _make_dt_prop("abc:note", domain=["dbpi:Fee"]),
                      _make_dt_prop("dbpi:paid", domain=["dbpi:Fee"])])
        inv["primaryNamespace"] = {"prefix": "dbpi", "uri": "https://example.test/dbpi#"}
        inv["namespaceMap"] = {"https://example.test/dbpi#": "dbpi:",
                               "https://example.test/abc#": "abc:"}
        matrix = _make_matrix([_make_mapping("dbpi:Fee", "reuse", "nc:FeeType", property_mappings=[
            _make_prop_mapping("dbpi:amount"),
            _make_prop_mapping("abc:note"),
            _make_prop_mapping("dbpi:paid", action="reuse-property", target_prop="nc:AmountValue")])])

        model = _build(matrix, inv)

        records = {(a.class_ref, a.property_ref)
                   for n in model.namespaces for a in n.augmentations}
        assert records == {("nc.FeeType", "test-edge.amount"), ("nc.FeeType", "abc.note")}
        assert not any(r[1] == "nc.AmountValue" for r in records)


class TestFullIriTargets:
    """Accepted full-IRI targets are emitted as CMF ids bound to catalog namespaces."""

    NC = "https://docs.oasis-open.org/niemopen/ns/model/niem-core/6.0/"
    J = "https://docs.oasis-open.org/niemopen/ns/model/domains/justice/6.0/"
    NS = {"nc": NC, "j": J}

    def test_class_base_augmentation_and_property_iris_become_cmf_ids(self):
        inv = _make_inventory(
            classes=[_make_class("src:A"), _make_class("src:B"), _make_class("src:C")],
            dt_props=[_make_dt_prop("src:code", domain=["src:A"]),
                      _make_dt_prop("src:extra", domain=["src:C"])])
        matrix = _make_matrix([
            _make_mapping("src:A", "reuse", self.NC + "PersonType", property_mappings=[
                _make_prop_mapping("src:code", "reuse-property", self.NC + "PersonNameText")]),
            _make_mapping("src:B", "extend", self.NC + "ItemType", base_type=self.NC + "ItemType"),
            _make_mapping("src:C", "augment", self.J + "ChargeType",
                          augments_type=self.J + "ChargeType",
                          property_mappings=[_make_prop_mapping("src:extra")]),
        ])

        model = _build(matrix, inv, target_ns_map=self.NS)

        by_name = {cls.name: cls for cls in model.classes}
        assert by_name["AType"].sub_class_of == "nc.PersonType"
        assert [p.property_ref for p in by_name["AType"].properties] == ["nc.PersonNameText"]
        assert by_name["BType"].sub_class_of == "nc.ItemType"
        external = {n.ns_id: n.uri for n in model.namespaces if n.category == "EXTERNAL"}
        assert external == self.NS
        augmentations = {(a.class_ref, a.property_ref)
                         for ns in model.namespaces for a in getattr(ns, "augmentations", [])}
        assert ("j.ChargeType", "ext.extra") in augmentations

    def test_iri_outside_catalog_namespaces_is_left_for_reference_validation(self):
        inv = _make_inventory(classes=[_make_class("src:A")])
        matrix = _make_matrix([_make_mapping("src:A", "reuse", "https://other.test/model/X")])

        model = _build(matrix, inv, target_ns_map=self.NS)

        [a] = model.classes
        assert a.sub_class_of == "https://other.test/model/X"
        assert [n.ns_id for n in model.namespaces] == ["test-edge"]
