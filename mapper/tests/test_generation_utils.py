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
    property_mapping_index,
    accepted_reuse_target,
    source_prefix,
)


def test_shape_domains_preserve_all_active_named_targets():
    shapes = [
        {"targetClasses": ["src:A", "src:B"], "targetClass": "src:A", "properties": [
            {"path": "src:p", "minCount": 0, "maxCount": 0, "severity": "Info"},
            {"path": None, "pathKind": "expression"},
            {"path": "src:disabled", "deactivated": True}]},
        {"targetClass": "src:C", "deactivated": True, "properties": [{"path": "src:p"}]},
    ]
    assert infer_domains_from_shapes([], shapes) == {"src:p": {"src:A", "src:B"}}


# ---------------------------------------------------------------------------
# property_mapping_index / accepted_reuse_target — M5d
# ---------------------------------------------------------------------------
def _matrix(*property_mappings_by_concept):
    return {"mappings": [{"sourceConcept": concept, "propertyMappings": pms}
                         for concept, pms in property_mappings_by_concept]}


def _pm(source_property, action="reuse-property", target="nc:Target",
        review="accepted"):
    return {"sourceProperty": source_property, "action": action,
            "targetProperty": target, "reviewStatus": review}


def _inventory(*qnames):
    return {"objectProperties": [],
            "datatypeProperties": [{"qname": q} for q in qnames]}


class TestPropertyMappingIndex:
    """The emitters build this index by qname and used to read it by local
    name, so every lookup missed on a real matrix and every accepted
    reuse-property decision was silently dropped."""

    def test_keys_by_qualified_name(self):
        index = property_mapping_index(_matrix(("s:Foo", [_pm("s:bar")])))
        assert set(index) == {("s:Foo", "s:bar")}

    def test_no_inventory_keeps_the_recorded_name(self):
        index = property_mapping_index(_matrix(("s:Foo", [_pm("bar")])))
        assert set(index) == {("s:Foo", "bar")}

    def test_resolves_a_misqualified_name_to_the_inventory_qname(self):
        """The redvale shape: the matrix says `dbpi:fiscalYearCode`, the
        source ontology says `fin:fiscalYearCode`."""
        index = property_mapping_index(
            _matrix(("dbpi:Fee", [_pm("dbpi:fiscalYearCode")])),
            _inventory("fin:fiscalYearCode", "dbpi:amount"))
        assert set(index) == {("dbpi:Fee", "fin:fiscalYearCode")}

    def test_exact_qname_is_never_overridden(self):
        index = property_mapping_index(
            _matrix(("s:Foo", [_pm("gis:code")])),
            _inventory("gis:code", "fin:code"))
        assert set(index) == {("s:Foo", "gis:code")}

    def test_ambiguous_local_name_is_not_guessed(self):
        """Two candidates: the decision stays unapplied rather than being
        attached to the wrong property."""
        index = property_mapping_index(
            _matrix(("s:Foo", [_pm("s:code")])),
            _inventory("gis:code", "fin:code"))
        assert set(index) == {("s:Foo", "s:code")}  # unresolved, not guessed

    def test_bare_name_resolves_when_unique(self):
        index = property_mapping_index(
            _matrix(("s:Foo", [_pm("bar")])), _inventory("s:bar"))
        assert set(index) == {("s:Foo", "s:bar")}

    def test_entries_without_property_mappings_are_skipped(self):
        assert property_mapping_index({"mappings": [{"sourceConcept": "s:Foo"}]}) == {}
        assert property_mapping_index({}) == {}


class TestAcceptedReuseTarget:
    def test_accepted_reuse_returns_the_target(self):
        assert accepted_reuse_target(_pm("s:bar")) == "nc:Target"

    @pytest.mark.parametrize("pm", [
        None,
        _pm("s:bar", action="create-property"),
        _pm("s:bar", review="pending-review"),
        _pm("s:bar", target=None),
        _pm("s:bar", target="[undecided]"),
    ])
    def test_anything_else_is_none(self, pm):
        assert accepted_reuse_target(pm) is None


class TestSourcePrefix:
    def test_from_first_class(self):
        assert source_prefix({"classes": [{"qname": "dbpi:Fee"}]}) == "dbpi"

    def test_empty_inventory(self):
        assert source_prefix({}) == ""
        assert source_prefix({"classes": []}) == ""


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


def test_shape_severity_does_not_change_evaluation():
    from ontology_mapper.generation_utils import shape_property_is_evaluated

    for severity in ("Violation", "Warning", "Info", "https://example.org/#Custom"):
        assert shape_property_is_evaluated({"severity": severity})
        assert not shape_property_is_evaluated({"severity": severity, "deactivated": True})
