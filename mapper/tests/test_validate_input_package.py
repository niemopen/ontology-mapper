#!/usr/bin/env python3
"""Tests for validate_input_package.py"""

from pathlib import Path

import pytest
from ontology_mapper.validate_input_package import (
    validate_input_package,
    find_rdf_files,
    format_findings,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

MINIMAL_ONTOLOGY = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/> .

ex:Person a owl:Class ;
    rdfs:label "Person" .

ex:name a owl:DatatypeProperty ;
    rdfs:domain ex:Person ;
    rdfs:label "name" .
"""

CLASSES_ONLY = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <http://example.org/> .

ex:Person a owl:Class .
ex:Organization a owl:Class .
"""

PROPERTIES_ONLY = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <http://example.org/> .

ex:name a owl:DatatypeProperty .
ex:knows a owl:ObjectProperty .
"""

RDFS_CLASSES = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/> .

ex:Widget a rdfs:Class .
ex:color a rdf:Property .
"""

INVALID_TTL = "this is not valid turtle @@ syntax {{"


def write_file(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


# ═══════════════════════════════════════════════════════════════════════════
# IV-010: Directory checks
# ═══════════════════════════════════════════════════════════════════════════

class TestDirectoryChecks:
    def test_nonexistent_directory(self, tmp_path):
        findings = validate_input_package(tmp_path / "does_not_exist")
        assert len(findings) == 1
        assert findings[0]["code"] == "IV-010"
        assert findings[0]["severity"] == "error"

    def test_path_is_file_not_dir(self, tmp_path):
        f = tmp_path / "notadir.txt"
        f.write_text("hello")
        findings = validate_input_package(f)
        assert len(findings) == 1
        assert findings[0]["code"] == "IV-010"
        assert "not a directory" in findings[0]["message"]

    def test_empty_directory(self, tmp_path):
        empty = tmp_path / "empty_pkg"
        empty.mkdir()
        findings = validate_input_package(empty)
        assert len(findings) == 1
        assert findings[0]["code"] == "IV-010"
        assert "empty" in findings[0]["message"]


# ═══════════════════════════════════════════════════════════════════════════
# IV-020: RDF file checks
# ═══════════════════════════════════════════════════════════════════════════

class TestRdfFileChecks:
    def test_no_rdf_files(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "readme.md").write_text("Just docs")
        (pkg / "data.csv").write_text("a,b,c")
        findings = validate_input_package(pkg)
        assert any(f["code"] == "IV-020" for f in findings)
        assert any(f["severity"] == "error" for f in findings)

    def test_only_unparseable_rdf(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "bad.ttl", INVALID_TTL)
        findings = validate_input_package(pkg)
        errors = [f for f in findings if f["code"] == "IV-020" and f["severity"] == "error"]
        assert len(errors) == 1
        assert "none could be parsed" in errors[0]["detail"]

    def test_some_unparseable_some_good(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "good.ttl", MINIMAL_ONTOLOGY)
        write_file(pkg, "bad.ttl", INVALID_TTL)
        findings = validate_input_package(pkg)
        # bad.ttl should be a warning, not a blocker
        warnings = [f for f in findings if f["code"] == "IV-020" and f["severity"] == "warning"]
        assert len(warnings) == 1
        assert "bad.ttl" in warnings[0]["message"]
        # No IV-020 errors since good.ttl parsed
        errors = [f for f in findings if f["code"] == "IV-020" and f["severity"] == "error"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# IV-030: Class definition checks
# ═══════════════════════════════════════════════════════════════════════════

class TestClassChecks:
    def test_no_classes(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "props.ttl", PROPERTIES_ONLY)
        findings = validate_input_package(pkg)
        assert any(f["code"] == "IV-030" for f in findings)

    def test_owl_classes_found(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "ont.ttl", MINIMAL_ONTOLOGY)
        findings = validate_input_package(pkg)
        assert not any(f["code"] == "IV-030" for f in findings)

    def test_rdfs_classes_accepted(self, tmp_path):
        """rdfs:Class declarations should satisfy IV-030."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "ont.ttl", RDFS_CLASSES)
        findings = validate_input_package(pkg)
        assert not any(f["code"] == "IV-030" for f in findings)


# ═══════════════════════════════════════════════════════════════════════════
# IV-040: Property definition checks
# ═══════════════════════════════════════════════════════════════════════════

class TestPropertyChecks:
    def test_no_properties(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "ont.ttl", CLASSES_ONLY)
        findings = validate_input_package(pkg)
        assert any(f["code"] == "IV-040" for f in findings)

    def test_object_properties_found(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "ont.ttl", MINIMAL_ONTOLOGY)
        findings = validate_input_package(pkg)
        assert not any(f["code"] == "IV-040" for f in findings)


# ═══════════════════════════════════════════════════════════════════════════
# Full validation — clean package
# ═══════════════════════════════════════════════════════════════════════════

class TestCleanPackage:
    def test_minimal_valid_package(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        write_file(pkg, "ontology.ttl", MINIMAL_ONTOLOGY)
        findings = validate_input_package(pkg)
        errors = [f for f in findings if f["severity"] == "error"]
        assert len(errors) == 0

    def test_nested_rdf_files(self, tmp_path):
        """RDF files in subdirectories should be found."""
        pkg = tmp_path / "pkg"
        (pkg / "ontology").mkdir(parents=True)
        write_file(pkg / "ontology", "core.ttl", MINIMAL_ONTOLOGY)
        findings = validate_input_package(pkg)
        errors = [f for f in findings if f["severity"] == "error"]
        assert len(errors) == 0

    def test_real_package(self):
        """Validate the actual example domain package."""
        pkg = Path(__file__).parent / "fixtures" / "redvale_dbpi_agency_package"
        if not pkg.exists():
            pytest.skip("Example domain package not available")
        findings = validate_input_package(pkg)
        errors = [f for f in findings if f["severity"] == "error"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# find_rdf_files
# ═══════════════════════════════════════════════════════════════════════════

class TestFindRdfFiles:
    def test_finds_multiple_formats(self, tmp_path):
        write_file(tmp_path, "a.ttl", "")
        write_file(tmp_path, "b.owl", "")
        write_file(tmp_path, "c.jsonld", "")
        write_file(tmp_path, "d.txt", "")
        found = find_rdf_files(tmp_path)
        names = {f.name for f in found}
        assert names == {"a.ttl", "b.owl", "c.jsonld"}

    def test_case_insensitive_extensions(self, tmp_path):
        write_file(tmp_path, "upper.TTL", "")
        found = find_rdf_files(tmp_path)
        assert len(found) == 1


# ═══════════════════════════════════════════════════════════════════════════
# format_findings
# ═══════════════════════════════════════════════════════════════════════════

class TestFormatFindings:
    def test_empty_findings(self):
        result = format_findings([])
        assert "all checks passed" in result

    def test_error_formatting(self):
        findings = [{
            "code": "IV-010",
            "severity": "error",
            "message": "Directory does not exist",
            "detail": "/some/path",
        }]
        result = format_findings(findings)
        assert "IV-010" in result
        assert "[X]" in result
        assert "cannot proceed" in result.lower()

    def test_warning_formatting(self):
        findings = [{
            "code": "IV-020",
            "severity": "warning",
            "message": "Parse warning",
            "detail": "Some detail",
        }]
        result = format_findings(findings)
        assert "[!]" in result
        assert "0 error(s)" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
