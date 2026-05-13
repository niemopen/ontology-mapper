#!/usr/bin/env python3
"""Tests for generate_owl_catalog — OWL ontology parsing, extraction, and catalog assembly."""

from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ontology_mapper.generate_owl_catalog import (
    _build_inheritance_chains,
    _build_prefix_map,
    _get_alt_labels,
    _get_definition,
    _get_label,
    _guess_format,
    _local_name,
    _qname,
    build_catalog,
    build_catalog_summary,
    definition_quality_report,
    extract_classes,
    extract_properties,
)

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
EX = Namespace("http://example.org/test/")

SAMPLE_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/test/> .

ex:Entity a owl:Class ;
    rdfs:label "Entity" ;
    rdfs:comment "A base entity." .

ex:Person a owl:Class ;
    rdfs:label "Person" ;
    rdfs:subClassOf ex:Entity ;
    skos:definition "A human individual." ;
    skos:altLabel "Individual" .

ex:Employee a owl:Class ;
    rdfs:label "Employee" ;
    rdfs:subClassOf ex:Person ;
    rdfs:comment "A person employed by an organization." .

ex:Organization a owl:Class ;
    rdfs:label "Organization" ;
    rdfs:comment "A structured group of people." .

ex:worksFor a owl:ObjectProperty ;
    rdfs:label "works for" ;
    rdfs:domain ex:Employee ;
    rdfs:range ex:Organization ;
    rdfs:comment "The organization an employee works for." .

ex:name a owl:DatatypeProperty ;
    rdfs:label "name" ;
    rdfs:domain ex:Person ;
    rdfs:range xsd:string ;
    rdfs:comment "The name of a person." .

ex:age a owl:DatatypeProperty ;
    rdfs:label "age" ;
    rdfs:domain ex:Person ;
    rdfs:range xsd:integer ;
    skos:definition "The age of a person in years." .
"""


@pytest.fixture
def sample_graph():
    """Parse the sample TTL into an rdflib Graph."""
    g = Graph()
    g.parse(data=SAMPLE_TTL, format="turtle")
    return g


@pytest.fixture
def prefix_map(sample_graph):
    return _build_prefix_map(sample_graph)


@pytest.fixture
def classes(sample_graph, prefix_map):
    return extract_classes(sample_graph, prefix_map)


@pytest.fixture
def properties(sample_graph, classes, prefix_map):
    return extract_properties(sample_graph, classes, prefix_map)


@pytest.fixture
def inheritance_chains(classes):
    return _build_inheritance_chains(classes)


# ---------------------------------------------------------------------------
# TestGuessFormat
# ---------------------------------------------------------------------------

class TestGuessFormat:
    """Tests for _guess_format()."""

    @pytest.mark.parametrize("ext,expected", [
        (".owl", "xml"),
        (".rdf", "xml"),
        (".xml", "xml"),
        (".ttl", "turtle"),
        (".n3", "n3"),
        (".nt", "nt"),
        (".jsonld", "json-ld"),
    ])
    def test_known_extensions(self, ext, expected):
        assert _guess_format(Path(f"ontology{ext}")) == expected

    def test_unknown_extension_defaults_to_xml(self):
        assert _guess_format(Path("ontology.xyz")) == "xml"

    def test_uppercase_extension(self):
        assert _guess_format(Path("ontology.OWL")) == "xml"


# ---------------------------------------------------------------------------
# TestLocalName
# ---------------------------------------------------------------------------

class TestLocalName:
    """Tests for _local_name()."""

    def test_hash_uri(self):
        assert _local_name("http://example.org/ontology#Person") == "Person"

    def test_slash_uri(self):
        assert _local_name("http://example.org/ontology/Person") == "Person"

    def test_no_separator(self):
        assert _local_name("Person") == "Person"


# ---------------------------------------------------------------------------
# TestGetLabel
# ---------------------------------------------------------------------------

class TestGetLabel:
    """Tests for _get_label()."""

    def test_returns_english_label(self, sample_graph):
        assert _get_label(sample_graph, EX.Person) == "Person"

    def test_returns_untagged_label(self, sample_graph):
        # All labels in the fixture are untagged, so they should be found
        assert _get_label(sample_graph, EX.Entity) == "Entity"

    def test_returns_empty_for_missing_label(self, sample_graph):
        assert _get_label(sample_graph, URIRef("http://example.org/test/NoSuchThing")) == ""

    def test_prefers_english_over_other_language(self):
        g = Graph()
        uri = URIRef("http://example.org/test/Foo")
        g.add((uri, RDFS.label, Literal("Foo", lang="en")))
        g.add((uri, RDFS.label, Literal("Feu", lang="fr")))
        assert _get_label(g, uri) == "Foo"


# ---------------------------------------------------------------------------
# TestGetDefinition
# ---------------------------------------------------------------------------

class TestGetDefinition:
    """Tests for _get_definition()."""

    def test_skos_definition_preferred(self, sample_graph):
        # Person has skos:definition "A human individual."
        assert _get_definition(sample_graph, EX.Person) == "A human individual."

    def test_falls_back_to_rdfs_comment(self, sample_graph):
        # Entity has only rdfs:comment
        assert _get_definition(sample_graph, EX.Entity) == "A base entity."

    def test_returns_empty_for_no_definition(self, sample_graph):
        assert _get_definition(sample_graph, URIRef("http://example.org/test/NoSuchThing")) == ""

    def test_skips_null_skos_definition(self):
        g = Graph()
        uri = URIRef("http://example.org/test/Foo")
        g.add((uri, SKOS.definition, Literal("NULL")))
        g.add((uri, RDFS.comment, Literal("Real definition.")))
        assert _get_definition(g, uri) == "Real definition."


# ---------------------------------------------------------------------------
# TestGetAltLabels
# ---------------------------------------------------------------------------

class TestGetAltLabels:
    """Tests for _get_alt_labels()."""

    def test_returns_alt_labels(self, sample_graph):
        labels = _get_alt_labels(sample_graph, EX.Person)
        assert "Individual" in labels

    def test_returns_empty_when_none(self, sample_graph):
        assert _get_alt_labels(sample_graph, EX.Entity) == []


# ---------------------------------------------------------------------------
# TestBuildPrefixMap
# ---------------------------------------------------------------------------

class TestBuildPrefixMap:
    """Tests for _build_prefix_map()."""

    def test_contains_ex_prefix(self, sample_graph):
        pm = _build_prefix_map(sample_graph)
        # The ex namespace should map to the "ex" prefix
        assert pm.get(str(EX)) == "ex"

    def test_excludes_empty_prefix(self, sample_graph):
        pm = _build_prefix_map(sample_graph)
        # Empty prefix (default namespace) should not appear as a value
        for ns_uri, prefix in pm.items():
            assert prefix != "", "Empty prefix should be excluded"


# ---------------------------------------------------------------------------
# TestQname
# ---------------------------------------------------------------------------

class TestQname:
    """Tests for _qname()."""

    def test_normal_resolution(self, prefix_map):
        qn = _qname(EX.Person, prefix_map)
        assert qn == "ex:Person"

    def test_label_as_name_mode(self, sample_graph, prefix_map):
        qn = _qname(EX.worksFor, prefix_map, label_as_name=True, g=sample_graph)
        assert qn == "ex:works for"

    def test_fallback_for_unknown_namespace(self):
        pm = {"http://known.org/": "known"}
        qn = _qname(URIRef("http://unknown.org/Thing"), pm)
        assert qn == "Thing"  # falls back to _local_name

    def test_label_as_name_falls_back_without_label(self, sample_graph, prefix_map):
        uri = URIRef("http://example.org/test/Unlabeled")
        qn = _qname(uri, prefix_map, label_as_name=True, g=sample_graph)
        # No label exists, so should fall back to normal prefix:local resolution
        assert qn == "ex:Unlabeled"


# ---------------------------------------------------------------------------
# TestExtractClasses
# ---------------------------------------------------------------------------

class TestExtractClasses:
    """Tests for extract_classes()."""

    def test_correct_count(self, classes):
        # 4 classes: Entity, Person, Employee, Organization
        assert len(classes) == 4

    def test_class_has_qname(self, classes):
        person = classes[str(EX.Person)]
        assert person["qname"] == "ex:Person"

    def test_class_has_label(self, classes):
        person = classes[str(EX.Person)]
        assert person["label"] == "Person"

    def test_class_has_definition(self, classes):
        person = classes[str(EX.Person)]
        assert person["definition"] == "A human individual."

    def test_class_has_subclass_of(self, classes):
        employee = classes[str(EX.Employee)]
        assert "ex:Person" in employee["directParents"]

    def test_class_has_alt_labels(self, classes):
        person = classes[str(EX.Person)]
        assert "Individual" in person["altLabels"]

    def test_owl_builtins_excluded(self, classes):
        for uri in classes:
            assert not uri.startswith("http://www.w3.org/")

    def test_entity_has_no_parents(self, classes):
        entity = classes[str(EX.Entity)]
        assert entity["directParents"] == []

    def test_label_as_name_mode(self, sample_graph, prefix_map):
        cls = extract_classes(sample_graph, prefix_map, label_as_name=True)
        person = cls[str(EX.Person)]
        assert person["qname"] == "ex:Person"  # label happens to match local name


# ---------------------------------------------------------------------------
# TestExtractProperties
# ---------------------------------------------------------------------------

class TestExtractProperties:
    """Tests for extract_properties()."""

    def test_correct_count(self, properties):
        # 3 properties: worksFor, name, age
        assert len(properties) == 3

    def test_object_property_domain_range(self, properties):
        works_for = next(p for p in properties if p["uri"] == str(EX.worksFor))
        assert "ex:Employee" in works_for["containingTypes"]
        assert works_for["qualifiedType"] == "ex:Organization"
        assert works_for["propertyKind"] == "object"

    def test_datatype_property(self, properties):
        name_prop = next(p for p in properties if p["uri"] == str(EX.name))
        assert name_prop["propertyKind"] == "datatype"
        assert "ex:Person" in name_prop["containingTypes"]

    def test_property_names_added_to_classes(self, classes, properties):
        # extract_properties mutates classes dict, so properties fixture must run
        person = classes[str(EX.Person)]
        assert "name" in person["properties"]
        assert "age" in person["properties"]

    def test_employee_has_works_for_property(self, classes, properties):
        # extract_properties mutates classes dict, so properties fixture must run
        employee = classes[str(EX.Employee)]
        assert "worksFor" in employee["properties"]

    def test_property_has_definition(self, properties):
        age_prop = next(p for p in properties if p["uri"] == str(EX.age))
        assert age_prop["definition"] == "The age of a person in years."

    def test_property_label(self, properties):
        works_for = next(p for p in properties if p["uri"] == str(EX.worksFor))
        assert works_for["label"] == "works for"


# ---------------------------------------------------------------------------
# TestBuildInheritanceChains
# ---------------------------------------------------------------------------

class TestBuildInheritanceChains:
    """Tests for _build_inheritance_chains()."""

    def test_employee_chain(self, inheritance_chains):
        # Employee -> Person -> Entity; chain should be [ex:Entity, ex:Person]
        chain = inheritance_chains[str(EX.Employee)]
        assert chain == ["ex:Entity", "ex:Person"]

    def test_person_chain(self, inheritance_chains):
        chain = inheritance_chains[str(EX.Person)]
        assert chain == ["ex:Entity"]

    def test_entity_chain_empty(self, inheritance_chains):
        chain = inheritance_chains[str(EX.Entity)]
        assert chain == []

    def test_organization_chain_empty(self, inheritance_chains):
        chain = inheritance_chains[str(EX.Organization)]
        assert chain == []


# ---------------------------------------------------------------------------
# TestDefinitionQualityReport
# ---------------------------------------------------------------------------

class TestDefinitionQualityReport:
    """Tests for definition_quality_report()."""

    def test_coverage_percent(self, classes, properties):
        report = definition_quality_report(classes, properties, "test-ontology")
        # All 4 classes have definitions
        assert report["types"]["coveragePercent"] == 100.0

    def test_property_coverage(self, classes, properties):
        report = definition_quality_report(classes, properties, "test-ontology")
        # All 3 properties have definitions
        assert report["properties"]["coveragePercent"] == 100.0

    def test_missing_count_zero(self, classes, properties):
        report = definition_quality_report(classes, properties, "test-ontology")
        assert report["types"]["missingCount"] == 0

    def test_shortest_definitions_present(self, classes, properties):
        report = definition_quality_report(classes, properties, "test-ontology")
        assert len(report["shortestDefinitions"]) > 0
        # Each entry should have id, definition, length
        entry = report["shortestDefinitions"][0]
        assert "id" in entry
        assert "definition" in entry
        assert "length" in entry

    def test_ontology_name_in_report(self, classes, properties):
        report = definition_quality_report(classes, properties, "test-ontology")
        assert report["ontology"] == "test-ontology"

    def test_missing_definitions_reported(self):
        """Classes without definitions should show up in missingCount."""
        classes = {
            "http://example.org/test/Foo": {
                "uri": "http://example.org/test/Foo",
                "qname": "ex:Foo",
                "label": "Foo",
                "definition": "",
                "altLabels": [],
                "directParents": [],
                "properties": [],
            }
        }
        report = definition_quality_report(classes, [], "test")
        assert report["types"]["missingCount"] == 1
        assert report["types"]["coveragePercent"] == 0.0


# ---------------------------------------------------------------------------
# TestBuildCatalog
# ---------------------------------------------------------------------------

class TestBuildCatalog:
    """Tests for build_catalog()."""

    def test_has_types(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        assert "types" in catalog
        assert len(catalog["types"]) == 4

    def test_has_property_index(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        assert "propertyIndex" in catalog
        assert "ex" in catalog["propertyIndex"]

    def test_has_namespaces(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        assert "namespaces" in catalog
        assert "ex" in catalog["namespaces"]

    def test_has_stats(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        assert catalog["stats"]["totalTypes"] == 4
        assert catalog["stats"]["totalPropertyMemberships"] == 3

    def test_has_actions(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        assert "reuse" in catalog["actions"]
        assert "extend" in catalog["actions"]

    def test_type_entry_has_inheritance_chain(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        employee_type = next(t for t in catalog["types"] if t["qname"] == "ex:Employee")
        assert employee_type["inheritanceChain"] == ["ex:Entity", "ex:Person"]

    def test_version_in_catalog(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        assert catalog["version"] == "1.0"


# ---------------------------------------------------------------------------
# TestBuildCatalogSummary
# ---------------------------------------------------------------------------

class TestBuildCatalogSummary:
    """Tests for build_catalog_summary()."""

    def test_groups_by_namespace(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        summary = build_catalog_summary(catalog["types"])
        assert "ex" in summary

    def test_summary_type_count(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        summary = build_catalog_summary(catalog["types"])
        assert len(summary["ex"]["types"]) == 4

    def test_summary_entry_has_qname(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        summary = build_catalog_summary(catalog["types"])
        qnames = [t["qname"] for t in summary["ex"]["types"]]
        assert "ex:Person" in qnames

    def test_summary_entry_has_property_count(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        summary = build_catalog_summary(catalog["types"])
        person_entry = next(t for t in summary["ex"]["types"] if t["qname"] == "ex:Person")
        assert person_entry["propertyCount"] == 2  # name, age

    def test_summary_label(self, classes, properties, inheritance_chains, prefix_map):
        catalog = build_catalog(
            classes, properties, inheritance_chains, prefix_map,
            "test", "1.0", ["test.ttl"],
        )
        summary = build_catalog_summary(catalog["types"])
        assert summary["ex"]["label"] == "ex"
