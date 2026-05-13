"""Tests for ontology_mapper.build_package_manifest."""

import textwrap
from pathlib import Path

import pytest

from ontology_mapper.build_package_manifest import (
    analyze_namespaces,
    build_manifest,
    classify_ttl_file,
    infer_org_source,
)


FIXTURE_PKG = Path(__file__).parent / "fixtures" / "redvale_dbpi_agency_package"


# ─── classify_ttl_file ──────────────────────────────────────────────────


class TestClassifyTtlFile:
    """Tests for classify_ttl_file against synthetic TTL content."""

    def _write(self, tmp_path, content, name="test.ttl"):
        p = tmp_path / name
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    def test_ontology_with_classes(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix ex: <https://example.org/ont/> .

            ex:Person a owl:Class .
            ex:Organization a owl:Class .
        """)
        r = classify_ttl_file(path)
        assert r["classification"] == "ontology"
        assert r["class_count"] == 2
        assert "owl:Class" in r["signals"]
        assert r["error"] is None

    def test_ontology_with_properties(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix ex: <https://example.org/ont/> .

            ex:hasName a owl:DatatypeProperty .
            ex:knows a owl:ObjectProperty .
        """)
        r = classify_ttl_file(path)
        assert r["classification"] == "ontology"
        assert "owl:Property" in r["signals"]
        assert r["class_count"] == 0

    def test_shapes_file(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix ex: <https://example.org/shapes/> .

            ex:PersonShape a sh:NodeShape ;
                sh:targetClass <https://example.org/ont/Person> .
        """)
        r = classify_ttl_file(path)
        assert r["classification"] == "shapes"
        assert "sh:NodeShape" in r["signals"]

    def test_vocab_file(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix ex: <https://example.org/vocab/> .

            ex:StatusScheme a skos:ConceptScheme ;
                skos:prefLabel "Status codes" .
        """)
        r = classify_ttl_file(path)
        assert r["classification"] == "vocab"
        assert "skos:ConceptScheme" in r["signals"]

    def test_seed_data(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix ex: <https://example.org/ont/> .
            @prefix inst: <https://example.org/data/> .

            inst:alice a ex:Person ;
                ex:hasName "Alice" .
        """)
        r = classify_ttl_file(path)
        assert r["classification"] == "seed-data"
        assert "instances" in r["signals"]

    def test_aggregate_with_imports(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

            <https://example.org/ont/all> a owl:Ontology ;
                owl:imports <https://example.org/ont/core> ;
                owl:imports <https://example.org/ont/ext> .
        """)
        r = classify_ttl_file(path)
        assert r["classification"] == "aggregate"
        assert "owl:imports" in r["signals"]

    def test_ontology_with_imports_stays_ontology(self, tmp_path):
        """A file with owl:imports AND classes should be 'ontology', not 'aggregate'."""
        path = self._write(tmp_path, """\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix ex: <https://example.org/ont/> .

            ex:all a owl:Ontology ;
                owl:imports <https://example.org/ont/core> .

            ex:Widget a owl:Class .
        """)
        r = classify_ttl_file(path)
        assert r["classification"] == "ontology"
        assert "owl:imports" in r["signals"]
        assert "owl:Class" in r["signals"]

    def test_parse_error(self, tmp_path):
        path = self._write(tmp_path, "this is not valid turtle {{{")
        r = classify_ttl_file(path)
        assert r["classification"] == "parse-error"
        assert r["error"] is not None

    def test_empty_file(self, tmp_path):
        path = self._write(tmp_path, "")
        r = classify_ttl_file(path)
        assert r["classification"] == "unknown"
        assert r["signals"] == []

    def test_prefixes_extracted(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix myns: <https://example.org/myns/> .

            myns:Foo a owl:Class .
        """)
        r = classify_ttl_file(path)
        assert "myns" in r["prefixes"]
        assert r["prefixes"]["myns"] == "https://example.org/myns/"

    def test_class_namespaces_counted(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix a: <https://example.org/a/> .
            @prefix b: <https://example.org/b/> .

            a:X a owl:Class .
            a:Y a owl:Class .
            b:Z a owl:Class .
        """)
        r = classify_ttl_file(path)
        assert r["class_namespaces"]["https://example.org/a/"] == 2
        assert r["class_namespaces"]["https://example.org/b/"] == 1

    def test_property_namespaces_counted(self, tmp_path):
        path = self._write(tmp_path, """\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix a: <https://example.org/a/> .

            a:X a owl:Class .
            a:hasFoo a owl:ObjectProperty .
            a:barValue a owl:DatatypeProperty .
        """)
        r = classify_ttl_file(path)
        assert r["property_namespaces"]["https://example.org/a/"] == 2


# ─── analyze_namespaces ─────────────────────────────────────────────────


class TestAnalyzeNamespaces:
    """Tests for analyze_namespaces with synthetic file_results dicts."""

    def test_primary_is_most_classes(self):
        results = [
            {
                "class_namespaces": {
                    "https://example.org/a/": 5,
                    "https://example.org/b/": 2,
                },
                "property_namespaces": {},
                "prefixes": {
                    "a": "https://example.org/a/",
                    "b": "https://example.org/b/",
                },
            },
        ]
        primary, augmenting, _ = analyze_namespaces(results)
        assert primary["prefix"] == "a"
        assert primary["uri"] == "https://example.org/a/"
        assert primary["classCount"] == 5
        assert len(augmenting) == 1
        assert augmenting[0]["prefix"] == "b"
        assert augmenting[0]["classCount"] == 2

    def test_no_classes_returns_none(self):
        results = [{"class_namespaces": {}, "property_namespaces": {}, "prefixes": {}}]
        primary, augmenting, _ = analyze_namespaces(results)
        assert primary is None
        assert augmenting == []

    def test_well_known_prefixes_filtered(self):
        results = [
            {
                "class_namespaces": {
                    "https://example.org/main/": 10,
                    "http://www.w3.org/2002/07/owl#": 1,
                },
                "property_namespaces": {},
                "prefixes": {
                    "main": "https://example.org/main/",
                    "owl": "http://www.w3.org/2002/07/owl#",
                },
            },
        ]
        primary, augmenting, _ = analyze_namespaces(results)
        assert primary["prefix"] == "main"
        # owl should not appear in augmenting
        aug_uris = [a["uri"] for a in augmenting]
        assert "http://www.w3.org/2002/07/owl#" not in aug_uris

    def test_rdflib_auto_prefixes_filtered(self):
        results = [
            {
                "class_namespaces": {
                    "https://example.org/main/": 10,
                },
                "property_namespaces": {
                    "https://example.org/schema-auto/": 3,
                },
                "prefixes": {
                    "main": "https://example.org/main/",
                    "schema": "https://example.org/schema-auto/",
                },
            },
        ]
        primary, augmenting, _ = analyze_namespaces(results)
        # "schema" is in rdflib_auto_prefixes, so it should be filtered
        aug_prefixes = [a["prefix"] for a in augmenting]
        assert "schema" not in aug_prefixes

    def test_property_only_augmenting_ns(self):
        """A namespace with only properties (no classes) should still appear as augmenting."""
        results = [
            {
                "class_namespaces": {"https://example.org/main/": 5},
                "property_namespaces": {"https://example.org/ext/": 3},
                "prefixes": {
                    "main": "https://example.org/main/",
                    "ext": "https://example.org/ext/",
                },
            },
        ]
        primary, augmenting, _ = analyze_namespaces(results)
        assert len(augmenting) == 1
        assert augmenting[0]["prefix"] == "ext"
        assert augmenting[0]["classCount"] == 0
        assert augmenting[0]["propertyCount"] == 3

    def test_aggregates_across_multiple_files(self):
        results = [
            {
                "class_namespaces": {"https://example.org/ns/": 3},
                "property_namespaces": {},
                "prefixes": {"ns": "https://example.org/ns/"},
            },
            {
                "class_namespaces": {"https://example.org/ns/": 7},
                "property_namespaces": {},
                "prefixes": {"ns": "https://example.org/ns/"},
            },
        ]
        primary, _, _ = analyze_namespaces(results)
        assert primary["classCount"] == 10

    def test_all_prefixes_returned(self):
        results = [
            {
                "class_namespaces": {"https://example.org/main/": 1},
                "property_namespaces": {},
                "prefixes": {
                    "main": "https://example.org/main/",
                    "extra": "https://example.org/extra/",
                },
            },
        ]
        _, _, all_prefixes = analyze_namespaces(results)
        assert all_prefixes["https://example.org/main/"] == "main"
        assert all_prefixes["https://example.org/extra/"] == "extra"


# ─── infer_org_source ───────────────────────────────────────────────────


class TestInferOrgSource:
    """Tests for infer_org_source URI pattern matching."""

    def test_pattern1_data_gov(self):
        org, source, conf = infer_org_source("https://data.redvale.gov/ontology/dbpi/")
        assert org == "redvale"
        assert source == "dbpi"
        assert conf == "high"

    def test_pattern2_org_tld(self):
        org, source, conf = infer_org_source("https://sali.org/ontology/folio/")
        assert org == "sali"
        assert source == "folio"
        assert conf == "high"

    def test_pattern3_simple(self):
        org, source, conf = infer_org_source("https://acme.com/widgets/")
        assert org == "acme"
        assert source == "widgets"
        assert conf == "medium"

    def test_empty_returns_none(self):
        org, source, conf = infer_org_source("")
        assert org is None
        assert source is None
        assert conf == "none"

    def test_none_returns_none(self):
        org, source, conf = infer_org_source(None)
        assert org is None
        assert source is None
        assert conf == "none"

    def test_trailing_hash_stripped(self):
        org, source, conf = infer_org_source("https://data.city.gov/ontology/transit#")
        assert org == "city"
        assert source == "transit"
        assert conf == "high"

    def test_http_also_works(self):
        org, source, conf = infer_org_source("http://data.county.gov/ontology/parks/")
        assert org == "county"
        assert source == "parks"
        assert conf == "high"


# ─── build_manifest (integration against Redvale fixture) ───────────────


class TestBuildManifestRedvaleFixture:
    """Integration tests for build_manifest against the Redvale fixture package."""

    @pytest.fixture(scope="class")
    def manifest_result(self):
        manifest, warnings, needs_input = build_manifest(str(FIXTURE_PKG))
        return manifest, warnings, needs_input

    def test_manifest_not_none(self, manifest_result):
        manifest, _, _ = manifest_result
        assert manifest is not None

    def test_no_needs_input(self, manifest_result):
        _, _, needs_input = manifest_result
        assert needs_input == {}

    def test_package_name(self, manifest_result):
        manifest, _, _ = manifest_result
        assert manifest["packageName"] == "redvale_dbpi_agency_package"

    def test_primary_namespace(self, manifest_result):
        manifest, _, _ = manifest_result
        primary = manifest["namespaces"]["primary"]
        assert primary["prefix"] == "dbpi"
        assert primary["uri"] == "https://data.redvale.gov/ontology/dbpi/"
        assert primary["classCount"] == 78

    def test_augmenting_namespaces(self, manifest_result):
        manifest, _, _ = manifest_result
        augmenting = manifest["namespaces"]["augmenting"]
        assert len(augmenting) == 2
        aug_by_prefix = {a["prefix"]: a for a in augmenting}
        assert "gis" in aug_by_prefix
        assert aug_by_prefix["gis"]["propertyCount"] == 4
        assert "fin" in aug_by_prefix
        assert aug_by_prefix["fin"]["propertyCount"] == 3

    def test_org_and_source(self, manifest_result):
        manifest, _, _ = manifest_result
        assert manifest["organization"] == "redvale"
        assert manifest["source"] == "dbpi"
        assert manifest["orgDomainConfidence"] == "high"

    def test_file_counts(self, manifest_result):
        manifest, _, _ = manifest_result
        stats = manifest["stats"]
        assert stats["totalFiles"] == 13
        assert stats["ontologyFiles"] == 8
        assert stats["shapeFiles"] == 1
        assert stats["vocabFiles"] == 1
        assert stats["seedDataFiles"] == 2
        assert stats["aggregateFiles"] == 1

    def test_ontology_files_list(self, manifest_result):
        manifest, _, _ = manifest_result
        ont_files = manifest["files"]["ontology"]
        assert len(ont_files) == 8
        # The aggregate should NOT be in the ontology list
        assert "ontology/dbpi-all.ttl" not in ont_files
        assert "ontology/dbpi-core.ttl" in ont_files

    def test_aggregate_files_list(self, manifest_result):
        manifest, _, _ = manifest_result
        assert manifest["files"]["aggregate"] == ["ontology/dbpi-all.ttl"]

    def test_shapes_files_list(self, manifest_result):
        manifest, _, _ = manifest_result
        assert manifest["files"]["shapes"] == ["shapes/dbpi-shapes.ttl"]

    def test_vocab_files_list(self, manifest_result):
        manifest, _, _ = manifest_result
        assert manifest["files"]["vocab"] == ["vocab/dbpi-codelists.ttl"]

    def test_seed_data_files_list(self, manifest_result):
        manifest, _, _ = manifest_result
        assert sorted(manifest["files"]["seedData"]) == [
            "seed-data/corpus/dbpi-seed-corpus.ttl",
            "seed-data/dbpi-seed-data.ttl",
        ]

    def test_no_unknown_or_parse_errors(self, manifest_result):
        manifest, _, _ = manifest_result
        assert manifest["files"]["unknown"] == []
        assert manifest["files"]["parseError"] == []

    def test_prefix_map(self, manifest_result):
        manifest, _, _ = manifest_result
        pm = manifest["namespaces"]["prefixMap"]
        assert pm["https://data.redvale.gov/ontology/dbpi/"] == "dbpi:"
        assert pm["https://data.redvale.gov/ontology/gis/"] == "gis:"
        assert pm["https://data.redvale.gov/ontology/finance/"] == "fin:"

    def test_no_warnings_about_missing_categories(self, manifest_result):
        """The fixture has all categories, so no 'No X detected' warnings."""
        _, warnings, _ = manifest_result
        assert not any("No ontology files" in w for w in warnings)
        assert not any("No SHACL shape files" in w for w in warnings)
        assert not any("No SKOS vocabulary files" in w for w in warnings)


class TestBuildManifestEdgeCases:
    """Edge-case tests for build_manifest."""

    def test_nonexistent_dir(self):
        manifest, warnings, needs_input = build_manifest("/nonexistent/path")
        assert manifest is None
        assert len(warnings) > 0
        assert "package_dir" in needs_input

    def test_empty_dir(self, tmp_path):
        manifest, warnings, _ = build_manifest(str(tmp_path))
        assert manifest is None
        assert any("No TTL files" in w for w in warnings)

    def test_dir_with_only_parse_errors(self, tmp_path):
        bad = tmp_path / "broken.ttl"
        bad.write_text("not valid {{{", encoding="utf-8")
        manifest, warnings, needs_input = build_manifest(str(tmp_path))
        assert manifest is not None
        assert manifest["files"]["parseError"] == ["broken.ttl"]
        assert manifest["stats"]["totalFiles"] == 1
        # No classes found, so primary namespace should be None
        assert manifest["namespaces"]["primary"] is None
        assert "primary_namespace" in needs_input

    def test_single_ontology_file(self, tmp_path):
        f = tmp_path / "core.ttl"
        f.write_text(textwrap.dedent("""\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix ex: <https://example.org/test/> .

            ex:Thing a owl:Class .
        """), encoding="utf-8")
        manifest, warnings, needs_input = build_manifest(str(tmp_path))
        assert manifest is not None
        assert manifest["namespaces"]["primary"]["classCount"] == 1
        assert manifest["stats"]["ontologyFiles"] == 1
        assert manifest["files"]["ontology"] == ["core.ttl"]
