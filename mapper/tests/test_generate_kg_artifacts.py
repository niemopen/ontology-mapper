#!/usr/bin/env python3
"""Tests for generate_kg_artifacts.py"""

import json
import pytest
from ontology_mapper.generation_utils import graph_labels, graph_property_keys
from ontology_mapper.generate_kg_artifacts import relationship_type
from pathlib import Path
from ontology_mapper.pipeline_context import PipelineContext
from ontology_mapper.generate_kg_artifacts import (
    local_name,
    relationship_type,
    xsd_to_cypher_type,
    build_active_classes,
    build_relationships,
    generate_schema_cypher,
    generate_query_templates,
    generate_sparql_templates,
    generate_internal_to_edge_transform,
    generate_loader_config,
    _kebab,
)


def _make_ctx(source="dbpi", organization="redvale"):
    return PipelineContext.from_inputs(
        {"organization": organization, "source": source,
         "target_ontology": "niem", "target_version": "6.0"},
        run_dir=Path("/tmp/run"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def make_inv(classes, obj_props=None, dt_props=None, shapes=None):
    return {
        "classes": classes,
        "objectProperties": obj_props or [],
        "datatypeProperties": dt_props or [],
        "shaclShapes": shapes or [],
        "codelistSchemes": [],
        "augmentingNamespaces": [],
    }


def make_class(qname, comment=""):
    name = qname.split(":")[-1] if ":" in qname else qname
    return {
        "iri": f"https://example.org/{name}",
        "qname": qname,
        "label": name,
        "comment": comment,
        "subClassOf": [],
    }


def make_obj_prop(qname, domain=None, range_val=None):
    name = qname.split(":")[-1] if ":" in qname else qname
    return {
        "iri": f"https://example.org/{name}",
        "qname": qname,
        "label": name,
        "comment": "",
        "domain": domain or [],
        "range": range_val or [],
    }


def make_dt_prop(qname, domain=None, range_val=None):
    name = qname.split(":")[-1] if ":" in qname else qname
    return {
        "iri": f"https://example.org/{name}",
        "qname": qname,
        "label": name,
        "comment": "",
        "domain": domain or [],
        "range": range_val or [
            "http://www.w3.org/2001/XMLSchema#string"
        ],
    }


def make_matrix(mappings):
    return {"mappings": mappings}


def make_mapping(concept, action, target_type=None):
    return {
        "sourceConcept": concept,
        "action": action,
        "targetType": target_type,
        "matchType": None,
        "reviewStatus": "accepted",
        "ruleId": "test",
        "notes": None,
        "rationale": "Semantic match by orchestrator.",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Pure Helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestLocalName:
    def test_qname(self):
        assert local_name("dbpi:Permit") == "Permit"

    def test_iri_hash(self):
        assert local_name("https://example.org/ontology#Permit") == "Permit"

    def test_iri_slash(self):
        assert local_name("https://example.org/ontology/Permit") == "Permit"


class TestGraphLabels:
    def test_a_primary_term_keeps_its_local_name(self):
        assert graph_labels(["dbpi:PermitApplication", "dbpi:Address"], "dbpi") == {
            "dbpi:PermitApplication": "PermitApplication", "dbpi:Address": "Address"}

    def test_a_term_of_another_namespace_is_always_qualified(self):
        """Decided by the term's namespace, not by what else is present."""
        assert graph_labels(["src:Other", "aug:Thing"], "src") == {
            "src:Other": "Other", "aug:Thing": "aug_Thing"}

    def test_a_label_does_not_change_when_a_later_package_adds_a_namesake(self):
        """Round twelve (open lens): adding aug:Thing renamed src:Thing from
        Thing to src_Thing, so data loaded under the earlier package's
        label stopped matching the new schema."""
        before = graph_labels(["src:Thing", "src:Other"], "src")
        after = graph_labels(["src:Thing", "src:Other", "aug:Thing", "http://x.org/y#Thing"], "src")
        assert after["src:Thing"] == before["src:Thing"] == "Thing"
        assert after["src:Other"] == before["src:Other"]

    def test_names_that_still_meet_after_cleanup_are_suffixed(self):
        cases = [
            ["http://a.org/x#Thing", "http://b.org/y#Thing"],
            ["a-b:Thing", "a_b:Thing"],
            ["src:aug_Thing", "aug:Thing"],
        ]
        for qnames in cases:
            labels = graph_labels(qnames, "src")
            assert len(set(labels.values())) == len(qnames), labels

    def test_every_label_is_a_cypher_identifier(self):
        """A plain local name was written as is: `Thing-Type` is not an
        unquoted Cypher label, and Check 8 reads labels as \\w+."""
        import re
        labels = graph_labels(["src:Thing-Type", "src:9Lives", "src:Ok"], "src")
        assert labels == {"src:Thing-Type": "Thing_Type", "src:9Lives": "_9Lives", "src:Ok": "Ok"}
        assert all(re.fullmatch(r"[A-Za-z_]\w*", l) for l in labels.values())

    def test_labels_do_not_depend_on_input_order(self):
        qnames = ["src:Thing", "aug:Thing", "src:aug_Thing", "a-b:X", "a_b:X"]
        assert graph_labels(qnames, "src") == graph_labels(list(reversed(qnames)), "src")


class TestGraphNameStability:
    """Round thirteen: a collision suffix was a counter in sorted order, so a
    later package's term renamed an existing label (src:aug_Thing became
    aug_Thing_2 when aug:Thing arrived) and the old label named a
    different class."""

    def test_a_later_namesake_does_not_rename_a_primary_term(self):
        before = graph_labels(["src:aug_Thing"], "src")
        after = graph_labels(["src:aug_Thing", "aug:Thing"], "src")
        assert after["src:aug_Thing"] == before["src:aug_Thing"] == "aug_Thing"
        assert after["aug:Thing"] != "aug_Thing"

    def test_a_suffix_does_not_depend_on_the_other_terms(self):
        one = graph_labels(["src:aug_Thing", "aug:Thing"], "src")["aug:Thing"]
        two = graph_labels(["src:aug_Thing", "aug:Thing", "a-b:X", "a_b:X", "src:Z"], "src")["aug:Thing"]
        assert one == two

    def test_full_iris_of_two_namespaces_never_meet(self):
        before = graph_labels(["http://b.org/x#Thing"], "src")
        after = graph_labels(["http://b.org/x#Thing", "http://a.org/y#Thing"], "src")
        assert after["http://b.org/x#Thing"] == before["http://b.org/x#Thing"]
        assert len(set(after.values())) == 2


class TestGraphPropertyNames:
    def test_properties_sharing_a_local_name_stay_distinct(self):
        """Round twelve: src:subject and aug:subject became one relationship
        type SUBJECT, and src:name / aug:name one node key `name`."""
        from ontology_mapper.generation_utils import graph_property_names
        inv = {"primaryNamespace": {"prefix": "src"},
               "objectProperties": [{"qname": "src:subject"}, {"qname": "aug:subject"}],
               "datatypeProperties": [{"qname": "src:name"}, {"qname": "aug:name"}]}
        names = graph_property_names(inv)
        assert names == {"src:subject": "subject", "aug:subject": "aug_subject",
                         "src:name": "name", "aug:name": "aug_name"}
        assert relationship_type(names["aug:subject"]) == "AUG_SUBJECT"

    def test_relationship_types_are_distinct(self):
        """Round thirteen: upper-casing made hasPart/has_part, partOf/PartOf
        and aug:subject/src:augSubject one relationship type, and
        build_relationships kept one of each pair."""
        from ontology_mapper.generation_utils import graph_property_names
        qnames = ["src:hasPart", "src:has_part", "src:partOf", "src:PartOf",
                  "aug:subject", "src:augSubject"]
        inv = {"primaryNamespace": {"prefix": "src"},
               "objectProperties": [{"qname": q} for q in qnames], "datatypeProperties": []}
        names = graph_property_names(inv)
        assert len({relationship_type(names[q]) for q in qnames}) == len(qnames)
        assert names["src:hasPart"] == "hasPart" and names["src:augSubject"] == "augSubject"

    def test_node_keys_differing_in_case_stay_as_they_are(self):
        """Node keys are case-sensitive; only relationship types fold."""
        from ontology_mapper.generation_utils import graph_property_names
        inv = {"primaryNamespace": {"prefix": "src"}, "objectProperties": [],
               "datatypeProperties": [{"qname": "src:partOf"}, {"qname": "src:PartOf"}]}
        assert graph_property_names(inv) == {"src:partOf": "partOf", "src:PartOf": "PartOf"}


class TestShapeOnlyPropertiesInTheGraph:
    """Round thirteen: a property only a shape names reached the OWL, SHACL
    and CMF, and not the graph's node keys, relationships or transforms."""

    def _inv(self):
        inv = make_inv(
            [make_class("src:Case"), make_class("src:Party")],
            shapes=[{"targetClasses": ["src:Case"], "properties": [
                {"path": "src:docketCode", "datatype": "http://www.w3.org/2001/XMLSchema#string"},
                {"path": "src:filedBy", "class": "src:Party"},
                {"path": "rdfs:label"},
            ]}])
        inv["primaryNamespace"] = {"prefix": "src"}
        inv["namespaceMap"] = {"https://example.org/src#": "src"}
        return inv

    def test_shape_only_properties_reach_the_class(self):
        matrix = make_matrix([make_mapping("src:Case", "extend"), make_mapping("src:Party", "extend")])
        case = next(c for c in build_active_classes(self._inv(), matrix) if c["label"] == "Case")
        assert {(p["qname"], p["label"], p["iri"]) for p in case["datatypeProps"]} == {
            ("src:docketCode", "docketCode", "https://example.org/src#docketCode"),
            ("rdfs:label", "rdfs_label", None)}
        assert [(p["qname"], p["rangeLabel"]) for p in case["objectProps"]] == [("src:filedBy", "Party")]
        transform = generate_internal_to_edge_transform(build_active_classes(self._inv(), matrix))
        rule = next(t for t in transform["transforms"] if t["targetLabel"] == "Case")
        assert {m["source"] for m in rule["propertyMappings"]} == {"src:docketCode", "rdfs:label"}
        assert rule["relationMappings"] == [
            {"source": "src:filedBy", "target": "FILED_BY", "targetNodeType": "Party"}]

    def test_a_shape_only_range_that_is_not_emitted_is_no_relationship(self):
        matrix = make_matrix([make_mapping("src:Case", "extend"), make_mapping("src:Party", "exclude")])
        case = build_active_classes(self._inv(), matrix)[0]
        assert case["objectProps"] == []

class TestRelationshipType:
    def test_camel_case(self):
        assert relationship_type("dbpi:submittedBy") == "SUBMITTED_BY"

    def test_multi_word(self):
        assert relationship_type("dbpi:concernsProperty") == "CONCERNS_PROPERTY"

    def test_single_word(self):
        assert relationship_type("dbpi:manages") == "MANAGES"

    def test_has_prefix(self):
        assert relationship_type("dbpi:hasAddress") == "HAS_ADDRESS"


class TestXsdToCypherType:
    def test_string(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#string") == "STRING"

    def test_integer(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#integer") == "INTEGER"

    def test_decimal(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#decimal") == "FLOAT"

    def test_boolean(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#boolean") == "BOOLEAN"

    def test_date(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#date") == "DATE"

    def test_datetime(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#dateTime") == "DATETIME"

    def test_any_uri(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#anyURI") == "STRING"

    def test_none(self):
        assert xsd_to_cypher_type(None) == "STRING"

    def test_unknown(self):
        assert xsd_to_cypher_type("http://www.w3.org/2001/XMLSchema#token") == "STRING"


class TestKebab:
    def test_pascal(self):
        assert _kebab("PermitApplication") == "permit-application"

    def test_simple(self):
        assert _kebab("Address") == "address"


# ═══════════════════════════════════════════════════════════════════════════
# Data Model
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildActiveClasses:
    @pytest.mark.parametrize("chain", [["ex:Minor"], ["ex:Minor", "ex:Middle"]])
    def test_an_excluded_range_names_the_class_the_owl_and_cmf_name(self, chain):
        """A range on an excluded class stands for its nearest emitted
        ancestor in OWL, SHACL and CMF (range_class_for); the graph dropped
        the relationship instead, through any number of exclusions."""
        classes = [make_class("ex:Person"), make_class("ex:Case")]
        parent = "ex:Person"
        for qname in reversed(chain):
            cls = make_class(qname)
            cls["subClassOf"] = [parent]
            classes.append(cls)
            parent = qname
        inv = make_inv(classes, obj_props=[
            make_obj_prop("ex:subject", domain=["ex:Case"], range_val=[chain[0]])])
        matrix = make_matrix([make_mapping("ex:Person", "reuse", "nc:PersonType"),
                              make_mapping("ex:Case", "extend")]
                             + [make_mapping(q, "exclude") for q in chain])
        case = next(c for c in build_active_classes(inv, matrix) if c["sourceQname"] == "ex:Case")
        assert [(p["qname"], p["rangeQname"]) for p in case["objectProps"]] == [("ex:subject", "ex:Person")]

    def test_a_range_with_no_emitted_ancestor_is_still_dropped(self):
        orphan = make_class("ex:Orphan")
        inv = make_inv([make_class("ex:Case"), orphan], obj_props=[
            make_obj_prop("ex:about", domain=["ex:Case"], range_val=["ex:Orphan"])])
        matrix = make_matrix([make_mapping("ex:Case", "extend"), make_mapping("ex:Orphan", "exclude")])
        case = next(c for c in build_active_classes(inv, matrix) if c["sourceQname"] == "ex:Case")
        assert case["objectProps"] == []

    def test_filters_to_reuse_and_extend(self):
        inv = make_inv(
            classes=[
                make_class("ex:Person"),
                make_class("ex:Address"),
                make_class("ex:InternalThing"),
            ],
            dt_props=[
                make_dt_prop("ex:name", domain=["ex:Person"]),
                make_dt_prop("ex:line1", domain=["ex:Address"]),
            ],
        )
        matrix = make_matrix([
            make_mapping("ex:Person", "reuse", "nc:PersonType"),
            make_mapping("ex:Address", "extend"),
            make_mapping("ex:InternalThing", "exclude"),
        ])
        result = build_active_classes(inv, matrix)
        labels = [c["label"] for c in result]
        assert "Person" in labels
        assert "Address" in labels
        assert "InternalThing" not in labels

    def test_datatype_props_assigned(self):
        inv = make_inv(
            classes=[make_class("ex:Person")],
            dt_props=[
                make_dt_prop("ex:givenName", domain=["ex:Person"]),
                make_dt_prop("ex:identifier", domain=["ex:Person"]),
            ],
        )
        matrix = make_matrix([make_mapping("ex:Person", "reuse", "nc:PersonType")])
        result = build_active_classes(inv, matrix)
        assert len(result) == 1
        prop_labels = [p["label"] for p in result[0]["datatypeProps"]]
        assert "givenName" in prop_labels
        assert "identifier" in prop_labels

    def test_object_props_filtered_to_active_ranges(self):
        inv = make_inv(
            classes=[make_class("ex:Permit"), make_class("ex:Internal")],
            obj_props=[
                make_obj_prop("ex:hasInternal", domain=["ex:Permit"], range_val=["ex:Internal"]),
            ],
        )
        matrix = make_matrix([
            make_mapping("ex:Permit", "reuse", "nc:ActivityType"),
            make_mapping("ex:Internal", "exclude"),
        ])
        result = build_active_classes(inv, matrix)
        permit = [c for c in result if c["label"] == "Permit"][0]
        assert len(permit["objectProps"]) == 0  # Internal range filtered out

    def test_object_props_kept_for_active_ranges(self):
        inv = make_inv(
            classes=[make_class("ex:Permit"), make_class("ex:Person")],
            obj_props=[
                make_obj_prop("ex:submittedBy", domain=["ex:Permit"], range_val=["ex:Person"]),
            ],
        )
        matrix = make_matrix([
            make_mapping("ex:Permit", "extend"),
            make_mapping("ex:Person", "reuse", "nc:PersonType"),
        ])
        result = build_active_classes(inv, matrix)
        permit = [c for c in result if c["label"] == "Permit"][0]
        assert len(permit["objectProps"]) == 1
        assert permit["objectProps"][0]["rangeLabel"] == "Person"

    def test_skos_concept_range_filtered(self):
        inv = make_inv(
            classes=[make_class("ex:Permit")],
            obj_props=[
                make_obj_prop("ex:hasStatus", domain=["ex:Permit"],
                              range_val=["http://www.w3.org/2004/02/skos/core#Concept"]),
            ],
        )
        matrix = make_matrix([make_mapping("ex:Permit", "reuse", "nc:ActivityType")])
        result = build_active_classes(inv, matrix)
        permit = result[0]
        assert len(permit["objectProps"]) == 0


class TestBuildRelationships:
    def test_extracts_relationships(self):
        classes = [{
            "sourceQname": "ex:Permit",
            "label": "Permit",
            "comment": "",
            "action": "reuse",
            "targetType": "nc:ActivityType",
            "datatypeProps": [],
            "objectProps": [
                {"qname": "ex:submittedBy", "label": "submittedBy",
                 "rangeQname": "ex:Person", "rangeLabel": "Person"},
            ],
        }]
        rels = build_relationships(classes)
        assert len(rels) == 1
        assert rels[0]["name"] == "SUBMITTED_BY"
        assert rels[0]["sourceLabel"] == "Permit"
        assert rels[0]["targetLabel"] == "Person"

    def test_deduplicates(self):
        classes = [
            {
                "sourceQname": "ex:A", "label": "A", "comment": "",
                "action": "reuse", "targetType": None,
                "datatypeProps": [],
                "objectProps": [
                    {"qname": "ex:links", "label": "links",
                     "rangeQname": "ex:B", "rangeLabel": "B"},
                ],
            },
            {
                "sourceQname": "ex:C", "label": "A", "comment": "",
                "action": "extend", "targetType": None,
                "datatypeProps": [],
                "objectProps": [
                    {"qname": "ex:links", "label": "links",
                     "rangeQname": "ex:B", "rangeLabel": "B"},
                ],
            },
        ]
        rels = build_relationships(classes)
        assert len(rels) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Schema Cypher
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateSchemaCypher:
    def _sample_classes(self):
        return [
            {
                "sourceQname": "ex:Permit", "label": "Permit", "comment": "A permit",
                "action": "reuse", "targetType": "nc:ActivityType",
                "datatypeProps": [
                    {"qname": "ex:identifier", "label": "identifier",
                     "range": "http://www.w3.org/2001/XMLSchema#string"},
                    {"qname": "ex:permitNumber", "label": "permitNumber",
                     "range": "http://www.w3.org/2001/XMLSchema#string"},
                    {"qname": "ex:displayName", "label": "displayName",
                     "range": "http://www.w3.org/2001/XMLSchema#string"},
                ],
                "objectProps": [],
            },
        ]

    def test_contains_constraints(self):
        output = generate_schema_cypher(self._sample_classes(), [], "dbpi")
        assert "CREATE CONSTRAINT Permit_identifier IF NOT EXISTS" in output
        assert "CREATE CONSTRAINT Permit_permitNumber IF NOT EXISTS" in output

    def test_contains_indexes(self):
        output = generate_schema_cypher(self._sample_classes(), [], "dbpi")
        assert "CREATE INDEX Permit_displayName IF NOT EXISTS" in output

    def test_idempotent_if_not_exists(self):
        output = generate_schema_cypher(self._sample_classes(), [], "dbpi")
        # Every CREATE line should have IF NOT EXISTS
        for line in output.split("\n"):
            if line.strip().startswith("CREATE "):
                assert "IF NOT EXISTS" in line

    def test_relationship_comments(self):
        rels = [{"name": "SUBMITTED_BY", "sourceLabel": "Permit",
                 "targetLabel": "Person", "propQname": "ex:submittedBy",
                 "propLabel": "submittedBy"}]
        output = generate_schema_cypher(self._sample_classes(), rels, "dbpi")
        assert "SUBMITTED_BY" in output
        assert "(Permit)" in output or "(:{" not in output  # relationship doc present


# ═══════════════════════════════════════════════════════════════════════════
# Query Templates
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateQueryTemplates:
    def _sample_classes(self, count=4):
        classes = []
        for i in range(count):
            name = f"Entity{i}"
            classes.append({
                "sourceQname": f"ex:{name}", "label": name, "comment": "",
                "action": "reuse", "targetType": None,
                "datatypeProps": [
                    {"qname": f"ex:prop{j}", "label": f"prop{j}",
                     "range": "http://www.w3.org/2001/XMLSchema#string"}
                    for j in range(i + 1)
                ],
                "objectProps": [
                    {"qname": f"ex:rel{j}", "label": f"rel{j}",
                     "rangeQname": f"ex:Entity{j}", "rangeLabel": f"Entity{j}"}
                    for j in range(min(i, 3))
                ],
            })
        return classes

    def test_has_find_by_identifier(self):
        templates = generate_query_templates(self._sample_classes(), [], "dbpi")
        assert "find-by-identifier" in templates
        assert "n.identifier" in templates["find-by-identifier"]

    def test_has_shortest_path(self):
        templates = generate_query_templates(self._sample_classes(), [], "dbpi")
        assert "shortest-path" in templates
        assert "shortestPath" in templates["shortest-path"]

    def test_entity_with_relations(self):
        classes = self._sample_classes()
        templates = generate_query_templates(classes, [], "dbpi")
        # Entity3 has 3 objectProps (>= 2), so should get a with-relations query
        with_rel_keys = [k for k in templates if k.endswith("-with-relations")]
        assert len(with_rel_keys) >= 1

    def test_has_export_subgraph(self):
        templates = generate_query_templates(self._sample_classes(), [], "dbpi")
        assert "export-subgraph" in templates


# ═══════════════════════════════════════════════════════════════════════════
# SPARQL Templates
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateSparqlTemplates:
    def test_has_describe(self):
        templates = generate_sparql_templates(_make_ctx())
        assert "describe-entity" in templates
        assert "DESCRIBE" in templates["describe-entity"]

    def test_has_list_classes(self):
        templates = generate_sparql_templates(_make_ctx())
        assert "list-classes" in templates
        assert "SELECT" in templates["list-classes"]

    def test_has_construct(self):
        templates = generate_sparql_templates(_make_ctx())
        assert "construct-subgraph" in templates
        assert "CONSTRUCT" in templates["construct-subgraph"]

    def test_contains_edge_namespace(self):
        templates = generate_sparql_templates(_make_ctx())
        for name, content in templates.items():
            if "PREFIX edge:" in content:
                assert "redvale.gov/dbpi/edge#" in content
                break


# ═══════════════════════════════════════════════════════════════════════════
# Transform Rules
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateTransformRules:
    def test_basic_transform(self):
        classes = [{
            "sourceQname": "ex:Permit", "label": "Permit", "comment": "",
            "action": "reuse", "targetType": "nc:ActivityType",
            "datatypeProps": [
                {"qname": "ex:identifier", "label": "identifier",
                 "range": "http://www.w3.org/2001/XMLSchema#string"},
            ],
            "objectProps": [],
        }]
        result = generate_internal_to_edge_transform(classes)
        assert len(result["transforms"]) == 1
        assert result["transforms"][0]["sourceType"] == "ex:Permit"
        assert result["transforms"][0]["targetLabel"] == "Permit"

    @pytest.mark.parametrize("name", ["issuedDate", "resultDate"])
    @pytest.mark.parametrize("datatype", [
        "http://www.w3.org/2001/XMLSchema#date",
        "http://www.w3.org/2001/XMLSchema#dateTime", "xsd:date", "xsd:dateTime",
    ])
    def test_date_transform_detected(self, name, datatype):
        classes = [{
            "sourceQname": "ex:Permit", "label": "Permit", "comment": "",
            "action": "reuse", "targetType": None,
            "datatypeProps": [
                {"qname": f"ex:{name}", "label": name, "range": datatype},
            ],
            "objectProps": [],
        }]
        result = generate_internal_to_edge_transform(classes)
        pm = result["transforms"][0]["propertyMappings"]
        assert pm[0]["transform"] == "xsd:date-to-iso8601"

    @pytest.mark.parametrize("name", ["hasApplicationStatus", "TypeDrugMeasurement", "localCode", "resultText"])
    def test_property_name_does_not_establish_a_codelist_conversion(self, name):
        classes = [{
            "sourceQname": "ex:Permit", "label": "Permit", "comment": "",
            "action": "reuse", "targetType": None,
            "datatypeProps": [
                {"qname": f"ex:{name}", "label": name,
                 "range": "http://www.w3.org/2001/XMLSchema#string"},
            ],
            "objectProps": [],
        }]
        result = generate_internal_to_edge_transform(classes)
        pm = result["transforms"][0]["propertyMappings"]
        assert pm[0]["transform"] is None

    def test_relation_mappings(self):
        classes = [{
            "sourceQname": "ex:Permit", "label": "Permit", "comment": "",
            "action": "reuse", "targetType": None,
            "datatypeProps": [],
            "objectProps": [
                {"qname": "ex:submittedBy", "label": "submittedBy",
                 "rangeQname": "ex:Person", "rangeLabel": "Person"},
            ],
        }]
        result = generate_internal_to_edge_transform(classes)
        rm = result["transforms"][0]["relationMappings"]
        assert len(rm) == 1
        assert rm[0]["target"] == "SUBMITTED_BY"
        assert rm[0]["targetNodeType"] == "Person"

    def test_sorted_by_label(self):
        classes = [
            {"sourceQname": "ex:Zebra", "label": "Zebra", "comment": "",
             "action": "extend", "targetType": None,
             "datatypeProps": [], "objectProps": []},
            {"sourceQname": "ex:Alpha", "label": "Alpha", "comment": "",
             "action": "reuse", "targetType": None,
             "datatypeProps": [], "objectProps": []},
        ]
        result = generate_internal_to_edge_transform(classes)
        labels = [t["targetLabel"] for t in result["transforms"]]
        assert labels == ["Alpha", "Zebra"]


# ═══════════════════════════════════════════════════════════════════════════
# Loader Config
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateLoaderConfig:
    def test_structure(self):
        config = generate_loader_config("dbpi")
        assert config["targetPlatform"] == "neo4j"
        assert "loadOrder" in config
        assert "constraints" in config
        assert "sourceDataPaths" in config

    def test_load_order(self):
        config = generate_loader_config("dbpi")
        assert config["loadOrder"] == ["schema.cypher", "seed.cypher"]

    def test_paths(self):
        config = generate_loader_config("dbpi")
        assert config["sourceDataPaths"]["schemaScript"] == "kg/neo4j/schema.cypher"
        assert config["sourceDataPaths"]["seedData"] == "kg/neo4j/seed.cypher"


class TestSeedDataIdentity:
    """Seed instances match the inventory's recorded IRIs, not one namespace."""

    DBPI = "https://example.test/dbpi/"
    ABC = "https://example.test/abc/"

    @staticmethod
    def _with_iri(entry, namespace_uri):
        entry["iri"] = namespace_uri + entry["qname"].split(":")[1]
        return entry

    def _two_namespace_domain(self):
        inv = make_inv(
            [self._with_iri(make_class("abc:Thing"), self.ABC),
             self._with_iri(make_class("dbpi:Fee"), self.DBPI)],
            obj_props=[self._with_iri(
                make_obj_prop("abc:owns", domain=["abc:Thing"], range_val=["dbpi:Fee"]),
                self.ABC)],
            dt_props=[self._with_iri(make_dt_prop("dbpi:feeNumber", domain=["dbpi:Fee"]), self.DBPI),
                      self._with_iri(make_dt_prop("abc:thingId", domain=["abc:Thing"]), self.ABC)],
        )
        inv["primaryNamespace"] = {"prefix": "dbpi", "uri": self.DBPI}
        inv["namespaceMap"] = {self.DBPI: "dbpi:", self.ABC: "abc:"}
        matrix = make_matrix([make_mapping("abc:Thing", "reuse", "nc:ThingType"),
                              make_mapping("dbpi:Fee", "reuse", "nc:FeeType")])
        return inv, matrix

    def _generate(self, inv, matrix, seed_text, tmp_path):
        from ontology_mapper.generate_kg_artifacts import generate_seed_cypher

        active = build_active_classes(inv, matrix)
        seed = tmp_path / "seed.ttl"
        seed.write_text(seed_text, encoding="utf-8")
        return generate_seed_cypher(active, build_relationships(active), seed, "dbpi",
                                    graph_property_keys(inv))

    def test_active_classes_carry_inventory_iris(self):
        inv, matrix = self._two_namespace_domain()
        active = {c["sourceQname"]: c for c in build_active_classes(inv, matrix)}
        assert active["abc:Thing"]["iri"] == self.ABC + "Thing"
        assert active["dbpi:Fee"]["iri"] == self.DBPI + "Fee"
        assert active["abc:Thing"]["objectProps"][0]["iri"] == self.ABC + "owns"

    def test_non_primary_namespace_instances_and_relationships_are_seeded(self, tmp_path):
        inv, matrix = self._two_namespace_domain()
        out = self._generate(inv, matrix, (
            f"@prefix dbpi: <{self.DBPI}> .\n@prefix abc: <{self.ABC}> .\n"
            '<https://data.test/fee1> a dbpi:Fee ; dbpi:feeNumber "F-1" .\n'
            '<https://data.test/thing1> a abc:Thing ; abc:thingId "T-1" ;\n'
            '    abc:owns <https://data.test/fee1> .\n'
        ), tmp_path)

        # abc is not the primary namespace: its class, property key and
        # relationship type are qualified (graph_name). Every node carries
        # the `identifier` its relationships MATCH on.
        assert 'CREATE (:Fee {feeNumber: "F-1", identifier: "F-1"});' in out
        assert 'CREATE (:abc_Thing {abc_thingId: "T-1", identifier: "T-1"});' in out
        assert 'MATCH (a:abc_Thing {identifier: "T-1"})' in out
        assert 'MATCH (b:Fee {identifier: "F-1"})' in out
        assert "CREATE (a)-[:ABC_OWNS]->(b);" in out

    def test_a_node_without_an_id_like_property_keeps_its_relationships(self, tmp_path):
        """Relationships MATCH on `identifier`. A node carried one only when
        a property was named `identifier` or ended in Number/Id, so a thing
        with just a note got none and its relationship left the seed."""
        inv, matrix = self._two_namespace_domain()
        out = self._generate(inv, matrix, (
            f"@prefix dbpi: <{self.DBPI}> .\n@prefix abc: <{self.ABC}> .\n"
            '<https://data.test/fee1> a dbpi:Fee ; dbpi:feeNumber "F-1" .\n'
            '<https://data.test/thing1> a abc:Thing ; abc:note "only a note" ;\n'
            '    abc:owns <https://data.test/fee1> .\n'
        ), tmp_path)

        assert 'identifier: "https://data.test/thing1"' in out
        assert 'note: "only a note"' in out
        assert 'MATCH (a:abc_Thing {identifier: "https://data.test/thing1"})' in out
        assert "CREATE (a)-[:ABC_OWNS]->(b);" in out

    def test_seed_prefix_declarations_are_not_consulted(self, tmp_path):
        """A seed file that binds no prefixes, or binds them differently, still matches."""
        inv, matrix = self._two_namespace_domain()
        out = self._generate(inv, matrix, (
            "@prefix dbpi: <https://elsewhere.test/> .\n"
            f'<urn:fee1> a <{self.DBPI}Fee> ; <{self.DBPI}feeNumber> "F-1" .\n'
            f'<urn:thing1> a <{self.ABC}Thing> ; <{self.ABC}thingId> "T-1" .\n'
        ), tmp_path)

        assert 'CREATE (:Fee {feeNumber: "F-1", identifier: "F-1"});' in out
        assert 'CREATE (:abc_Thing {abc_thingId: "T-1", identifier: "T-1"});' in out

    def test_relationship_type_comes_from_the_property_qname_not_the_predicate_iri(self, tmp_path):
        """CSV ingest records property IRIs as `{ns}#{Class}.{prop}`; the seeded
        relationship type must match schema.cypher (`HAS_FEE`), not `ACCOUNT.HAS_FEE`."""
        csv = "https://example.test/csv"
        account = make_class("csv:Account"); account["iri"] = f"{csv}#Account"
        fee = make_class("csv:Fee"); fee["iri"] = f"{csv}#Fee"
        has_fee = make_obj_prop("csv:hasFee", domain=["csv:Account"], range_val=["csv:Fee"])
        has_fee["iri"] = f"{csv}#Account.hasFee"
        acct_id = make_dt_prop("csv:accountId", domain=["csv:Account"]); acct_id["iri"] = f"{csv}#Account.accountId"
        fee_id = make_dt_prop("csv:feeId", domain=["csv:Fee"]); fee_id["iri"] = f"{csv}#Fee.feeId"
        inv = make_inv([account, fee], obj_props=[has_fee], dt_props=[acct_id, fee_id])
        inv["primaryNamespace"] = {"prefix": "csv", "uri": csv}
        matrix = make_matrix([make_mapping("csv:Account", "extend"), make_mapping("csv:Fee", "extend")])
        out = self._generate(inv, matrix, (
            f'<https://data.test/a1> a <{csv}#Account> ; <{csv}#Account.accountId> "A-1" ;'
            f' <{csv}#Account.hasFee> <https://data.test/f1> .\n'
            f'<https://data.test/f1> a <{csv}#Fee> ; <{csv}#Fee.feeId> "F-1" .\n'
        ), tmp_path)

        assert "CREATE (a)-[:HAS_FEE]->(b);" in out
        assert "ACCOUNT.HAS_FEE" not in out

    def test_instances_of_other_iris_are_not_seeded(self, tmp_path):
        inv, matrix = self._two_namespace_domain()
        out = self._generate(inv, matrix, (
            f'<urn:x> a <{self.DBPI}Thing> ; <{self.DBPI}thingId> "X-1" .\n'
        ), tmp_path)

        assert "CREATE (:" not in out


def test_a_seed_file_matching_no_active_class_says_so(tmp_path):
    """Silence reads as "no seed data to load": the operator ships and
    deploys believing the sample data loaded."""
    from ontology_mapper.generate_kg_artifacts import generate_seed_cypher

    seed = tmp_path / "seed.ttl"
    seed.write_text('<urn:one> a <https://sample.test/src/Record> .',
                    encoding="utf-8")
    active = [{"qname": "src:Record", "label": "Record",
               "iri": "https://sample.test/src/Record/",  # trailing slash
               "datatypeProps": [], "objectProps": []}]
    cypher = generate_seed_cypher(active, [], seed, "sample", {})

    assert "No seed instance matches an active class" in cypher
    assert "https://sample.test/src/Record" in cypher


def test_a_matching_seed_file_still_seeds_without_the_note(tmp_path):
    """The legitimate flow: the note appears only when nothing matched."""
    from ontology_mapper.generate_kg_artifacts import generate_seed_cypher

    seed = tmp_path / "seed.ttl"
    seed.write_text('<urn:one> a <https://sample.test/src/Record> .',
                    encoding="utf-8")
    active = [{"qname": "src:Record", "label": "Record",
               "iri": "https://sample.test/src/Record",
               "datatypeProps": [], "objectProps": []}]
    cypher = generate_seed_cypher(active, [], seed, "sample", {})

    # Only the note is under test here: an instance whose type the inventory
    # records is a match, whatever the node emitter then writes for it.
    assert "No seed instance matches an active class" not in cypher


class TestSeedPropertyKeys:
    """The seed's property key comes from the inventory QName, like the
    schema's — the IRI tail does not survive Neo4j."""

    _generate = TestSeedDataIdentity._generate

    def test_a_csv_shaped_property_iri_does_not_become_a_dotted_key(self, tmp_path):
        """CSV ingest records property IRIs as `{ns}#{Class}.{prop}`.
        `SET n.Account.accountId` is not valid Cypher, and it does not match
        the `accountId` the schema constrains."""
        csv = "https://example.test/csv"
        account = make_class("csv:Account"); account["iri"] = f"{csv}#Account"
        acct_id = make_dt_prop("csv:accountId", domain=["csv:Account"])
        acct_id["iri"] = f"{csv}#Account.accountId"
        inv = make_inv([account], dt_props=[acct_id])
        inv["primaryNamespace"] = {"prefix": "csv", "uri": csv}
        matrix = make_matrix([make_mapping("csv:Account", "extend")])

        out = self._generate(inv, matrix, (
            f'<https://data.test/a1> a <{csv}#Account> ;'
            f' <{csv}#Account.accountId> "A-1" .\n'), tmp_path)

        assert "accountId:" in out or "accountId =" in out or "accountId" in out
        assert "Account.accountId" not in out


class TestSeedRound13:
    """Round thirteen (emitters): seed identity and keys."""

    SRC = "https://sample.test/src/"
    AUG = "https://aug.test/ns#"
    XSD = "http://www.w3.org/2001/XMLSchema#"

    def _cypher(self, tmp_path):
        from ontology_mapper.generate_kg_artifacts import generate_seed_cypher

        def dt(qname, domain, iri, rng=None):
            return {**make_dt_prop(qname, domain=domain, range_val=rng), "iri": iri}

        def obj(qname, domain, rng, iri):
            return {**make_obj_prop(qname, domain=domain, range_val=rng), "iri": iri}

        classes = []
        for name in ("Case", "Fee", "Note", "Gone"):
            classes.append({**make_class(f"src:{name}"), "iri": self.SRC + name})
        inv = make_inv(
            classes,
            obj_props=[obj("src:fee", ["src:Case"], ["src:Fee"], self.SRC + "fee"),
                       obj("src:note", ["src:Case"], ["src:Note"], self.SRC + "note")],
            dt_props=[dt("src:feeNumber", ["src:Fee"], self.SRC + "feeNumber", [self.XSD + "integer"]),
                      dt("src:caseNumber", ["src:Case"], self.SRC + "caseNumber"),
                      dt("src:name", ["src:Case"], self.SRC + "name"),
                      # declared, but only on an excluded class
                      dt("aug:name", ["src:Gone"], self.AUG + "name")])
        inv["primaryNamespace"] = {"prefix": "src"}
        inv["namespaceMap"] = {self.SRC: "src:", self.AUG: "aug:"}
        matrix = make_matrix([make_mapping("src:Case", "extend"), make_mapping("src:Fee", "extend"),
                              make_mapping("src:Note", "extend"), make_mapping("src:Gone", "exclude")])
        seed = tmp_path / "seed.ttl"
        seed.write_text(f"""
@prefix src: <{self.SRC}> .
@prefix aug: <{self.AUG}> .
@prefix xsd: <{self.XSD}> .
src:c1 a src:Case ; src:caseNumber "C-1" ; src:name "primary name" ; aug:name "augmenting name" ;
   <http://other.test/x#2ndLine> "two" ; src:fee src:f1 ; src:note src:n1 .
src:f1 a src:Fee ; src:feeNumber "1001"^^xsd:integer .
src:n1 a src:Note .
""", encoding="utf-8")
        active = build_active_classes(inv, matrix)
        return generate_seed_cypher(active, build_relationships(active), seed, "sample",
                                    graph_property_keys(inv))

    def test_an_integer_identifier_is_matched_as_an_integer(self, tmp_path):
        """The node was written `identifier: 1001` and the MATCH looked for
        "1001", which Neo4j never equals, so the relationship was lost."""
        cypher = self._cypher(tmp_path)
        assert "CREATE (:Fee {feeNumber: 1001, identifier: 1001});" in cypher
        assert "MATCH (b:Fee {identifier: 1001})" in cypher

    def test_an_unowned_property_keeps_its_own_key(self, tmp_path):
        """aug:name, owned by no active class, took the bare key `name` and
        overwrote src:name on the same node."""
        cypher = self._cypher(tmp_path)
        assert 'aug_name: "augmenting name"' in cypher
        assert 'name: "primary name"' in cypher

    def test_an_undeclared_key_is_a_cypher_identifier(self, tmp_path):
        assert '_2ndLine: "two"' in self._cypher(tmp_path)

    def test_a_node_with_only_relationships_is_created(self, tmp_path):
        """src:n1 has no literal, so it was never created and the
        relationship to it matched nothing."""
        cypher = self._cypher(tmp_path)
        iri = self.SRC + "n1"
        assert f'CREATE (:Note {{identifier: "{iri}"}});' in cypher
        assert f'MATCH (b:Note {{identifier: "{iri}"}})' in cypher

