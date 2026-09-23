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
    component_iri,
    target_qname,
    range_class_for,
)


class TestRangeClassFor:
    """One redirect for a range on an excluded class, for every emitter."""

    CLASSES = {"src:A": {"subClassOf": ["src:B"]}, "src:B": {"subClassOf": ["src:C"]},
               "src:C": {"subClassOf": []}, "src:Loop": {"subClassOf": ["src:Loop"]}}

    @staticmethod
    def _rows(**actions):
        return {"src:" + name: {"action": action, "reviewStatus": "accepted"}
                for name, action in actions.items()}

    def test_an_emitted_class_is_its_own_range(self):
        assert range_class_for("src:A", self._rows(A="reuse"), self.CLASSES) == "src:A"

    @pytest.mark.parametrize("action", ["reuse", "extend", "augment"])
    def test_an_exclusion_chain_reaches_the_nearest_emitted_ancestor(self, action):
        rows = self._rows(A="exclude", B="exclude", C=action)
        assert range_class_for("src:A", rows, self.CLASSES) == "src:C"

    def test_no_emitted_ancestor_and_cycles_are_none(self):
        assert range_class_for("src:A", self._rows(A="exclude", B="exclude", C="exclude"),
                               self.CLASSES) is None
        assert range_class_for("src:Loop", self._rows(Loop="exclude"), self.CLASSES) is None

    def test_a_pending_class_is_not_emitted(self):
        rows = self._rows(A="exclude")
        rows["src:B"] = {"action": "reuse", "reviewStatus": "pending-review"}
        assert range_class_for("src:A", rows, self.CLASSES) is None


def test_shape_domains_preserve_all_active_named_targets():
    shapes = [
        {"targetClasses": ["src:A", "src:B"], "targetClass": "src:A", "properties": [
            {"path": "src:p", "minCount": 0, "maxCount": 0, "severity": "Info"},
            {"path": None, "pathKind": "expression"},
            {"path": "src:disabled", "deactivated": True}]},
        {"targetClass": "src:C", "deactivated": True, "properties": [{"path": "src:p"}]},
    ]
    assert infer_domains_from_shapes([], shapes) == {"src:p": {"src:A", "src:B"}}


def test_namespace_alias_avoids_other_source_and_target_prefixes():
    from ontology_mapper.generation_utils import source_namespace_bindings

    inv = {"classes": [{"qname": "src:A"}], "namespaceMap": {
        "https://source.org/nc/": "nc:", "https://source.org/other/": "source_nc:"}}
    target = {"nc": "https://target.org/nc/", "source_nc_2": "https://target.org/other/"}
    bindings = source_namespace_bindings(inv, target, "edge:")
    assert bindings["nc"] == ("source_nc_3", "https://source.org/nc/")
    assert bindings["source_nc"] == ("source_nc", "https://source.org/other/")


# ---------------------------------------------------------------------------
# property_mapping_index / accepted_reuse_target
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

    def test_declared_primary_namespace_wins_over_class_sort_order(self):
        inventory = {"primaryNamespace": {"prefix": "dbpi", "uri": "https://example.test/dbpi#"},
                     "classes": [{"qname": "abc:Thing"}, {"qname": "dbpi:Fee"}]}
        assert source_prefix(inventory) == "dbpi"

    def test_declared_prefix_may_carry_its_colon(self):
        inventory = {"primaryNamespace": {"prefix": "dbpi:"}, "classes": [{"qname": "abc:Thing"}]}
        assert source_prefix(inventory) == "dbpi"


class TestTargetQname:
    NS = {"nc": "https://docs.oasis-open.org/niemopen/ns/model/niem-core/6.0/",
          "hash": "https://example.test/model#",
          "urn": "urn:example:model",
          "bare": "https://example.test/bare"}

    def test_component_iri_follows_the_namespace_separator_rule(self):
        assert component_iri(self.NS["nc"], "PersonType") == self.NS["nc"] + "PersonType"
        assert component_iri(self.NS["hash"], "A") == "https://example.test/model#A"
        assert component_iri(self.NS["urn"], "A") == "urn:example:model:A"
        assert component_iri(self.NS["bare"], "A") == "https://example.test/bare/A"

    @pytest.mark.parametrize("prefix", ["nc", "hash", "urn", "bare"])
    def test_full_iri_grounds_to_the_catalog_qname(self, prefix):
        assert target_qname(component_iri(self.NS[prefix], "Thing"), self.NS) == f"{prefix}:Thing"

    def test_qnames_blank_and_unknown_iris_are_unchanged(self):
        assert target_qname("nc:PersonType", self.NS) == "nc:PersonType"
        assert target_qname("", self.NS) == ""
        assert target_qname(None, self.NS) is None
        assert target_qname("https://other.test/X", self.NS) == "https://other.test/X"
        assert target_qname("https://example.test/model#", self.NS) == "https://example.test/model#"

    def test_longest_namespace_match_wins(self):
        namespaces = {"a": "https://x.test/", "ab": "https://x.test/sub/"}
        assert target_qname("https://x.test/sub/T", namespaces) == "ab:T"
        assert target_qname("https://x.test/T", namespaces) == "a:T"


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


def test_created_property_identity_is_shared_across_outputs():
    from ontology_mapper.generation_utils import created_property_qname

    bindings = {"shared": ("src_shared", "https://example.org/source#")}
    assert created_property_qname("src:value", "reuse", "src", bindings, "sample-edge:") == "sample-edge:value"
    for action in ("extend", "augment"):
        assert created_property_qname("src:value", action, "src", bindings, "sample-edge:") == "ext:value"
    assert created_property_qname("shared:value", "extend", "src", bindings, "sample-edge:") == "src_shared:value"

class TestCreatedPropertyIdentityForUndeclaredNamespaces:
    """Extraction leaves a property whose namespace the manifest does not name
    as a full IRI; it has no prefix to split and no binding to emit under."""

    def _bindings(self):
        from ontology_mapper.generation_utils import source_namespace_bindings
        inv = {"namespaceMap": {"https://example.test/dbpi#": "dbpi:"},
               "augmentingNamespaces": [],
               "primaryNamespace": {"prefix": "dbpi", "uri": "https://example.test/dbpi#"},
               "classes": [{"qname": "dbpi:Fee"}]}
        return source_namespace_bindings(inv, {"nc": "http://niem/core/"}, "edge:")

    @pytest.mark.parametrize("iri", [
        "https://other.test/ns/value", "http://other.test/ns#value", "urn:other:ns:value"])
    def test_full_iri_property_is_minted_not_split(self, iri):
        from ontology_mapper.generation_utils import created_property_qname
        bindings = self._bindings()
        assert created_property_qname(iri, "extend", "dbpi", bindings, "edge:") == "ext:value"
        assert created_property_qname(iri, "reuse", "dbpi", bindings, "edge:") == "edge:value"

    def test_declared_namespaces_keep_their_emitted_prefix(self):
        from ontology_mapper.generation_utils import created_property_qname
        bindings = self._bindings()
        assert created_property_qname("dbpi:amount", "extend", "dbpi", bindings, "edge:") == "ext:amount"
        assert created_property_qname("dbpi:amount", "reuse", "dbpi", bindings, "edge:") == "edge:amount"


class TestComponentIriRoundTrip:
    """`local_name` is the inverse of `component_iri` for every namespace
    shape that function writes, not only the ones the bundled catalogs use."""

    def test_every_namespace_shape_reads_back_whole(self):
        from ontology_mapper.generation_utils import component_iri, local_name
        for namespace in ("https://example.test/ns/", "https://example.test/ns#",
                          "https://example.test/ns:", "https://example.test/ns",
                          "urn:example:model", "urn:example:model:",
                          "urn:example:model/v1", "urn:example:model/v1/"):
            assert local_name(component_iri(namespace, "Thing")) == "Thing", namespace


class TestCollidingPropertyDecisions:
    """Two rows that resolve to one decision are a matrix defect, not a
    race between row orders."""

    def _inventory(self):
        return {"datatypeProperties": [{"qname": "dbpi:code", "domain": ["dbpi:Fee"]}],
                "objectProperties": []}

    def _matrix(self, rows):
        return {"mappings": [{"sourceConcept": "dbpi:Fee", "propertyMappings": rows}]}

    def test_a_resolved_collision_is_reported_not_silently_dropped(self):
        from ontology_mapper.generation_utils import property_mapping_index
        accepted = {"sourceProperty": "dbpi:code", "action": "reuse-property",
                    "reviewStatus": "accepted", "targetProperty": "nc:CodeText"}
        legacy = {"sourceProperty": "fin:code", "action": "create-property",
                  "reviewStatus": "pending-review"}
        for rows in ([legacy, accepted], [accepted, legacy]):
            with pytest.raises(ValueError, match="resolve to a decision"):
                property_mapping_index(self._matrix(rows), self._inventory())

    def test_a_legacy_name_is_not_resolved_onto_another_class_property(self):
        """The fallback exists for a namespace error on the concept's own
        property; a unique local name on a different class is a different
        property, and renaming a decision onto it invents a mapping."""
        from ontology_mapper.generation_utils import property_mapping_index
        inventory = {"objectProperties": [],
                     "datatypeProperties": [{"qname": "other:widgetId",
                                             "domain": ["other:Widget"]}]}
        index = property_mapping_index(self._matrix([
            {"sourceProperty": "dbpi:widgetId", "action": "create-property",
             "reviewStatus": "accepted"}]), inventory)
        assert set(index) == {("dbpi:Fee", "dbpi:widgetId")}


class TestDuplicateDecisionRows:
    """A duplicated row is one decision: refusing it would stop a run over
    an editing slip that changes nothing."""

    def _matrix(self, rows):
        return {"mappings": [{"sourceConcept": "src:Fee", "propertyMappings": rows}]}

    def _inventory(self):
        return {"objectProperties": [],
                "datatypeProperties": [{"qname": "src:code", "domain": ["src:Fee"]}]}

    def test_two_identical_rows_are_one_decision(self):
        from ontology_mapper.generation_utils import property_mapping_index
        row = {"sourceProperty": "src:code", "action": "reuse-property",
               "reviewStatus": "accepted", "targetProperty": "nc:CodeText"}
        index = property_mapping_index(self._matrix([dict(row), dict(row)]),
                                       self._inventory())
        assert set(index) == {("src:Fee", "src:code")}

    def test_two_rows_that_disagree_are_still_refused(self):
        from ontology_mapper.generation_utils import property_mapping_index
        accepted = {"sourceProperty": "src:code", "action": "reuse-property",
                    "reviewStatus": "accepted", "targetProperty": "nc:CodeText"}
        other = {"sourceProperty": "src:code", "action": "create-property",
                 "reviewStatus": "pending-review"}
        with pytest.raises(ValueError, match="resolve to a decision"):
            property_mapping_index(self._matrix([accepted, other]), self._inventory())


class TestInheritedPropertyOwnership:
    """A child's decision resolves when the child's own shape attaches the
    property — which is how Stage 3/4 writes it. Ownership deliberately does
    NOT union ancestors: `build_class_properties` is non-transitive, so the
    reviewer's per-class list never offers a property only an ancestor
    declares, and unioning them re-admits the transplant the rule blocks.
    """

    def _inventory(self, shape_target):
        return {
            "classes": [
                {"qname": "src:Parent", "subClassOf": []},
                {"qname": "src:Kid", "subClassOf": ["src:Parent"]},
            ],
            "objectProperties": [],
            "datatypeProperties": [{"qname": "aug:code", "domain": ["src:Parent"]}],
            "shaclShapes": [{"targetClasses": [shape_target],
                             "properties": [{"path": "aug:code"}]}],
        }

    def _matrix(self):
        return {"mappings": [{"sourceConcept": "src:Kid", "propertyMappings": [
            {"sourceProperty": "src:code", "action": "reuse-property",
             "reviewStatus": "accepted", "targetProperty": "nc:PersonFullName"}]}]}

    def test_a_decision_resolves_when_the_concepts_own_shape_attaches_it(self):
        from ontology_mapper.generation_utils import property_mapping_index
        index = property_mapping_index(self._matrix(), self._inventory("src:Kid"))
        assert set(index) == {("src:Kid", "aug:code")}

    def test_an_ancestors_property_is_not_borrowed(self):
        """`gis:code` on the ancestor is a different property from the
        `fin:code` the decision names; renaming onto it would apply an
        accepted decision to a property the reviewer never saw."""
        from ontology_mapper.generation_utils import property_mapping_index
        inventory = {
            "classes": [{"qname": "src:Root", "subClassOf": []},
                        {"qname": "src:Fee", "subClassOf": ["src:Root"]}],
            "objectProperties": [],
            "datatypeProperties": [{"qname": "gis:code", "domain": ["src:Root"]}],
            "shaclShapes": [],
        }
        matrix = {"mappings": [{"sourceConcept": "src:Fee", "propertyMappings": [
            {"sourceProperty": "fin:code", "action": "reuse-property",
             "reviewStatus": "accepted", "targetProperty": "nc:CodeText"}]}]}
        assert set(property_mapping_index(matrix, inventory)) == {("src:Fee", "fin:code")}
