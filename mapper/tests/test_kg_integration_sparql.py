#!/usr/bin/env python3
"""Integration tests: load generated TriG into rdflib, run generated SPARQL queries.

These tests verify that the SPARQL templates produced by generate_kg_artifacts
are syntactically valid AND return meaningful results when executed against the
TriG named graph generated from the same data model.

Requires only rdflib (already a core dependency). No external services needed.

Run:
    pytest tests/test_kg_integration_sparql.py -v
    pytest -m integration -v   # run all integration tests
"""

import re
import pytest
from pathlib import Path
from textwrap import dedent

from rdflib import Graph, Namespace, RDF, RDFS, OWL, Literal

from ontology_mapper.pipeline_context import PipelineContext
from ontology_mapper.generate_kg_artifacts import (
    generate_sparql_templates,
    generate_trig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path):
    """Create a PipelineContext with a real pkg_dir containing minimal OWL files."""
    run_dir = tmp_path / "run"
    pkg_dir = run_dir / "edge-package"
    ont_dir = pkg_dir / "ontology"
    ont_dir.mkdir(parents=True)

    ctx = PipelineContext(
        run_dir=run_dir,
        pkg_dir=pkg_dir,
        organization="redvale",
        source="dbpi",
        target_ontology="niem",
        target_version="6.0",
        input_package_path=str(tmp_path / "sources" / "pkg"),
    )

    # Write a minimal core TTL with two classes and properties
    core_ttl = dedent(f"""\
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix edge: <{ctx.edge_ns_hash}> .

        edge:Permit a owl:Class ;
            rdfs:label "Permit" ;
            rdfs:comment "A building permit" .

        edge:Person a owl:Class ;
            rdfs:label "Person" ;
            rdfs:comment "A person" .

        edge:identifier a owl:DatatypeProperty ;
            rdfs:domain edge:Permit ;
            rdfs:range xsd:string .

        edge:submittedBy a owl:ObjectProperty ;
            rdfs:domain edge:Permit ;
            rdfs:range edge:Person .
    """)
    (ont_dir / ctx.ontology_filename("core")).write_text(core_ttl, encoding="utf-8")

    # Write a minimal extensions TTL
    ext_ttl = dedent(f"""\
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix edge: <{ctx.edge_ns_hash}> .

        edge:Inspector a owl:Class ;
            rdfs:label "Inspector" ;
            rdfs:comment "A building inspector" .
    """)
    (ont_dir / ctx.ontology_filename("extensions")).write_text(ext_ttl, encoding="utf-8")

    return ctx


def _strip_placeholders(sparql_text, entity_iri="http://example.org/entity1"):
    """Replace $entityIRI / $typeIRI placeholders with concrete IRIs."""
    result = sparql_text
    result = result.replace("$entityIRI", entity_iri)
    result = result.replace("$typeIRI", entity_iri)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSparqlIntegration:
    """Load generated TriG into rdflib, execute generated SPARQL templates."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.ctx = _make_ctx(tmp_path)
        self.trig_content = generate_trig(self.ctx)
        self.templates = generate_sparql_templates(self.ctx)

        # Parse TriG into ConjunctiveGraph (supports named graph querying).
        # rdflib deprecates ConjunctiveGraph in favor of Dataset, but Dataset
        # doesn't expose named-graph triples via the default query interface.
        from rdflib import ConjunctiveGraph
        self.graph = ConjunctiveGraph()
        self.graph.parse(data=self.trig_content, format="trig")

    def test_trig_parses_without_error(self):
        """The generated TriG should parse cleanly."""
        assert len(self.graph) > 0

    def test_trig_contains_classes(self):
        """TriG should contain the OWL classes from the ontology files."""
        classes = set()
        for s, p, o in self.graph.triples((None, RDF.type, OWL.Class)):
            classes.add(str(s))
        edge_ns = self.ctx.edge_ns_hash
        assert f"{edge_ns}Permit" in classes
        assert f"{edge_ns}Person" in classes
        assert f"{edge_ns}Inspector" in classes

    def test_list_classes_query_returns_results(self):
        """The list-classes SPARQL template should find all owl:Class instances."""
        sparql = self.templates["list-classes"]
        results = list(self.graph.query(sparql))
        # Should find at least Permit, Person, Inspector
        assert len(results) >= 3
        labels = {str(row[1]) for row in results if row[1]}
        assert "Permit" in labels
        assert "Person" in labels
        assert "Inspector" in labels

    def test_describe_entity_parses_and_executes(self):
        """The describe-entity template should parse with a substituted IRI."""
        edge_ns = self.ctx.edge_ns_hash
        sparql = _strip_placeholders(
            self.templates["describe-entity"],
            entity_iri=f"{edge_ns}Permit",
        )
        results = self.graph.query(sparql)
        # DESCRIBE returns a graph — should have triples about Permit
        result_graph = results.graph if hasattr(results, 'graph') else Graph()
        assert len(result_graph) > 0

    def test_find_by_type_parses_and_executes(self):
        """The find-by-type template should parse with a substituted type IRI."""
        edge_ns = self.ctx.edge_ns_hash
        sparql = _strip_placeholders(
            self.templates["find-by-type"],
            entity_iri=f"{edge_ns}Permit",
        )
        # Replace $typeIRI too (same template uses it)
        sparql = sparql.replace("$typeIRI", f"{edge_ns}Permit")
        results = list(self.graph.query(sparql))
        # No instances in the ontology, but the query should execute without error
        assert isinstance(results, list)

    def test_entity_neighborhood_parses(self):
        """The entity-neighborhood template should parse and execute."""
        edge_ns = self.ctx.edge_ns_hash
        sparql = _strip_placeholders(
            self.templates["entity-neighborhood"],
            entity_iri=f"{edge_ns}Permit",
        )
        results = list(self.graph.query(sparql))
        # Permit has rdfs:label, rdfs:comment, rdf:type — should return triples
        assert len(results) >= 1

    def test_construct_subgraph_parses(self):
        """The construct-subgraph template should parse and return a graph."""
        edge_ns = self.ctx.edge_ns_hash
        sparql = _strip_placeholders(
            self.templates["construct-subgraph"],
            entity_iri=f"{edge_ns}Permit",
        )
        results = self.graph.query(sparql)
        result_graph = results.graph if hasattr(results, 'graph') else Graph()
        # Should construct triples about Permit
        assert len(result_graph) >= 1

    def test_all_templates_are_valid_sparql(self):
        """Every generated SPARQL template should parse without error."""
        from rdflib.plugins.sparql import prepareQuery
        edge_ns = self.ctx.edge_ns_hash
        for name, sparql in self.templates.items():
            # Substitute placeholders with a valid IRI
            clean = _strip_placeholders(sparql, f"{edge_ns}Permit")
            try:
                prepareQuery(clean)
            except Exception as e:
                pytest.fail(f"SPARQL template '{name}' failed to parse: {e}")

    def test_trig_named_graph_structure(self):
        """TriG should place triples inside the expected named graph."""
        edge_ns = self.ctx.edge_ns_hash
        expected_graph_uri = edge_ns.rstrip("#") + "/graph"
        graph_names = {str(g.identifier) for g in self.graph.contexts()}
        assert expected_graph_uri in graph_names
