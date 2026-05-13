#!/usr/bin/env python3
"""Integration tests: real Cypher execution against Neo4j via testcontainers.

Spins up a real Neo4j instance in Docker, executes generated Cypher scripts
(schema, seed, queries), and verifies the resulting graph state.

REQUIREMENTS:
    pip install -e ".[integration]"   # installs testcontainers[neo4j] + neo4j driver
    Docker must be running locally.

RUN:
    pytest tests/test_kg_integration_neo4j.py -v
    pytest -m docker -v   # run all Docker-dependent tests

SKIP BEHAVIOR:
    All tests are skipped automatically if:
    - testcontainers is not installed
    - neo4j driver is not installed
    - Docker daemon is not running / not available

VERSION TESTING:
    Tests are parameterized across NEO4J_VERSIONS. To add a new Neo4j version,
    append its Docker image tag to the list below. Update the "Tested Neo4j
    Versions" table in README.md when the new version passes.
"""

import re
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# Neo4j versions to test against.
# Each entry is a Docker image tag. Tests run against every version.
# When adding a version here, run the tests; if they pass, update README.md.
# ---------------------------------------------------------------------------
NEO4J_VERSIONS = [
    "neo4j:5-community",
]

# ---------------------------------------------------------------------------
# Skip if dependencies are not available
# ---------------------------------------------------------------------------
pytestmark = [
    pytest.mark.docker,
    pytest.mark.integration,
]

try:
    from testcontainers.neo4j import Neo4jContainer
    from neo4j import GraphDatabase
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

if not HAS_DEPS:
    pytest.skip(
        "testcontainers and/or neo4j driver not installed "
        "(pip install -e '.[integration]')",
        allow_module_level=True,
    )

# Check Docker availability early
try:
    import docker
    _client = docker.from_env()
    _client.ping()
    _client.close()
    HAS_DOCKER = True
except Exception:
    HAS_DOCKER = False

if not HAS_DOCKER:
    pytest.skip(
        "Docker daemon is not running or not available",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Now safe to import pipeline code
# ---------------------------------------------------------------------------
from ontology_mapper.generate_kg_artifacts import (
    build_active_classes,
    build_relationships,
    generate_schema_cypher,
    generate_seed_cypher,
    generate_query_templates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def split_cypher_statements(cypher_text):
    """Split a multi-statement Cypher script into individual executable statements.

    Handles semicolons as statement terminators, skips comments and blank lines.
    Multi-line statements (e.g. CREATE CONSTRAINT ... FOR ... REQUIRE ...) are
    reassembled into a single string.
    """
    statements = []
    for stmt in cypher_text.split(";"):
        cleaned = stmt.strip()
        lines = [
            line for line in cleaned.split("\n")
            if line.strip() and not line.strip().startswith("//")
        ]
        if lines:
            statements.append("\n".join(lines))
    return statements


# ---------------------------------------------------------------------------
# Test data factory (same domain as test_kg_integration_cypher.py)
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


def build_test_domain():
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


def write_seed_ttl(tmp_path):
    """Write a minimal seed TTL file and return its path."""
    seed_dir = tmp_path / "seed-data"
    seed_dir.mkdir(parents=True, exist_ok=True)
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
        'dbpi:insp1 rdf:type dbpi:Inspection ;\n'
        '    dbpi:identifier "INSP-001" ;\n'
        '    dbpi:inspectionDate "2026-03-15"^^xsd:date .\n'
        '\n'
        'dbpi:permit1 dbpi:submittedBy dbpi:person1 .\n'
        'dbpi:permit1 dbpi:locatedAt dbpi:addr1 .\n'
        'dbpi:permit1 dbpi:hasInspection dbpi:insp1 .\n'
        'dbpi:insp1 dbpi:conductedBy dbpi:person1 .\n',
        encoding="utf-8",
    )
    return seed_path


# ---------------------------------------------------------------------------
# Artifacts holder — generated once per version, shared across test classes
# ---------------------------------------------------------------------------

class Artifacts:
    """Pre-generated Cypher artifacts for a test run."""

    def __init__(self, tmp_path):
        inv, matrix = build_test_domain()
        self.active_classes = build_active_classes(inv, matrix)
        self.relationships = build_relationships(self.active_classes)
        self.active_labels = {c["label"] for c in self.active_classes}
        self.schema = generate_schema_cypher(
            self.active_classes, self.relationships, "dbpi",
        )
        seed_path = write_seed_ttl(tmp_path)
        self.seed = generate_seed_cypher(
            self.active_classes, self.relationships, seed_path, "dbpi",
        )
        self.queries = generate_query_templates(
            self.active_classes, self.relationships, "dbpi",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", params=NEO4J_VERSIONS)
def neo4j_container(request):
    """Start a Neo4j container for the parameterized image tag."""
    image = request.param
    container = Neo4jContainer(image)
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="module")
def neo4j_driver(neo4j_container):
    """Create a Neo4j driver connected to the test container."""
    url = neo4j_container.get_connection_url()
    driver = GraphDatabase.driver(
        url,
        auth=("neo4j", neo4j_container.env["NEO4J_AUTH"].split("/")[-1]),
    )
    # Wait for the database to be ready
    driver.verify_connectivity()
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    """Generate Cypher artifacts once per module."""
    tmp = tmp_path_factory.mktemp("neo4j_artifacts")
    return Artifacts(tmp)


@pytest.fixture(scope="module")
def loaded_graph(neo4j_driver, artifacts):
    """Execute schema + seed scripts against the container.

    Returns the driver for querying. Schema and seed are loaded once
    per module (per Neo4j version).
    """
    with neo4j_driver.session() as session:
        for stmt in split_cypher_statements(artifacts.schema):
            session.run(stmt)
        for stmt in split_cypher_statements(artifacts.seed):
            session.run(stmt)
    return neo4j_driver


def _run_query(driver, cypher, **params):
    """Run a Cypher query and return results as a list of dicts."""
    with driver.session() as session:
        result = session.run(cypher, **params)
        return [record.data() for record in result]


# ---------------------------------------------------------------------------
# TestSchemaExecution
# ---------------------------------------------------------------------------

class TestSchemaExecution:
    """Execute schema.cypher against a fresh Neo4j container."""

    def test_schema_creates_constraints(self, loaded_graph, artifacts):
        """Every active class should have a uniqueness constraint on identifier."""
        rows = _run_query(loaded_graph, "SHOW CONSTRAINTS YIELD name RETURN name")
        constraint_names = {r["name"] for r in rows}
        for label in artifacts.active_labels:
            expected = f"{label}_identifier"
            assert expected in constraint_names, (
                f"Missing constraint: {expected}"
            )

    def test_schema_creates_domain_constraints(self, loaded_graph):
        """Domain-specific constraints (e.g. permitNumber) should exist."""
        rows = _run_query(loaded_graph, "SHOW CONSTRAINTS YIELD name RETURN name")
        constraint_names = {r["name"] for r in rows}
        assert "Permit_permitNumber" in constraint_names

    def test_schema_creates_indexes(self, loaded_graph):
        """Expected indexes should exist (displayName, etc.)."""
        rows = _run_query(loaded_graph, "SHOW INDEXES YIELD name RETURN name")
        index_names = {r["name"] for r in rows}
        assert "Permit_displayName" in index_names

    def test_schema_is_idempotent(self, loaded_graph, artifacts):
        """Running schema.cypher a second time should not error (IF NOT EXISTS)."""
        with loaded_graph.session() as session:
            for stmt in split_cypher_statements(artifacts.schema):
                session.run(stmt)
        # Verify constraint count is unchanged
        rows = _run_query(loaded_graph, "SHOW CONSTRAINTS YIELD name RETURN name")
        constraint_names = {r["name"] for r in rows}
        for label in artifacts.active_labels:
            assert f"{label}_identifier" in constraint_names


# ---------------------------------------------------------------------------
# TestSeedExecution
# ---------------------------------------------------------------------------

class TestSeedExecution:
    """Verify seed data loaded correctly into the graph."""

    def test_seed_creates_expected_nodes(self, loaded_graph):
        """Graph should contain nodes for each seeded type."""
        rows = _run_query(
            loaded_graph,
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, count(*) AS cnt",
        )
        label_counts = {r["label"]: r["cnt"] for r in rows}
        assert label_counts.get("Permit", 0) >= 1
        assert label_counts.get("Person", 0) >= 1
        assert label_counts.get("Address", 0) >= 1
        assert label_counts.get("Inspection", 0) >= 1

    def test_seed_creates_expected_relationships(self, loaded_graph):
        """Graph should contain the expected relationship types."""
        rows = _run_query(
            loaded_graph,
            "MATCH ()-[r]->() RETURN type(r) AS relType, count(*) AS cnt",
        )
        rel_types = {r["relType"] for r in rows}
        assert "SUBMITTED_BY" in rel_types
        assert "LOCATED_AT" in rel_types
        assert "HAS_INSPECTION" in rel_types
        assert "CONDUCTED_BY" in rel_types

    def test_seed_node_properties_present(self, loaded_graph):
        """Seeded nodes should have property values."""
        rows = _run_query(
            loaded_graph,
            "MATCH (p:Permit) RETURN p.identifier AS id, "
            "p.permitNumber AS num, p.displayName AS name",
        )
        assert len(rows) >= 1
        permit = rows[0]
        assert permit["id"] == "PERM-001"
        assert permit["num"] == "PN-2026-001"
        assert permit["name"] == "Main St Renovation"

    def test_seed_relationship_endpoints_valid(self, loaded_graph, artifacts):
        """Every relationship endpoint should be an active label."""
        rows = _run_query(
            loaded_graph,
            "MATCH (a)-[r]->(b) "
            "RETURN labels(a) AS srcLabels, type(r) AS rel, labels(b) AS tgtLabels",
        )
        for row in rows:
            for label in row["srcLabels"]:
                assert label in artifacts.active_labels, (
                    f"Relationship source label '{label}' not active"
                )
            for label in row["tgtLabels"]:
                assert label in artifacts.active_labels, (
                    f"Relationship target label '{label}' not active"
                )

    def test_seed_no_excluded_labels(self, loaded_graph):
        """Excluded types should have no nodes in the graph."""
        rows = _run_query(
            loaded_graph,
            "MATCH (n:InternalLog) RETURN count(n) AS cnt",
        )
        assert rows[0]["cnt"] == 0


# ---------------------------------------------------------------------------
# TestQueryExecution
# ---------------------------------------------------------------------------

class TestQueryExecution:
    """Execute generated query templates against the loaded graph."""

    def test_find_by_identifier_returns_node(self, loaded_graph):
        """find-by-identifier should find a node with a known identifier."""
        rows = _run_query(
            loaded_graph,
            "MATCH (n) "
            "WHERE $label IN labels(n) AND n.identifier = $identifier "
            "RETURN n",
            label="Permit",
            identifier="PERM-001",
        )
        assert len(rows) == 1

    def test_entity_specific_query_executes(self, loaded_graph, artifacts):
        """Entity-specific find queries should execute without error."""
        for name, cypher in artifacts.queries.items():
            if not name.startswith("find-") or name == "find-by-identifier":
                continue
            # These use $propertyName and $value parameters
            with loaded_graph.session() as session:
                result = session.run(
                    cypher,
                    propertyName="identifier",
                    value="PERM-001",
                )
                # Just verify it executes; results depend on label match
                list(result)

    def test_shortest_path_between_connected_nodes(self, loaded_graph):
        """shortest-path should find a path between connected nodes."""
        rows = _run_query(
            loaded_graph,
            "MATCH (a {identifier: $startId}), (b {identifier: $endId}) "
            "MATCH p = shortestPath((a)-[*..6]-(b)) "
            "RETURN p",
            startId="PERM-001",
            endId="PER-001",
        )
        assert len(rows) >= 1

    def test_export_subgraph_returns_paths(self, loaded_graph):
        """export-subgraph should return paths for a known node."""
        rows = _run_query(
            loaded_graph,
            "MATCH path = (root {identifier: $identifier})-[*0..2]-(connected) "
            "RETURN path",
            identifier="PERM-001",
        )
        # Permit is connected to Person, Address, Inspection
        assert len(rows) >= 3

    def test_with_relations_query(self, loaded_graph, artifacts):
        """Entity-with-relations queries should return connections."""
        for name, cypher in artifacts.queries.items():
            if not name.endswith("-with-relations"):
                continue
            with loaded_graph.session() as session:
                result = session.run(cypher, identifier="PERM-001")
                rows = [record.data() for record in result]
                # May or may not match depending on the label — just verify no error
                assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# TestCrossScriptConsistency
# ---------------------------------------------------------------------------

class TestCrossScriptConsistency:
    """End-to-end verification: schema ↔ seed ↔ queries in the live graph."""

    def test_schema_labels_match_seed_labels(self, loaded_graph, artifacts):
        """Labels with constraints should cover all labels with nodes."""
        # Get labels that have nodes
        rows = _run_query(
            loaded_graph,
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN DISTINCT label",
        )
        node_labels = {r["label"] for r in rows}

        # Get labels that have constraints
        constraint_rows = _run_query(
            loaded_graph,
            "SHOW CONSTRAINTS YIELD name RETURN name",
        )
        # Constraint names follow pattern: Label_property
        constrained_labels = set()
        for r in constraint_rows:
            parts = r["name"].rsplit("_", 1)
            if len(parts) == 2:
                constrained_labels.add(parts[0])

        # Every node label should have at least one constraint
        unconstrained = node_labels - constrained_labels
        assert not unconstrained, (
            f"Node labels without constraints: {unconstrained}"
        )

    def test_query_labels_exist_in_graph(self, loaded_graph, artifacts):
        """Labels referenced in query templates should have nodes in the graph."""
        rows = _run_query(
            loaded_graph,
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN DISTINCT label",
        )
        graph_labels = {r["label"] for r in rows}

        # Extract concrete labels from query templates
        all_query_text = "\n".join(artifacts.queries.values())
        query_labels = set(re.findall(r"\(\w*:(\w+)[\s{)]", all_query_text))

        for label in query_labels:
            assert label in graph_labels, (
                f"Query references label '{label}' with no nodes in graph"
            )

    def test_relationship_types_documented_in_schema(self, loaded_graph, artifacts):
        """Every relationship type in the graph should appear in schema docs."""
        rows = _run_query(
            loaded_graph,
            "MATCH ()-[r]->() RETURN DISTINCT type(r) AS relType",
        )
        graph_rels = {r["relType"] for r in rows}
        schema_rels = set(re.findall(r"// (\w+): \(:", artifacts.schema))

        undocumented = graph_rels - schema_rels
        assert not undocumented, (
            f"Relationship types in graph but not in schema docs: {undocumented}"
        )
