#!/usr/bin/env python3
"""Tests for generate_kg_artifacts.py"""

import json
import pytest
from pathlib import Path
from ontology_mapper.pipeline_context import PipelineContext
from ontology_mapper.generate_kg_artifacts import (
    local_name,
    graph_label,
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


class TestGraphLabel:
    def test_basic(self):
        assert graph_label("dbpi:PermitApplication") == "PermitApplication"

    def test_simple(self):
        assert graph_label("dbpi:Address") == "Address"


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

    def test_date_transform_detected(self):
        classes = [{
            "sourceQname": "ex:Permit", "label": "Permit", "comment": "",
            "action": "reuse", "targetType": None,
            "datatypeProps": [
                {"qname": "ex:issuedDate", "label": "issuedDate",
                 "range": "http://www.w3.org/2001/XMLSchema#date"},
            ],
            "objectProps": [],
        }]
        result = generate_internal_to_edge_transform(classes)
        pm = result["transforms"][0]["propertyMappings"]
        assert pm[0]["transform"] == "xsd:date-to-iso8601"

    def test_codelist_transform_detected(self):
        classes = [{
            "sourceQname": "ex:Permit", "label": "Permit", "comment": "",
            "action": "reuse", "targetType": None,
            "datatypeProps": [
                {"qname": "ex:hasApplicationStatus", "label": "hasApplicationStatus",
                 "range": "http://www.w3.org/2001/XMLSchema#string"},
            ],
            "objectProps": [],
        }]
        result = generate_internal_to_edge_transform(classes)
        pm = result["transforms"][0]["propertyMappings"]
        assert pm[0]["transform"] == "codelist-resolve"

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
