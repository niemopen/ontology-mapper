#!/usr/bin/env python3
"""Integration tests: structural verification of generated Cypher scripts.

These tests parse all generated Cypher scripts (schema, seed, queries), build a
dict-based graph model, and verify the full data flow:

  schema labels → seed nodes → seed relationships → query patterns

All reference the same entity labels. No Neo4j instance required — this is pure
Python structural analysis of the generated Cypher text.

Run:
    pytest tests/test_kg_integration_cypher.py -v
    pytest -m integration -v   # run all integration tests
"""

import re
import pytest
from pathlib import Path

from ontology_mapper.generate_kg_artifacts import (
    build_active_classes,
    build_relationships,
    generate_schema_cypher,
    generate_seed_cypher,
    generate_query_templates,
)


# ---------------------------------------------------------------------------
# Test data factory (reuses patterns from test_generate_kg_artifacts.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Cypher parsing helpers
# ---------------------------------------------------------------------------

def extract_constraint_labels(schema_cypher):
    """Extract node labels from CREATE CONSTRAINT statements."""
    return set(re.findall(r"FOR \(n:(\w+)\)", schema_cypher))


def extract_index_labels(schema_cypher):
    """Extract node labels from CREATE INDEX statements."""
    return set(re.findall(r"FOR \(n:(\w+)\)", schema_cypher))


def extract_relationship_types(schema_cypher):
    """Extract documented relationship types from schema comments."""
    return set(re.findall(r"// (\w+): \(:", schema_cypher))


def extract_relationship_endpoints(schema_cypher):
    """Extract (rel_type, source_label, target_label) from relationship comments."""
    pattern = r"// (\w+): \(:(\w+)\)-\[:\1\]->\(:(\w+)\)"
    return {(m[0], m[1], m[2]) for m in re.findall(pattern, schema_cypher)}


def extract_seed_create_labels(seed_cypher):
    """Extract labels from CREATE (:Label {...}) statements in seed data."""
    return set(re.findall(r"CREATE \(:(\w+)\s", seed_cypher))


def extract_seed_match_labels(seed_cypher):
    """Extract labels from MATCH (x:Label ...) statements in seed data."""
    return set(re.findall(r"MATCH \(\w+:(\w+)\s", seed_cypher))


def extract_seed_relationship_types(seed_cypher):
    """Extract relationship types from CREATE (a)-[:REL]->(b) in seed data."""
    return set(re.findall(r"CREATE \(a\)-\[:(\w+)\]->\(b\)", seed_cypher))


def extract_query_labels(query_cypher):
    """Extract node labels referenced in query templates."""
    # Matches patterns like (n:Label), (:Label), (n:Label {...)
    return set(re.findall(r"\(\w*:(\w+)[\s{)]", query_cypher))


# ---------------------------------------------------------------------------
# Integration test fixture
# ---------------------------------------------------------------------------

def _build_test_domain():
    """Build a realistic multi-class domain with relationships and properties."""
    inv = make_inv(
        classes=[
            make_class("dbpi:Permit", "A building permit"),
            make_class("dbpi:Person", "An applicant"),
            make_class("dbpi:Address", "A street address"),
            make_class("dbpi:Inspection", "A field inspection"),
            make_class("dbpi:InternalLog", "Internal-only — excluded"),
        ],
        obj_props=[
            make_obj_prop("dbpi:submittedBy",
                          domain=["dbpi:Permit"], range_val=["dbpi:Person"]),
            make_obj_prop("dbpi:locatedAt",
                          domain=["dbpi:Permit"], range_val=["dbpi:Address"]),
            make_obj_prop("dbpi:hasInspection",
                          domain=["dbpi:Permit"], range_val=["dbpi:Inspection"]),
            make_obj_prop("dbpi:conductedBy",
                          domain=["dbpi:Inspection"], range_val=["dbpi:Person"]),
            # This range is excluded, so it should be filtered out
            make_obj_prop("dbpi:loggedIn",
                          domain=["dbpi:Permit"], range_val=["dbpi:InternalLog"]),
        ],
        dt_props=[
            make_dt_prop("dbpi:identifier", domain=["dbpi:Permit"]),
            make_dt_prop("dbpi:permitNumber", domain=["dbpi:Permit"]),
            make_dt_prop("dbpi:displayName", domain=["dbpi:Permit"]),
            make_dt_prop("dbpi:identifier", domain=["dbpi:Person"]),
            make_dt_prop("dbpi:givenName", domain=["dbpi:Person"]),
            make_dt_prop("dbpi:identifier", domain=["dbpi:Address"]),
            make_dt_prop("dbpi:streetAddress", domain=["dbpi:Address"]),
            make_dt_prop("dbpi:identifier", domain=["dbpi:Inspection"]),
            make_dt_prop("dbpi:inspectionDate", domain=["dbpi:Inspection"],
                         range_val=["http://www.w3.org/2001/XMLSchema#date"]),
        ],
    )

    matrix = make_matrix([
        make_mapping("dbpi:Permit", "extend", "nc:ActivityType"),
        make_mapping("dbpi:Person", "reuse", "nc:PersonType"),
        make_mapping("dbpi:Address", "reuse", "nc:AddressType"),
        make_mapping("dbpi:Inspection", "extend"),
        make_mapping("dbpi:InternalLog", "exclude"),
    ])

    return inv, matrix


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCypherStructuralIntegration:
    """Verify cross-script consistency of generated Cypher artifacts."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        inv, matrix = _build_test_domain()
        self.active_classes = build_active_classes(inv, matrix)
        self.relationships = build_relationships(self.active_classes)
        self.active_labels = {c["label"] for c in self.active_classes}

        self.schema = generate_schema_cypher(
            self.active_classes, self.relationships, "dbpi",
        )

        # Seed cypher with no seed file — produces a stub
        self.seed = generate_seed_cypher(
            self.active_classes, self.relationships,
            tmp_path / "nonexistent-seed.ttl", "dbpi",
        )

        self.queries = generate_query_templates(
            self.active_classes, self.relationships, "dbpi",
        )

    # ── Active classes correctness ────────────────────────────────────

    def test_excluded_class_not_active(self):
        assert "InternalLog" not in self.active_labels

    def test_all_mapped_classes_active(self):
        for label in ("Permit", "Person", "Address", "Inspection"):
            assert label in self.active_labels

    def test_excluded_range_relationship_filtered(self):
        """Object prop with excluded range should not appear in relationships."""
        rel_names = {r["name"] for r in self.relationships}
        assert "LOGGED_IN" not in rel_names

    def test_active_range_relationships_present(self):
        rel_names = {r["name"] for r in self.relationships}
        assert "SUBMITTED_BY" in rel_names
        assert "LOCATED_AT" in rel_names
        assert "HAS_INSPECTION" in rel_names
        assert "CONDUCTED_BY" in rel_names

    # ── Schema ↔ active classes ──────────────────────────────────────

    def test_schema_constraints_cover_all_active_labels(self):
        """Every active class should have at least an identifier constraint."""
        constraint_labels = extract_constraint_labels(self.schema)
        for label in self.active_labels:
            assert label in constraint_labels, (
                f"Missing constraint for active label: {label}"
            )

    def test_schema_has_no_spurious_labels(self):
        """Schema should not reference excluded labels."""
        constraint_labels = extract_constraint_labels(self.schema)
        assert "InternalLog" not in constraint_labels

    def test_schema_relationship_docs_match_relationships(self):
        """Documented relationship types should match built relationships."""
        schema_rels = extract_relationship_endpoints(self.schema)
        built_rels = {
            (r["name"], r["sourceLabel"], r["targetLabel"])
            for r in self.relationships
        }
        assert schema_rels == built_rels

    # ── Schema ↔ seed consistency ────────────────────────────────────
    # (When seed data is absent, seed.cypher is a stub — these tests
    # verify the structural properties hold for the non-stub case too.)

    def test_seed_stub_when_no_seed_file(self):
        """Without a seed file, seed.cypher should be a comment-only stub."""
        non_comment = [
            line for line in self.seed.split("\n")
            if line.strip() and not line.strip().startswith("//")
        ]
        assert len(non_comment) == 0

    # ── Query templates ↔ active labels ──────────────────────────────

    def test_queries_reference_only_active_labels(self):
        """Labels in query templates must be a subset of active labels.

        Query templates may use parameterized labels ($label) which don't
        appear in the regex, so we only check concrete label references.
        """
        all_query_text = "\n".join(self.queries.values())
        referenced_labels = extract_query_labels(all_query_text)
        for label in referenced_labels:
            assert label in self.active_labels, (
                f"Query references label '{label}' which is not an active class"
            )

    def test_find_by_identifier_present(self):
        assert "find-by-identifier" in self.queries

    def test_shortest_path_present(self):
        assert "shortest-path" in self.queries

    def test_export_subgraph_present(self):
        assert "export-subgraph" in self.queries

    # ── All Cypher is syntactically valid (basic check) ──────────────

    def test_schema_all_statements_terminated(self):
        """Every CREATE statement should end with a semicolon."""
        for line in self.schema.split("\n"):
            stripped = line.strip()
            if stripped.startswith("CREATE ") and "IF NOT EXISTS" in stripped:
                # Multi-line constraint — the semicolon is on the next line
                continue
            if stripped.startswith("FOR (") or stripped.startswith("ON ("):
                assert stripped.endswith(";"), f"Unterminated: {stripped}"

    def test_no_empty_query_templates(self):
        """No query template should be empty or comment-only."""
        for name, content in self.queries.items():
            non_comment = [
                line for line in content.strip().split("\n")
                if line.strip() and not line.strip().startswith("//")
            ]
            assert len(non_comment) > 0, f"Query '{name}' is empty"


@pytest.mark.integration
class TestCypherWithSeedData:
    """Verify seed.cypher with actual seed data present.

    Uses a minimal Turtle file as seed data to test the full
    schema → seed → relationship data flow.
    """

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        inv, matrix = _build_test_domain()
        self.active_classes = build_active_classes(inv, matrix)
        self.relationships = build_relationships(self.active_classes)
        self.active_labels = {c["label"] for c in self.active_classes}

        self.schema = generate_schema_cypher(
            self.active_classes, self.relationships, "dbpi",
        )

        # Create a minimal seed TTL
        seed_dir = tmp_path / "seed-data"
        seed_dir.mkdir()
        seed_path = seed_dir / "dbpi-seed-data.ttl"
        seed_path.write_text(
            '@prefix dbpi: <https://example.org/> .\n'
            '@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n'
            '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n'
            '\n'
            'dbpi:permit1 rdf:type dbpi:Permit ;\n'
            '    dbpi:identifier "PERM-001" ;\n'
            '    dbpi:permitNumber "PN-2026-001" ;\n'
            '    dbpi:displayName "Main St Renovation" .\n'
            '\n'
            'dbpi:person1 rdf:type dbpi:Person ;\n'
            '    dbpi:identifier "PER-001" ;\n'
            '    dbpi:givenName "Alice" .\n'
            '\n'
            'dbpi:addr1 rdf:type dbpi:Address ;\n'
            '    dbpi:identifier "ADDR-001" ;\n'
            '    dbpi:streetAddress "123 Main St" .\n'
            '\n'
            'dbpi:permit1 dbpi:submittedBy dbpi:person1 .\n'
            'dbpi:permit1 dbpi:locatedAt dbpi:addr1 .\n',
            encoding="utf-8",
        )

        self.seed = generate_seed_cypher(
            self.active_classes, self.relationships, seed_path, "dbpi",
        )

    def test_seed_creates_nodes(self):
        """Seed data should produce CREATE statements for known types."""
        created = extract_seed_create_labels(self.seed)
        assert "Permit" in created
        assert "Person" in created
        assert "Address" in created

    def test_seed_creates_only_active_labels(self):
        """Seed should not create nodes for excluded types."""
        created = extract_seed_create_labels(self.seed)
        assert "InternalLog" not in created

    def test_seed_match_labels_subset_of_created(self):
        """Every MATCH label in seed relationships should reference a CREATEd label."""
        created = extract_seed_create_labels(self.seed)
        matched = extract_seed_match_labels(self.seed)
        orphaned = matched - created
        assert not orphaned, f"MATCH references un-CREATEd labels: {orphaned}"

    def test_seed_relationship_types_match_schema(self):
        """Relationship types in seed should be a subset of schema relationship types."""
        seed_rels = extract_seed_relationship_types(self.seed)
        schema_rels = extract_relationship_types(self.schema)
        unexpected = seed_rels - schema_rels
        assert not unexpected, f"Seed uses undocumented relationship types: {unexpected}"

    def test_schema_labels_cover_seed_labels(self):
        """All labels CREATEd in seed should have schema constraints."""
        created = extract_seed_create_labels(self.seed)
        constrained = extract_constraint_labels(self.schema)
        unconstrained = created - constrained
        assert not unconstrained, (
            f"Seed creates labels without schema constraints: {unconstrained}"
        )

    def test_seed_contains_property_values(self):
        """Seed CREATE statements should contain property values from the TTL."""
        assert "PERM-001" in self.seed
        assert "Alice" in self.seed
        assert "123 Main St" in self.seed

    def test_seed_relationships_present(self):
        """Seed should contain MATCH/CREATE relationship patterns."""
        seed_rels = extract_seed_relationship_types(self.seed)
        assert "SUBMITTED_BY" in seed_rels
        assert "LOCATED_AT" in seed_rels
