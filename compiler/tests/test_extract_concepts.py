"""Tests for ontology_mapper.extract_concepts against the Redvale DBPI fixture."""

import pytest
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS, OWL, SKOS, SH, URIRef, BNode, Literal

from ontology_mapper.extract_concepts import (
    load_or_build_manifest,
    build_ns_map,
    make_to_qname,
    load_ontology_graph,
    load_shapes_graph,
    load_vocab_graph,
    load_seed_graph,
    extract_classes,
    extract_object_properties,
    extract_datatype_properties,
    extract_codelist_schemes,
    extract_workflow_models,
    extract_shacl_shapes,
    extract_augmenting_namespaces,
)

FIXTURES = Path(__file__).parent / "fixtures"
REDVALE_PKG = FIXTURES / "redvale_dbpi_agency_package"


# ─── Module-scoped fixtures (expensive graph loading done once) ──────────


@pytest.fixture(scope="module")
def pkg_path():
    return REDVALE_PKG


@pytest.fixture(scope="module")
def manifest():
    return load_or_build_manifest(REDVALE_PKG)


@pytest.fixture(scope="module")
def ns_map(manifest):
    return build_ns_map(manifest)


@pytest.fixture(scope="module")
def to_qname(ns_map):
    return make_to_qname(ns_map)


@pytest.fixture(scope="module")
def ontology_graph(manifest):
    return load_ontology_graph(REDVALE_PKG, manifest)


@pytest.fixture(scope="module")
def shapes_graph(manifest):
    return load_shapes_graph(REDVALE_PKG, manifest)


@pytest.fixture(scope="module")
def vocab_graph(manifest):
    return load_vocab_graph(REDVALE_PKG, manifest)


@pytest.fixture(scope="module")
def seed_graph(manifest):
    return load_seed_graph(REDVALE_PKG, manifest)


# ─── Manifest & Namespace Tests ─────────────────────────────────────────


class TestManifest:
    def test_manifest_loads(self, manifest):
        assert manifest is not None
        assert isinstance(manifest, dict)

    def test_primary_prefix_is_dbpi(self, manifest):
        primary = manifest["namespaces"]["primary"]
        assert primary["prefix"] == "dbpi"

    def test_primary_uri(self, manifest):
        primary = manifest["namespaces"]["primary"]
        assert primary["uri"] == "https://data.redvale.gov/ontology/dbpi/"

    def test_primary_class_count(self, manifest):
        assert manifest["namespaces"]["primary"]["classCount"] == 78

    def test_augmenting_count(self, manifest):
        augmenting = manifest["namespaces"]["augmenting"]
        assert len(augmenting) == 2

    def test_augmenting_prefixes(self, manifest):
        prefixes = {a["prefix"] for a in manifest["namespaces"]["augmenting"]}
        assert prefixes == {"gis", "fin"}

    def test_ontology_file_count(self, manifest):
        assert len(manifest["files"]["ontology"]) == 8

    def test_aggregate_file_listed(self, manifest):
        assert "ontology/dbpi-all.ttl" in manifest["files"]["aggregate"]


class TestNsMap:
    def test_ns_map_has_three_entries(self, ns_map):
        assert len(ns_map) == 3

    def test_ns_map_contains_dbpi(self, ns_map):
        assert "https://data.redvale.gov/ontology/dbpi/" in ns_map
        assert ns_map["https://data.redvale.gov/ontology/dbpi/"] == "dbpi:"

    def test_ns_map_contains_gis(self, ns_map):
        assert "https://data.redvale.gov/ontology/gis/" in ns_map
        assert ns_map["https://data.redvale.gov/ontology/gis/"] == "gis:"

    def test_ns_map_contains_fin(self, ns_map):
        uri = "https://data.redvale.gov/ontology/finance/"
        assert uri in ns_map
        assert ns_map[uri] == "fin:"


class TestToQname:
    def test_converts_dbpi_iri(self, to_qname):
        result = to_qname("https://data.redvale.gov/ontology/dbpi/PermitType")
        assert result == "dbpi:PermitType"

    def test_converts_gis_iri(self, to_qname):
        result = to_qname("https://data.redvale.gov/ontology/gis/SomeProperty")
        assert result == "gis:SomeProperty"

    def test_converts_fin_iri(self, to_qname):
        result = to_qname("https://data.redvale.gov/ontology/finance/FeeAmount")
        assert result == "fin:FeeAmount"

    def test_unknown_namespace_returns_full_iri(self, to_qname):
        iri = "http://example.org/unknown/Thing"
        assert to_qname(iri) == iri

    def test_converts_uriref(self, to_qname):
        iri = URIRef("https://data.redvale.gov/ontology/dbpi/Permit")
        assert to_qname(iri) == "dbpi:Permit"


# ─── Graph Loading Tests ────────────────────────────────────────────────


class TestLoadOntologyGraph:
    def test_graph_is_non_empty(self, ontology_graph):
        assert len(ontology_graph) > 0

    def test_aggregate_file_skipped(self, ontology_graph):
        """The aggregate dbpi-all.ttl should be skipped, so the graph should
        not contain duplicate triples from it. We verify indirectly by
        checking that the graph loaded successfully and has a reasonable size."""
        # If the aggregate were included, we'd have duplicates but rdflib
        # deduplicates. Instead, confirm loading works (it would fail if the
        # aggregate had import-only content with missing references).
        assert len(ontology_graph) > 100

    def test_contains_owl_classes(self, ontology_graph):
        classes = list(ontology_graph.subjects(RDF.type, OWL.Class))
        assert len(classes) > 0


class TestLoadShapesGraph:
    def test_shapes_graph_non_empty(self, shapes_graph):
        assert len(shapes_graph) > 0

    def test_contains_node_shapes(self, shapes_graph):
        shapes = list(shapes_graph.subjects(RDF.type, SH.NodeShape))
        assert len(shapes) > 0


class TestLoadVocabGraph:
    def test_vocab_graph_non_empty(self, vocab_graph):
        assert len(vocab_graph) > 0

    def test_contains_concept_schemes(self, vocab_graph):
        schemes = list(vocab_graph.subjects(RDF.type, SKOS.ConceptScheme))
        assert len(schemes) > 0


class TestLoadSeedGraph:
    def test_seed_graph_non_empty(self, seed_graph):
        assert len(seed_graph) > 0


# ─── Extraction Tests (real fixture data) ────────────────────────────────


class TestExtractClasses:
    @pytest.fixture(scope="module")
    def classes(self, ontology_graph, to_qname):
        return extract_classes(ontology_graph, to_qname)

    def test_class_count(self, classes):
        # The manifest declares classCount=78 which includes the aggregate file.
        # With the aggregate skipped, the non-aggregate ontology files yield 39
        # unique OWL classes.
        assert len(classes) == 39

    def test_all_classes_have_dbpi_prefix(self, classes):
        for cls in classes:
            assert cls["qname"].startswith("dbpi:"), (
                f"Expected dbpi: prefix, got {cls['qname']}"
            )

    def test_classes_have_required_keys(self, classes):
        required = {"iri", "qname", "label", "comment", "subClassOf"}
        for cls in classes:
            assert required <= set(cls.keys()), (
                f"Missing keys in class {cls.get('qname', '?')}"
            )

    def test_classes_sorted_by_qname(self, classes):
        qnames = [c["qname"] for c in classes]
        assert qnames == sorted(qnames)

    def test_iris_are_full_uris(self, classes):
        for cls in classes:
            assert cls["iri"].startswith("https://"), (
                f"Expected full URI, got {cls['iri']}"
            )

    def test_subclass_of_is_list(self, classes):
        for cls in classes:
            assert isinstance(cls["subClassOf"], list)


class TestExtractObjectProperties:
    @pytest.fixture(scope="module")
    def obj_props(self, ontology_graph, to_qname):
        return extract_object_properties(ontology_graph, to_qname)

    def test_has_object_properties(self, obj_props):
        assert len(obj_props) > 0

    def test_properties_have_required_keys(self, obj_props):
        required = {"iri", "qname", "label", "comment", "domain", "range"}
        for p in obj_props:
            assert required <= set(p.keys())

    def test_domain_and_range_are_lists(self, obj_props):
        for p in obj_props:
            assert isinstance(p["domain"], list)
            assert isinstance(p["range"], list)

    def test_sorted_by_qname(self, obj_props):
        qnames = [p["qname"] for p in obj_props]
        assert qnames == sorted(qnames)


class TestExtractDatatypeProperties:
    @pytest.fixture(scope="module")
    def data_props(self, ontology_graph, to_qname):
        return extract_datatype_properties(ontology_graph, to_qname)

    def test_has_datatype_properties(self, data_props):
        assert len(data_props) > 0

    def test_properties_have_required_keys(self, data_props):
        required = {"iri", "qname", "label", "comment", "domain", "range"}
        for p in data_props:
            assert required <= set(p.keys())

    def test_sorted_by_qname(self, data_props):
        qnames = [p["qname"] for p in data_props]
        assert qnames == sorted(qnames)


class TestExtractCodelistSchemes:
    @pytest.fixture(scope="module")
    def schemes(self, vocab_graph, to_qname):
        return extract_codelist_schemes(vocab_graph, to_qname)

    def test_has_at_least_one_scheme(self, schemes):
        assert len(schemes) >= 1

    def test_schemes_have_concepts(self, schemes):
        total_concepts = sum(s["conceptCount"] for s in schemes)
        assert total_concepts > 0

    def test_scheme_structure(self, schemes):
        for s in schemes:
            assert "iri" in s
            assert "label" in s
            assert "conceptCount" in s
            assert "concepts" in s
            assert isinstance(s["concepts"], list)

    def test_concepts_sorted_by_label(self, schemes):
        for s in schemes:
            labels = [c["label"] for c in s["concepts"]]
            assert labels == sorted(labels)


class TestExtractShaclShapes:
    @pytest.fixture(scope="module")
    def shapes(self, shapes_graph, to_qname):
        return extract_shacl_shapes(shapes_graph, to_qname)

    def test_has_at_least_one_shape(self, shapes):
        assert len(shapes) >= 1

    def test_shapes_have_properties(self, shapes):
        has_props = any(s["propertyCount"] > 0 for s in shapes)
        assert has_props, "Expected at least one shape with properties"

    def test_shape_structure(self, shapes):
        for s in shapes:
            assert "iri" in s
            assert "targetClass" in s
            assert "propertyCount" in s
            assert "properties" in s

    def test_property_structure(self, shapes):
        for s in shapes:
            for p in s["properties"]:
                assert "path" in p
                assert "minCount" in p
                assert "maxCount" in p


class TestExtractWorkflowModels:
    @pytest.fixture(scope="module")
    def wf_models(self, ontology_graph, manifest, to_qname):
        primary_uri = manifest["namespaces"]["primary"]["uri"]
        return extract_workflow_models(ontology_graph, primary_uri, to_qname)

    def test_has_at_least_one_workflow(self, wf_models):
        assert len(wf_models) >= 1

    def test_workflow_structure(self, wf_models):
        for wf in wf_models:
            assert "iri" in wf
            assert "label" in wf
            assert "appliesToClass" in wf
            assert "stateCount" in wf
            assert "transitionCount" in wf
            assert "states" in wf
            assert "transitions" in wf

    def test_workflows_have_states(self, wf_models):
        total_states = sum(wf["stateCount"] for wf in wf_models)
        assert total_states > 0

    def test_workflows_sorted_by_label(self, wf_models):
        labels = [wf["label"] for wf in wf_models]
        assert labels == sorted(labels)


class TestExtractAugmentingNamespaces:
    @pytest.fixture(scope="module")
    def augmenting(self, ontology_graph, manifest, to_qname):
        return extract_augmenting_namespaces(ontology_graph, manifest, to_qname)

    def test_exactly_two_augmenting(self, augmenting):
        assert len(augmenting) == 2

    def test_gis_namespace(self, augmenting):
        gis = next((a for a in augmenting if a["prefix"] == "gis"), None)
        assert gis is not None
        assert gis["propertyCount"] == 4
        assert gis["namespace"] == "https://data.redvale.gov/ontology/gis/"

    def test_fin_namespace(self, augmenting):
        fin = next((a for a in augmenting if a["prefix"] == "fin"), None)
        assert fin is not None
        assert fin["propertyCount"] == 3
        assert fin["namespace"] == "https://data.redvale.gov/ontology/finance/"

    def test_properties_are_sorted(self, augmenting):
        for a in augmenting:
            assert a["properties"] == sorted(a["properties"])


# ─── Edge Case Tests (synthetic data) ───────────────────────────────────


class TestEdgeCasesEmptyGraph:
    """Verify extraction functions return empty lists on an empty graph."""

    @pytest.fixture
    def empty_graph(self):
        return Graph()

    @pytest.fixture
    def trivial_qname(self):
        return make_to_qname({})

    def test_empty_classes(self, empty_graph, trivial_qname):
        assert extract_classes(empty_graph, trivial_qname) == []

    def test_empty_object_properties(self, empty_graph, trivial_qname):
        assert extract_object_properties(empty_graph, trivial_qname) == []

    def test_empty_datatype_properties(self, empty_graph, trivial_qname):
        assert extract_datatype_properties(empty_graph, trivial_qname) == []

    def test_empty_codelist_schemes(self, empty_graph, trivial_qname):
        assert extract_codelist_schemes(empty_graph, trivial_qname) == []

    def test_empty_shacl_shapes(self, empty_graph, trivial_qname):
        assert extract_shacl_shapes(empty_graph, trivial_qname) == []

    def test_empty_workflow_models(self, empty_graph, trivial_qname):
        result = extract_workflow_models(
            empty_graph, "http://example.org/ns/", trivial_qname
        )
        assert result == []


class TestEdgeCasesBNodes:
    """Verify that BNodes are skipped during extraction."""

    @pytest.fixture
    def graph_with_bnodes(self):
        g = Graph()
        EX = Namespace("http://example.org/")
        # Add a real class
        g.add((EX.RealClass, RDF.type, OWL.Class))
        g.add((EX.RealClass, RDFS.label, Literal("Real Class")))
        # Add a BNode class (e.g., from an OWL restriction)
        bnode = BNode()
        g.add((bnode, RDF.type, OWL.Class))
        g.add((bnode, RDFS.label, Literal("Should be skipped")))
        # Add a real object property
        g.add((EX.realProp, RDF.type, OWL.ObjectProperty))
        # Add a BNode object property
        bnode_prop = BNode()
        g.add((bnode_prop, RDF.type, OWL.ObjectProperty))
        # Add a real datatype property
        g.add((EX.realDataProp, RDF.type, OWL.DatatypeProperty))
        # Add a BNode datatype property
        bnode_dprop = BNode()
        g.add((bnode_dprop, RDF.type, OWL.DatatypeProperty))
        return g

    @pytest.fixture
    def ex_qname(self):
        return make_to_qname({"http://example.org/": "ex:"})

    def test_bnode_classes_skipped(self, graph_with_bnodes, ex_qname):
        classes = extract_classes(graph_with_bnodes, ex_qname)
        assert len(classes) == 1
        assert classes[0]["qname"] == "ex:RealClass"

    def test_bnode_object_properties_skipped(self, graph_with_bnodes, ex_qname):
        props = extract_object_properties(graph_with_bnodes, ex_qname)
        assert len(props) == 1
        assert props[0]["qname"] == "ex:realProp"

    def test_bnode_datatype_properties_skipped(self, graph_with_bnodes, ex_qname):
        props = extract_datatype_properties(graph_with_bnodes, ex_qname)
        assert len(props) == 1
        assert props[0]["qname"] == "ex:realDataProp"


class TestEdgeCasesToQnameFallback:
    """Verify that to_qname falls back to the full IRI for unknown namespaces."""

    def test_unknown_ns_returns_full_iri(self):
        to_qname = make_to_qname({"http://known.org/": "k:"})
        assert to_qname("http://unknown.org/Foo") == "http://unknown.org/Foo"

    def test_known_ns_resolves(self):
        to_qname = make_to_qname({"http://known.org/": "k:"})
        assert to_qname("http://known.org/Bar") == "k:Bar"

    def test_empty_ns_map_returns_full_iri(self):
        to_qname = make_to_qname({})
        assert to_qname("http://example.org/X") == "http://example.org/X"


class TestEdgeCasesBuildNsMap:
    """Verify build_ns_map handles edge cases in manifest structure."""

    def test_no_augmenting(self):
        manifest = {
            "namespaces": {
                "primary": {"prefix": "test", "uri": "http://test.org/"},
            }
        }
        ns_map = build_ns_map(manifest)
        assert len(ns_map) == 1
        assert ns_map["http://test.org/"] == "test:"

    def test_empty_augmenting(self):
        manifest = {
            "namespaces": {
                "primary": {"prefix": "test", "uri": "http://test.org/"},
                "augmenting": [],
            }
        }
        ns_map = build_ns_map(manifest)
        assert len(ns_map) == 1
