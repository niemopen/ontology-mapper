"""Tests for generation_utils — shared pure utility functions."""

import pytest
from ontology_mapper.generation_utils import (
    XSD,
    local_name,
    edge_class_name,
    target_to_qname,
    xsd_qname,
    infer_domains_from_shapes,
    assign_properties_to_classes,
    detect_consolidations,
)


# ---------------------------------------------------------------------------
# XSD constant
# ---------------------------------------------------------------------------
def test_xsd_constant():
    assert XSD == "http://www.w3.org/2001/XMLSchema#"


# ---------------------------------------------------------------------------
# local_name
# ---------------------------------------------------------------------------
class TestLocalName:
    def test_qname(self):
        assert local_name("nc:PersonType") == "PersonType"

    def test_fragment_iri(self):
        assert local_name("http://example.org/ont#Widget") == "Widget"

    def test_slash_iri(self):
        assert local_name("http://example.org/ont/Widget") == "Widget"

    def test_no_separator(self):
        assert local_name("PlainName") == "PlainName"

    def test_colon_in_http_iri(self):
        # http: prefix should NOT be treated as a qname
        assert local_name("http://example.org/Foo") == "Foo"

    def test_multiple_colons(self):
        assert local_name("ns:sub:Part") == "sub:Part"


# ---------------------------------------------------------------------------
# edge_class_name
# ---------------------------------------------------------------------------
class TestEdgeClassName:
    def test_appends_type(self):
        assert edge_class_name("dbpi:Permit") == "PermitType"

    def test_already_has_type_suffix(self):
        # It always appends — caller's job to avoid double-suffix
        assert edge_class_name("dbpi:PermitType") == "PermitTypeType"

    def test_fragment_iri(self):
        assert edge_class_name("http://example.org#Building") == "BuildingType"


# ---------------------------------------------------------------------------
# target_to_qname
# ---------------------------------------------------------------------------
class TestTargetToQname:
    def test_passthrough(self):
        assert target_to_qname("nc:PersonType") == "nc:PersonType"

    def test_iri_passthrough(self):
        assert target_to_qname("http://ex.org/Type") == "http://ex.org/Type"


# ---------------------------------------------------------------------------
# xsd_qname
# ---------------------------------------------------------------------------
class TestXsdQname:
    def test_full_iri(self):
        assert xsd_qname("http://www.w3.org/2001/XMLSchema#string") == "xsd:string"

    def test_xs_shorthand(self):
        assert xsd_qname("xs:integer") == "xsd:integer"

    def test_already_xsd_prefix(self):
        # Non-XSD prefix passes through
        assert xsd_qname("xsd:boolean") == "xsd:boolean"

    def test_none(self):
        assert xsd_qname(None) is None

    def test_non_xsd_iri(self):
        assert xsd_qname("http://example.org/custom") == "http://example.org/custom"


# ---------------------------------------------------------------------------
# infer_domains_from_shapes
# ---------------------------------------------------------------------------
class TestInferDomainsFromShapes:
    def test_basic_inference(self):
        shapes = [
            {
                "targetClass": "dbpi:Permit",
                "properties": [
                    {"path": "dbpi:issuedDate"},
                    {"path": "dbpi:status"},
                ],
            }
        ]
        result = infer_domains_from_shapes([], shapes)
        assert result["dbpi:issuedDate"] == {"dbpi:Permit"}
        assert result["dbpi:status"] == {"dbpi:Permit"}

    def test_multiple_shapes_same_property(self):
        shapes = [
            {"targetClass": "A", "properties": [{"path": "p1"}]},
            {"targetClass": "B", "properties": [{"path": "p1"}]},
        ]
        result = infer_domains_from_shapes([], shapes)
        assert result["p1"] == {"A", "B"}

    def test_empty_shapes(self):
        assert infer_domains_from_shapes([], []) == {}


# ---------------------------------------------------------------------------
# assign_properties_to_classes
# ---------------------------------------------------------------------------
class TestAssignPropertiesToClasses:
    def test_explicit_domain(self):
        props = [{"qname": "p1", "domain": ["ClassA"]}]
        assigned, unassigned = assign_properties_to_classes(
            props, {"ClassA"}, {}
        )
        assert assigned == {"p1": ["ClassA"]}
        assert unassigned == []

    def test_shape_fallback(self):
        props = [{"qname": "p1", "domain": []}]
        shape_domains = {"p1": {"ClassA"}}
        assigned, unassigned = assign_properties_to_classes(
            props, {"ClassA"}, shape_domains
        )
        assert assigned == {"p1": ["ClassA"]}

    def test_unassigned(self):
        props = [{"qname": "p1", "domain": []}]
        assigned, unassigned = assign_properties_to_classes(props, {"ClassA"}, {})
        assert assigned == {}
        assert unassigned == ["p1"]

    def test_domain_not_active(self):
        props = [{"qname": "p1", "domain": ["Inactive"]}]
        assigned, unassigned = assign_properties_to_classes(
            props, {"Active"}, {}
        )
        # Domain exists but class not active — falls through to shape, then unassigned
        assert unassigned == ["p1"]

    def test_empty_inputs(self):
        assigned, unassigned = assign_properties_to_classes([], set(), {})
        assert assigned == {}
        assert unassigned == []


# ---------------------------------------------------------------------------
# detect_consolidations
# ---------------------------------------------------------------------------
class TestDetectConsolidations:
    def _make_matrix(self, mappings):
        return {"mappings": mappings}

    def _make_class_map(self, classes):
        return {c["qname"]: c for c in classes}

    def test_two_excluded_siblings(self):
        matrix = self._make_matrix([
            {"sourceConcept": "ns:Child1", "action": "exclude"},
            {"sourceConcept": "ns:Child2", "action": "exclude"},
            {"sourceConcept": "ns:Parent", "action": "reuse"},
        ])
        classes = self._make_class_map([
            {"qname": "ns:Child1", "subClassOf": ["ns:Parent"]},
            {"qname": "ns:Child2", "subClassOf": ["ns:Parent"]},
            {"qname": "ns:Parent", "subClassOf": []},
        ])
        result = detect_consolidations(matrix, classes)
        assert len(result) == 1
        parent, absorbed, scheme = result[0]
        assert parent == "ns:Parent"
        assert set(absorbed) == {"ns:Child1", "ns:Child2"}
        assert scheme == "ParentRoleScheme"

    def test_single_excluded_no_consolidation(self):
        matrix = self._make_matrix([
            {"sourceConcept": "ns:Child1", "action": "exclude"},
        ])
        classes = self._make_class_map([
            {"qname": "ns:Child1", "subClassOf": ["ns:Parent"]},
        ])
        result = detect_consolidations(matrix, classes)
        assert result == []

    def test_non_excluded_ignored(self):
        matrix = self._make_matrix([
            {"sourceConcept": "ns:A", "action": "reuse"},
            {"sourceConcept": "ns:B", "action": "extend"},
        ])
        result = detect_consolidations(matrix, {})
        assert result == []

    def test_excluded_no_parent(self):
        matrix = self._make_matrix([
            {"sourceConcept": "ns:Orphan", "action": "exclude"},
        ])
        classes = self._make_class_map([
            {"qname": "ns:Orphan", "subClassOf": []},
        ])
        result = detect_consolidations(matrix, classes)
        assert result == []
