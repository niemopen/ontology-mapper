#!/usr/bin/env python3
"""Tests for generate_edge_ontology.py — pure helpers and OWL pattern rules."""

import pytest

from ontology_mapper.generate_edge_ontology import (
    xsd_qname, local_name, edge_class_name,
    infer_domains_from_shapes, assign_properties_to_classes,
    detect_consolidations,
)


# ---------------------------------------------------------------------------
# TestXsdQname
# ---------------------------------------------------------------------------
class TestXsdQname:
    def test_full_iri_string(self):
        assert xsd_qname("http://www.w3.org/2001/XMLSchema#string") == "xsd:string"

    def test_full_iri_date(self):
        assert xsd_qname("http://www.w3.org/2001/XMLSchema#date") == "xsd:date"

    def test_full_iri_integer(self):
        assert xsd_qname("http://www.w3.org/2001/XMLSchema#integer") == "xsd:integer"

    def test_xs_prefix_string(self):
        assert xsd_qname("xs:string") == "xsd:string"

    def test_xs_prefix_date(self):
        assert xsd_qname("xs:date") == "xsd:date"

    def test_xs_prefix_boolean(self):
        assert xsd_qname("xs:boolean") == "xsd:boolean"

    def test_xs_prefix_decimal(self):
        assert xsd_qname("xs:decimal") == "xsd:decimal"

    def test_already_xsd_prefix(self):
        # xsd:string doesn't start with XSD IRI or xs:, passes through
        assert xsd_qname("xsd:string") == "xsd:string"

    def test_non_xsd_iri(self):
        assert xsd_qname("http://example.org/MyType") == "http://example.org/MyType"

    def test_none(self):
        assert xsd_qname(None) is None

    def test_empty_string(self):
        assert xsd_qname("") == ""

    def test_skos_concept(self):
        assert xsd_qname("skos:Concept") == "skos:Concept"


# ---------------------------------------------------------------------------
# TestLocalName
# ---------------------------------------------------------------------------
class TestLocalName:
    def test_qname(self):
        assert local_name("nc:PersonType") == "PersonType"

    def test_hash_iri(self):
        assert local_name("http://example.org/ns#Foo") == "Foo"

    def test_slash_iri(self):
        assert local_name("http://example.org/ns/Foo") == "Foo"

    def test_no_separator(self):
        assert local_name("Foo") == "Foo"


# ---------------------------------------------------------------------------
# TestEdgeClassName
# ---------------------------------------------------------------------------
class TestEdgeClassName:
    def test_appends_type(self):
        assert edge_class_name("dbpi:Permit") == "PermitType"

    def test_already_has_type_suffix(self):
        # It always appends Type — this is by design
        assert edge_class_name("nc:PersonType") == "PersonTypeType"


# ---------------------------------------------------------------------------
# TestDetectConsolidations
# ---------------------------------------------------------------------------
class TestDetectConsolidations:
    def test_excludes_are_candidates(self):
        matrix = {"mappings": [
            {"sourceConcept": "src:A", "action": "exclude"},
            {"sourceConcept": "src:B", "action": "exclude"},
            {"sourceConcept": "src:C", "action": "reuse"},
        ]}
        class_by_qname = {
            "src:A": {"qname": "src:A", "subClassOf": ["src:Parent"]},
            "src:B": {"qname": "src:B", "subClassOf": ["src:Parent"]},
            "src:C": {"qname": "src:C", "subClassOf": []},
        }
        cons = detect_consolidations(matrix, class_by_qname)
        assert len(cons) == 1
        assert cons[0][0] == "src:Parent"

    def test_non_exclude_ignored(self):
        matrix = {"mappings": [
            {"sourceConcept": "src:A", "action": "reuse"},
        ]}
        assert detect_consolidations(matrix, {"src:A": {"qname": "src:A"}}) == []


# ---------------------------------------------------------------------------
# TestAssignProperties
# ---------------------------------------------------------------------------
class TestAssignProperties:
    def test_explicit_domain_assigned(self):
        props = [{"qname": "src:prop1", "domain": ["src:ClassA"]}]
        active = {"src:ClassA"}
        assigned, unassigned = assign_properties_to_classes(props, active, {})
        assert "src:prop1" in assigned
        assert assigned["src:prop1"] == ["src:ClassA"]

    def test_shape_fallback(self):
        props = [{"qname": "src:prop1", "domain": []}]
        active = {"src:ClassA"}
        shape_domains = {"src:prop1": {"src:ClassA"}}
        assigned, unassigned = assign_properties_to_classes(props, active, shape_domains)
        assert "src:prop1" in assigned

    def test_inactive_domain_not_assigned(self):
        props = [{"qname": "src:prop1", "domain": ["src:InactiveClass"]}]
        active = {"src:ClassA"}
        assigned, unassigned = assign_properties_to_classes(props, active, {})
        assert "src:prop1" not in assigned
        assert "src:prop1" in unassigned


# ---------------------------------------------------------------------------
# OWL Pattern Rule Tests — verified via main() output
# ---------------------------------------------------------------------------
class TestNiemOWLPatterns:
    """Test NIEM-specific OWL emission rules.

    These test the patterns documented in AGENTS/Target_OWL_Patterns.md
    by constructing minimal matrix data and verifying the generated TTL.
    Since the core emission functions are closures inside main(), we
    exercise them through a thin integration helper.
    """

    @staticmethod
    def _run_generation(inv, matrix, target_ontology="niem", target_version="6.0"):
        """Run generate_edge_ontology.main() with in-memory data and return file contents."""
        import json
        import tempfile
        from pathlib import Path
        from ontology_mapper.run_dir_utils import resolve_specs_dir, STATE_FILENAME

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            pkg_dir = run_dir / "edge-package"
            pkg_dir.mkdir()

            # Write inventory and matrix
            (run_dir / "concept-inventory.json").write_text(json.dumps(inv), encoding="utf-8")
            (run_dir / "mapping-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")

            # Write minimal catalog
            specs = resolve_specs_dir()
            cat_name = f"{target_ontology}_reference_catalog_{target_version}.json"
            cat_path = specs / cat_name
            catalog = {"namespaces": {"nc": f"https://docs.oasis-open.org/niemopen/ns/model/niem-core/{target_version}/"}}
            cat_existed = cat_path.exists()
            if not cat_existed:
                cat_path.write_text(json.dumps(catalog), encoding="utf-8")

            # Write mapper state directly
            state = {
                "inputs": {
                    "organization": "testorg",
                    "source": "test",
                    "target_ontology": target_ontology,
                    "target_version": target_version,
                    "input_package_path": str(tmpdir),
                },
                "run_dir": str(run_dir),
            }
            (run_dir / STATE_FILENAME).write_text(json.dumps(state), encoding="utf-8")

            try:
                from ontology_mapper.generate_edge_ontology import main
                import sys
                orig_argv = sys.argv
                sys.argv = ["om-generate-ontology",
                            "--run-dir", str(run_dir),
                            "--package-dir", str(pkg_dir)]
                try:
                    main()
                finally:
                    sys.argv = orig_argv

                # Read generated files
                result = {}
                for f in pkg_dir.rglob("*.ttl"):
                    result[f.name] = f.read_text(encoding="utf-8")
                return result
            finally:
                if not cat_existed and cat_path.exists():
                    cat_path.unlink()

    @staticmethod
    def _minimal_inventory(classes, dt_props=None, obj_props=None, shapes=None):
        return {
            "classes": classes,
            "datatypeProperties": dt_props or [],
            "objectProperties": obj_props or [],
            "shaclShapes": shapes or [],
            "codelistSchemes": [],
            "augmentingNamespaces": [],
        }

    def test_augment_emits_no_class_declaration(self):
        """NIEM augmentation is transparent in OWL — no augmentation type class."""
        inv = self._minimal_inventory([
            {"qname": "src:Foo", "label": "Foo", "comment": "", "subClassOf": []},
        ])
        matrix = {"mappings": [{
            "sourceConcept": "src:Foo",
            "action": "augment",
            "targetType": "nc:PersonType",
            "augmentationType": "PersonAugmentationType",
            "augmentsType": "nc:PersonType",
            "propertyMappings": [],
        }]}

        files = self._run_generation(inv, matrix)
        ext_ttl = files.get("test-edge-extensions.ttl", "")

        # No class declaration for augmentation type
        assert "AugmentationType" not in ext_ttl or "a owl:Class" not in ext_ttl.split("AugmentationType")[0].split("\n")[-1]
        # More precisely: no line like "ext:PersonAugmentationType" followed by "a owl:Class"
        assert "ext:PersonAugmentationType" not in ext_ttl

    def test_augment_property_has_domain_of_augmented_type(self):
        """Augmentation properties have rdfs:domain pointing to the augmented type."""
        inv = self._minimal_inventory(
            classes=[{"qname": "src:Foo", "label": "Foo", "comment": "", "subClassOf": []}],
            dt_props=[{"qname": "src:newProp", "label": "newProp", "domain": ["src:Foo"],
                       "range": ["http://www.w3.org/2001/XMLSchema#string"]}],
            shapes=[{"targetClass": "src:Foo", "properties": [
                {"path": "src:newProp", "minCount": 1, "maxCount": 1,
                 "datatype": "http://www.w3.org/2001/XMLSchema#string", "class": None}
            ]}],
        )
        matrix = {"mappings": [{
            "sourceConcept": "src:Foo",
            "action": "augment",
            "targetType": "nc:PersonType",
            "augmentationType": "PersonAugmentationType",
            "augmentsType": "nc:PersonType",
            "propertyMappings": [{
                "sourceProperty": "newProp",
                "action": "create-property",
                "reviewStatus": "accepted",
            }],
        }]}

        files = self._run_generation(inv, matrix)
        ext_ttl = files.get("test-edge-extensions.ttl", "")

        # Property should have domain = augmented type, not an augmentation type
        assert "rdfs:domain nc:PersonType" in ext_ttl

    def test_augment_reuse_property_not_emitted(self):
        """Reuse-property properties are already on the target — not re-declared."""
        inv = self._minimal_inventory(
            classes=[{"qname": "src:Foo", "label": "Foo", "comment": "", "subClassOf": []}],
            dt_props=[{"qname": "src:existingProp", "label": "existingProp",
                       "domain": ["src:Foo"],
                       "range": ["http://www.w3.org/2001/XMLSchema#string"]}],
        )
        matrix = {"mappings": [{
            "sourceConcept": "src:Foo",
            "action": "augment",
            "targetType": "nc:PersonType",
            "augmentationType": "PersonAugmentationType",
            "augmentsType": "nc:PersonType",
            "propertyMappings": [{
                "sourceProperty": "existingProp",
                "action": "reuse-property",
                "targetProperty": "nc:PersonName",
                "reviewStatus": "accepted",
            }],
        }]}

        files = self._run_generation(inv, matrix)
        ext_ttl = files.get("test-edge-extensions.ttl", "")

        # The reuse-property should NOT be declared in extensions
        # (it already exists on the target type)
        assert "existingProp" not in ext_ttl

    def test_extend_uses_baseType_as_superclass(self):
        """Extend entries use baseType scaffolding for rdfs:subClassOf."""
        inv = self._minimal_inventory([
            {"qname": "src:Bar", "label": "Bar", "comment": "", "subClassOf": []},
        ])
        matrix = {"mappings": [{
            "sourceConcept": "src:Bar",
            "action": "extend",
            "targetType": "nc:ActivityType",
            "extensionType": "BarType",
            "baseType": "nc:ObjectType",
            "propertyMappings": [],
        }]}

        files = self._run_generation(inv, matrix)
        ext_ttl = files.get("test-edge-extensions.ttl", "")

        # Should use baseType (nc:ObjectType), not targetType (nc:ActivityType)
        assert "rdfs:subClassOf nc:ObjectType" in ext_ttl

    def test_extend_no_base_falls_back_to_owl_thing(self):
        """When both targetType and baseType are None, generator uses owl:Thing.

        NIEM-specific defaults (structures:ObjectType) belong in
        ontology_specific.py, not in the generator.
        """
        inv = self._minimal_inventory([
            {"qname": "src:Baz", "label": "Baz", "comment": "", "subClassOf": []},
        ])
        matrix = {"mappings": [{
            "sourceConcept": "src:Baz",
            "action": "extend",
            "targetType": None,
            "extensionType": "BazType",
            "baseType": None,
            "propertyMappings": [],
        }]}

        files = self._run_generation(inv, matrix)
        ext_ttl = files.get("test-edge-extensions.ttl", "")

        assert "rdfs:subClassOf owl:Thing" in ext_ttl

    def test_reuse_subclass_of_target(self):
        """Reuse entries create edge type as rdfs:subClassOf the target type."""
        inv = self._minimal_inventory([
            {"qname": "src:Qux", "label": "Qux", "comment": "", "subClassOf": []},
        ])
        matrix = {"mappings": [{
            "sourceConcept": "src:Qux",
            "action": "reuse",
            "targetType": "nc:ActivityType",
            "propertyMappings": [],
        }]}

        files = self._run_generation(inv, matrix)
        core_ttl = files.get("test-edge-core.ttl", "")

        assert "rdfs:subClassOf nc:ActivityType" in core_ttl
