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
    def _run_generation(inv, matrix, target_ontology="niem", target_version="6.0", catalog=None):
        """Run generate_edge_ontology.main() with in-memory data and return file contents.

        The reference catalog is a minimal fixture written to a temporary
        specs directory, selected for the duration of the run through
        ``OM_SPECS_DIR``. The real ``specs/`` tree is never
        written to, and the emitted output never depends on which catalogs
        happen to be built on this machine.
        """
        import json
        import os
        import sys
        import tempfile
        from pathlib import Path
        from unittest import mock
        from ontology_mapper.run_dir_utils import STATE_FILENAME

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            pkg_dir = run_dir / "edge-package"
            pkg_dir.mkdir()
            specs = Path(tmpdir) / "specs"
            specs.mkdir()

            # Write inventory and matrix
            (run_dir / "concept-inventory.json").write_text(json.dumps(inv), encoding="utf-8")
            (run_dir / "mapping-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")

            # Write the minimal catalog into the temporary specs dir
            cat_name = f"{target_ontology}_reference_catalog_{target_version}.json"
            if catalog is None:
                catalog = {"namespaces": {"nc": f"https://docs.oasis-open.org/niemopen/ns/model/niem-core/{target_version}/"}}
            (specs / cat_name).write_text(json.dumps(catalog), encoding="utf-8")

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

            from ontology_mapper.generate_edge_ontology import main
            orig_argv = sys.argv
            sys.argv = ["om-generate-ontology",
                        "--run-dir", str(run_dir),
                        "--package-dir", str(pkg_dir)]
            try:
                with mock.patch.dict(os.environ,
                                     {"OM_SPECS_DIR": str(specs)}):
                    main()
            finally:
                sys.argv = orig_argv

            # Read generated files
            result = {}
            for f in pkg_dir.rglob("*.ttl"):
                result[f.name] = f.read_text(encoding="utf-8")
            return result

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

    @pytest.mark.parametrize("action", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("typed", [False, True])
    def test_accepted_reuse_is_visible_in_owl_without_shapes(self, action, typed):
        from rdflib import Graph, RDF, RDFS, OWL, URIRef

        inv = self._minimal_inventory([
            {"qname": "src:Foo", "label": "Foo", "comment": "", "subClassOf": []}],
            dt_props=[{"qname": "src:flag", "label": "Flag", "domain": ["src:Foo"], "range": []}])
        matrix = {"mappings": [{"sourceConcept": "src:Foo", "action": action,
            "targetType": "nc:BaseType", "propertyMappings": [{"sourceProperty": "src:flag",
            "action": "reuse-property", "targetProperty": "nc:FlagText", "reviewStatus": "accepted"}]}]}
        declaration = {"qualifiedProperty": "nc:FlagText"}
        if typed:
            declaration["qualifiedType"] = "xs:string"
        catalog = {"namespaces": {"nc": "https://example.org/nc/", "xs": "http://www.w3.org/2001/XMLSchema#"},
                   "propertyIndex": {"nc": {"properties": [declaration]}}}
        files = self._run_generation(inv, matrix, catalog=catalog)
        graph = Graph()
        for name, text in files.items():
            if name in ("test-edge-core.ttl", "test-edge-extensions.ttl"):
                graph.parse(data=text, format="turtle")
        prop = URIRef("https://example.org/nc/FlagText")
        restrictions = list(graph.subjects(OWL.onProperty, prop))
        assert restrictions
        assert not list(graph.objects(prop, RDFS.domain))
        assert not list(graph.objects(prop, RDFS.range))
        for restriction in restrictions:
            assert (restriction, RDF.type, OWL.Restriction) in graph
            if typed:
                assert graph.value(restriction, OWL.allValuesFrom) == URIRef("http://www.w3.org/2001/XMLSchema#string")
            else:
                assert int(graph.value(restriction, OWL.minCardinality)) == 0

    def test_multiple_shape_targets_do_not_become_global_domain_intersection(self):
        from rdflib import Graph, RDFS, SH, URIRef

        inv = self._minimal_inventory([
            {"qname": q, "label": q, "comment": "", "subClassOf": []} for q in ("src:A", "src:B")],
            dt_props=[{"qname": "src:flag", "label": "Flag", "domain": [], "range": []}],
            shapes=[{"targetClasses": ["src:A", "src:B"], "targetClass": "src:A", "properties": [
                {"path": "src:flag", "minCount": 0, "maxCount": 0}]}])
        matrix = {"mappings": [{"sourceConcept": q, "action": "extend", "targetType": None} for q in ("src:A", "src:B")]}
        files = self._run_generation(inv, matrix)
        graph = Graph().parse(data=files["test-edge-extensions.ttl"], format="turtle")
        assert not list(graph.triples((None, RDFS.domain, None)))
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        assert len(set(shapes.objects(None, SH.targetClass))) == 2
        assert [int(v) for v in shapes.objects(None, SH.maxCount)] == [0, 0]

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
                # Qualified name — the identity the matrix records.
                "sourceProperty": "src:newProp",
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
                # Qualified name — the identity the matrix records.
                "sourceProperty": "src:existingProp",
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

    # -- accepted reuse-property decisions on reuse/extend classes -----
    @staticmethod
    def _reuse_property_matrix(action, target, source_property="src:existingProp"):
        entry = {
            "sourceConcept": "src:Foo",
            "action": action,
            "targetType": target,
            "propertyMappings": [{
                "sourceProperty": source_property,
                "action": "reuse-property",
                "targetProperty": "nc:PersonName",
                "reviewStatus": "accepted",
            }],
        }
        if action == "extend":
            entry["baseType"] = target
            entry["extensionType"] = "Foo"
        return {"mappings": [entry]}

    def _inventory_with_one_property(self, prop_qname="src:existingProp"):
        return self._minimal_inventory(
            classes=[{"qname": "src:Foo", "label": "Foo", "comment": "", "subClassOf": []}],
            dt_props=[{"qname": prop_qname, "label": "existing prop",
                       "domain": ["src:Foo"],
                       "range": ["http://www.w3.org/2001/XMLSchema#string"]}],
        )

    @pytest.mark.parametrize("action,ttl_name", [
        ("reuse", "test-edge-core.ttl"),
        ("extend", "test-edge-extensions.ttl"),
    ])
    def test_accepted_reuse_property_is_neither_re_declared_nor_redomained(
            self, action, ttl_name):
        """The target property belongs to the target ontology. Declaring it
        here would re-declare a NIEM-owned term, and `rdfs:domain` is a
        GLOBAL assertion in OWL — `nc:PersonName rdfs:domain edge:FooType`
        would narrow that NIEM property to the edge type everywhere, and the
        emitted `rdfs:range`/`rdfs:label` would overwrite its NIEM ones."""
        files = self._run_generation(self._inventory_with_one_property(),
                                     self._reuse_property_matrix(action, "nc:PersonType"))
        ttl = files.get(ttl_name, "")
        # The source property is not re-declared under the edge/ext prefix …
        assert "existingProp" not in ttl
        # … and the NIEM property is not declared, domained or labelled here.
        assert "nc:PersonName\n" not in ttl
        assert "rdfs:domain" not in ttl
        assert "owl:DatatypeProperty" not in ttl
        # The class itself is still emitted and still anchored on its target,
        # and the decision is recorded as an anonymous restriction.
        assert "rdfs:subClassOf nc:PersonType" in ttl
        assert "owl:onProperty nc:PersonName" in ttl

    def test_create_property_is_still_declared(self):
        """Regression guard: only REUSED properties are withheld."""
        matrix = self._reuse_property_matrix("reuse", "nc:PersonType")
        matrix["mappings"][0]["propertyMappings"][0].update(
            {"action": "create-property", "targetProperty": None})
        files = self._run_generation(self._inventory_with_one_property(), matrix)
        assert "existingProp" in files.get("test-edge-core.ttl", "")

    def test_augmenting_namespace_property_is_matched_despite_a_misqualified_matrix(self):
        """A matrix written before the Stage-3 qname fix names an
        augmenting-namespace property under the source prefix
        (`src:zoneCode` for `gis:zoneCode`). The decision must still apply."""
        inv = self._inventory_with_one_property("gis:zoneCode")
        matrix = self._reuse_property_matrix("reuse", "nc:PersonType",
                                             source_property="src:zoneCode")
        ttl = self._run_generation(inv, matrix).get("test-edge-core.ttl", "")
        assert "zoneCode" not in ttl

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

    @pytest.mark.parametrize("properties", [[], [{"path": None, "pathKind": "expression"}]])
    def test_empty_or_expression_only_shape_is_parseable(self, properties):
        from rdflib import Graph, RDF, SH

        inv = self._inventory_with_one_property()
        inv["shaclShapes"] = [{"targetClass": "src:Foo", "properties": properties}]
        files = self._run_generation(inv, self._reuse_property_matrix("reuse", "nc:PersonType"))
        graph = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        assert len(list(graph.subjects(RDF.type, SH.NodeShape))) == 1
        assert not list(graph.triples((None, SH.property, None)))

    def test_unrenderable_reuse_is_reported_without_dangling_shape_path(self, capsys):
        from rdflib import Graph, SH

        inv = self._inventory_with_one_property()
        inv["shaclShapes"] = [{"targetClass": "src:Foo", "properties": [
            {"path": "src:existingProp", "minCount": 1}]}]
        matrix = self._reuse_property_matrix("extend", "BareType")
        matrix["mappings"][0]["propertyMappings"][0]["targetProperty"] = "NoUriProp"
        files = self._run_generation(inv, matrix, catalog={
            "namespaces": {}, "types": [{"qname": "BareType", "uri": "https://example.org/Type"}]})
        for name, ttl in files.items():
            Graph().parse(data=ttl, format="turtle")
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        assert not list(shapes.triples((None, SH.path, None)))
        assert "NoUriProp" in capsys.readouterr().out

    @pytest.mark.parametrize("deactivate", ["shape", "property", None])
    def test_only_active_shapes_constrain_data_and_severity_survives(self, deactivate):
        from rdflib import Graph, SH, URIRef
        from pyshacl import validate

        prop = {"path": "src:existingProp", "minCount": 1,
                "severity": "https://example.org/severity#Notice",
                "deactivated": deactivate == "property"}
        inv = self._inventory_with_one_property()
        inv["shaclShapes"] = [{"targetClass": "src:Foo", "properties": [prop],
                               "deactivated": deactivate == "shape"}]
        matrix = self._reuse_property_matrix("reuse", "nc:PersonType")
        shapes = Graph().parse(data=self._run_generation(inv, matrix)["test-edge-shapes.ttl"], format="turtle")
        data = Graph().parse(data='<urn:item> a <https://docs.oasis-open.org/niemopen/ns/model/niem-core/6.0/PersonType> .', format="turtle")
        conforms, _, _ = validate(data, shacl_graph=shapes, inference="none")
        assert conforms == (deactivate is not None)
        if deactivate is None:
            assert list(shapes.subjects(SH.severity, URIRef(prop["severity"])))

    @pytest.mark.parametrize("action", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("form", ["iri", "catalog-qname", "bare-id", "bound-qname", "unresolved"])
    def test_class_references_use_grounded_target_terms(self, action, form, capsys):
        from rdflib import Graph, RDFS, SH, URIRef

        target_uri = "https://example.org/target/BaseType"
        target = {"iri": target_uri, "bare-id": "BaseId", "unresolved": "missing:BaseType"}.get(form, "nc:BaseType")
        catalog = {"namespaces": {"nc": "https://example.org/target/"} if form == "bound-qname" else {}}
        if form in ("catalog-qname", "bare-id"):
            catalog["types"] = [{"qname": target, "uri": target_uri}]
        inv = self._minimal_inventory(
            [{"qname": "src:Foo", "label": "Foo", "comment": "", "subClassOf": []}],
            dt_props=[{"qname": "src:code", "label": "Code", "domain": ["src:Foo"], "range": []}],
            obj_props=[{"qname": "src:link", "label": "Link", "domain": ["src:Foo"], "range": ["src:Foo"]}],
            shapes=[{"targetClass": "src:Foo", "properties": [{"path": "src:link", "class": "src:Foo"}]}])
        matrix = {"mappings": [{"sourceConcept": "src:Foo", "action": action, "targetType": target,
                               "reviewStatus": "accepted", "propertyMappings": []}]}
        files = self._run_generation(inv, matrix, catalog=catalog)
        for ttl in files.values():
            Graph().parse(data=ttl, format="turtle")
        graph = Graph().parse(data=files["test-edge-combined.ttl"], format="turtle")
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        if form == "unresolved":
            assert target in capsys.readouterr().out
            assert not list(graph.objects(None, RDFS.subClassOf))
            if action != "extend":
                assert not list(shapes.objects(None, SH.targetClass))
        else:
            assert "WARNING" not in capsys.readouterr().out
            predicate = RDFS.domain if action == "augment" else RDFS.subClassOf
            assert list(graph.subjects(predicate, URIRef(target_uri)))
            if action != "extend":
                assert list(graph.subjects(RDFS.range, URIRef(target_uri)))
                assert list(shapes.subjects(SH.targetClass, URIRef(target_uri)))
                assert list(shapes.subjects(SH["class"], URIRef(target_uri)))

    @pytest.mark.parametrize("action", ["reuse", "extend", "augment", "global"])
    @pytest.mark.parametrize("datatype,expected", [
        ("nc:Code", "https://example.org/source-nc/Code"),
        ("https://example.org/source-nc/Code", "https://example.org/source-nc/Code"),
        ("xs:string", "http://www.w3.org/2001/XMLSchema#string"),
    ])
    def test_source_datatype_references_preserve_namespace(self, action, datatype, expected):
        from rdflib import Graph, RDFS, SH, URIRef

        inv = self._inventory_with_one_property()
        inv["namespaceMap"] = {"https://example.org/src/": "src:", "https://example.org/source-nc/": "nc:"}
        inv["datatypeProperties"][0]["range"] = [datatype]
        if action == "global":
            inv["datatypeProperties"][0]["domain"] = []
        else:
            inv["shaclShapes"] = [{"targetClass": "src:Foo", "properties": [
                {"path": "src:existingProp", "datatype": datatype}]}]
        matrix = {"mappings": [{"sourceConcept": "src:Foo", "action": "reuse" if action == "global" else action,
                               "targetType": "nc:BaseType", "propertyMappings": []}]}
        files = self._run_generation(inv, matrix, catalog={"namespaces": {"nc": "https://example.org/target/"}})
        graph = Graph().parse(data=files["test-edge-combined.ttl"], format="turtle")
        assert list(graph.objects(None, RDFS.range)) == [URIRef(expected)]
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        assert list(shapes.objects(None, SH.datatype)) == ([] if action == "global" else [URIRef(expected)])

    def test_distinct_source_shapes_preserve_severity_and_remain_valid(self):
        from rdflib import Graph, RDF, SH, URIRef
        from pyshacl import validate
        from ontology_mapper.extract_concepts import extract_shacl_shapes, make_to_qname

        source_shapes = Graph().parse(data='''
            @prefix src: <https://example.org/src/> .
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            src:Required a sh:NodeShape ; sh:targetClass src:Foo ; sh:severity sh:Warning ;
                sh:property [ sh:path src:existingProp ; sh:minCount 1 ] .
            src:Bounded a sh:NodeShape ; sh:targetClass src:Foo ;
                sh:property [ sh:path src:existingProp ; sh:maxCount 2 ] .
        ''', format="turtle")
        assert validate(Graph(), shacl_graph=source_shapes, meta_shacl=True)[0]
        inv = self._inventory_with_one_property()
        inv["shaclShapes"] = extract_shacl_shapes(source_shapes, make_to_qname({"https://example.org/src/": "src:"}))
        files = self._run_generation(inv, self._reuse_property_matrix("reuse", "nc:PersonType"))
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        nodes = list(shapes.subjects(RDF.type, SH.NodeShape))
        assert len(nodes) == 2
        assert {shapes.value(n, SH.severity) for n in nodes} == {SH.Warning, SH.Violation}
        assert all(len(list(shapes.objects(n, SH.severity))) == 1 for n in nodes)
        assert validate(Graph(), shacl_graph=shapes, meta_shacl=True)[0]
        target = URIRef("https://docs.oasis-open.org/niemopen/ns/model/niem-core/6.0/PersonType")
        data = Graph()
        data.add((URIRef("urn:item"), RDF.type, target))
        assert not validate(data, shacl_graph=shapes)[0]

    def test_catalog_uri_rendering_preserves_shared_target_minimum_policy(self):
        from rdflib import Graph, SH

        inv = self._minimal_inventory(
            [{"qname": q, "label": q, "comment": "", "subClassOf": []} for q in ("src:A", "src:B")],
            dt_props=[{"qname": "src:flag", "label": "Flag", "domain": [], "range": []}],
            shapes=[{"targetClasses": ["src:A", "src:B"], "properties": [{"path": "src:flag", "minCount": 1}]}])
        matrix = {"mappings": [{"sourceConcept": q, "action": "reuse", "targetType": "nc:BaseType"} for q in ("src:A", "src:B")]}
        files = self._run_generation(inv, matrix, catalog={
            "namespaces": {"nc": "https://example.org/target/"},
            "types": [{"qname": "nc:BaseType", "uri": "https://example.org/target/BaseType"}]})
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        assert [int(v) for v in shapes.objects(None, SH.minCount)] == [0, 0]
