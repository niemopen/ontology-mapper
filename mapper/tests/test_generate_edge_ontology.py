#!/usr/bin/env python3
"""Tests for generate_edge_ontology.py — pure helpers and OWL pattern rules."""

import pytest


def test_generation_includes_offline_native_cmf_definitions_in_xml_and_json(tmp_path, monkeypatch):
    import json
    import sys
    from lxml import etree
    from ontology_mapper.generate_edge_ontology import main
    from ontology_mapper.validate_edge_package import check_cmf_consistency

    monkeypatch.delenv("OM_SPECS_DIR", raising=False)
    inventory = {
        "classes": [{"qname": "src:Record", "iri": "urn:source:Record", "label": "Record", "comment": "", "subClassOf": []}],
        "datatypeProperties": [{"qname": "src:value", "iri": "urn:source:value", "label": "Value", "comment": "",
                                "domain": ["src:Record"], "range": ["http://www.w3.org/2001/XMLSchema#string"]}],
        "objectProperties": [], "shaclShapes": [], "codelistSchemes": [], "augmentingNamespaces": [],
    }
    mappings = [{"sourceConcept": "src:Record", "action": "extend", "targetType": "nc:TextType", "reviewStatus": "accepted",
                 "propertyMappings": [{"sourceProperty": "src:value", "action": "create-property", "reviewStatus": "accepted"}]}]
    for name, content in {
        "concept-inventory.json": inventory, "mapping-matrix.json": {"mappings": mappings},
        ".mapper-state.json": {"inputs": {"organization": "sample", "source": "sample", "target_ontology": "niem", "target_version": "6.0"}},
    }.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["om-generate-ontology", "--run-dir", str(tmp_path)])
    main()
    cmf_path = next((tmp_path / "edge-package/cmf").glob("*.cmf"))
    assert check_cmf_consistency(cmf_path, mappings, {"http://sample.gov/sample/edge#", "http://sample.gov/sample/ext#"}) == []
    root = etree.parse(str(cmf_path)).getroot()
    ns = {"cmf": root.nsmap[None], "s": root.nsmap["structures"]}
    text_class = root.xpath('./cmf:Class[@s:id="nc.TextType"]', namespaces=ns)[0]
    assert text_class.findtext("cmf:DocumentationText", namespaces=ns)
    assert text_class.find("cmf:ChildPropertyAssociation", ns) is not None
    data = json.loads(cmf_path.with_suffix(".cmf.json").read_text(encoding="utf-8"))["Model"]
    assert any(c["structures:id"] == "nc.TextType" for c in data["Class"])
    assert any(c["structures:id"] == "xs.string" for c in data["Datatype"])
    assert any(n.get("ConformanceTargetURI") for n in data["Namespace"])

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

    def test_catalog_uri_rendering_preserves_shared_source_requirements(self):
        from rdflib import Graph, Literal, RDF, SH, URIRef
        from pyshacl import validate

        inv = self._minimal_inventory(
            [{"qname": q, "label": q, "comment": "", "subClassOf": []} for q in ("src:A", "src:B")],
            dt_props=[{"qname": "src:flag", "label": "Flag", "domain": [], "range": []}],
            shapes=[{"targetClasses": ["src:A", "src:B"], "properties": [{"path": "src:flag", "minCount": 1}]}])
        matrix = {"mappings": [{"sourceConcept": q, "action": "reuse", "targetType": "nc:BaseType"} for q in ("src:A", "src:B")]}
        files = self._run_generation(inv, matrix, catalog={
            "namespaces": {"nc": "https://example.org/target/"},
            "types": [{"qname": "nc:BaseType", "uri": "https://example.org/target/BaseType"}]})
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        assert [int(v) for v in shapes.objects(None, SH.minCount)] == [1, 1]
        data = Graph()
        data.add((URIRef("urn:item"), RDF.type, URIRef("https://example.org/target/BaseType")))
        assert not validate(data, shacl_graph=shapes, meta_shacl=True)[0]
        data.add((URIRef("urn:item"), URIRef("http://testorg.gov/test/edge#flag"), Literal("present")))
        assert validate(data, shacl_graph=shapes)[0]

    @pytest.mark.parametrize("catalog_uri", [False, True])
    @pytest.mark.parametrize("second_target", [
        "nc:BaseType", "https://example.org/target/BaseType", "alias:BaseType", "other:BaseType"])
    def test_shared_target_identity_is_independent_of_identifier_spelling(self, catalog_uri, second_target):
        from rdflib import Graph, Literal, RDF, SH, URIRef
        from pyshacl import validate
        from ontology_mapper.extract_concepts import extract_shacl_shapes, make_to_qname

        target_uri = "https://example.org/target/"
        catalog = {"namespaces": {"nc": target_uri, "alias": target_uri, "other": "https://example.org/other/"}}
        if catalog_uri:
            catalog["types"] = [{"qname": "nc:BaseType", "uri": target_uri + "BaseType"}]
        source_shapes = Graph().parse(data='''
            @prefix src: <https://example.org/src/> .
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            src:A a sh:NodeShape ; sh:targetClass src:A ; sh:property [ sh:path src:p ; sh:minCount 1 ] .
            src:B a sh:NodeShape ; sh:targetClass src:B ; sh:property [ sh:path src:q ; sh:minCount 1 ] .
        ''', format="turtle")
        inv = self._minimal_inventory(
            [{"qname": q, "label": q, "comment": "", "subClassOf": []} for q in ("src:A", "src:B")],
            dt_props=[{"qname": prop, "label": prop, "domain": [cls], "range": []}
                      for cls, prop in (("src:A", "src:p"), ("src:B", "src:q"))],
            shapes=extract_shacl_shapes(source_shapes, make_to_qname({"https://example.org/src/": "src:"})))
        matrix = {"mappings": [{"sourceConcept": cls, "action": "reuse", "targetType": target,
                               "reviewStatus": "accepted", "propertyMappings": [{
                                   "sourceProperty": prop, "action": "reuse-property",
                                   "targetProperty": mapped_prop, "reviewStatus": "accepted"}]}
                              for cls, prop, mapped_prop, target in (
                                  ("src:A", "src:p", "nc:PText", "nc:BaseType"),
                                  ("src:B", "src:q", "nc:QText", second_target))]}
        files = self._run_generation(inv, matrix, catalog=catalog)
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        assert [int(v) for v in shapes.objects(None, SH.minCount)] == [1, 1]
        data = Graph()
        data.add((URIRef("urn:item"), RDF.type, URIRef(target_uri + "BaseType")))
        data.add((URIRef("urn:item"), URIRef(target_uri + "PText"), Literal("a")))
        assert validate(data, shacl_graph=shapes, meta_shacl=True)[0]
        data.remove((URIRef("urn:item"), URIRef(target_uri + "PText"), None))
        assert not validate(data, shacl_graph=shapes)[0]

    @pytest.mark.parametrize("action_a", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("action_b", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("second_target", ["nc:BaseType", "https://example.org/target/BaseType", "other:BaseType"])
    def test_shared_base_constraints_across_class_actions(self, action_a, action_b, second_target):
        from rdflib import Graph, Literal, RDF, SH, URIRef
        from pyshacl import validate

        inv = self._minimal_inventory(
            [{"qname": "src:" + cls, "label": cls, "comment": "", "subClassOf": []} for cls in ("A", "B")],
            dt_props=[{"qname": "src:" + prop, "label": prop, "domain": ["src:" + cls], "range": []}
                      for cls, prop in (("A", "p"), ("B", "q"))] + [
                          {"qname": "src:anchor", "label": "Anchor", "domain": ["src:A", "src:B"], "range": []}],
            shapes=[{"targetClass": "src:" + cls, "properties": [{"path": "src:" + prop, "minCount": 1}]}
                    for cls, prop in (("A", "p"), ("B", "q"))])
        entries = []
        for cls, prop, action, target in (("A", "p", action_a, "nc:BaseType"), ("B", "q", action_b, second_target)):
            entries.append({"sourceConcept": "src:" + cls, "action": action, "targetType": target,
                            "baseType": target if action == "extend" else None,
                            "augmentsType": target if action == "augment" else None,
                            "reviewStatus": "accepted", "propertyMappings": [
                                {"sourceProperty": "src:" + prop, "reviewStatus": "accepted",
                                 "action": "reuse-property" if action == "reuse" else "create-property",
                                 "targetProperty": "nc:" + prop.upper() + "Text" if action == "reuse" else None},
                                {"sourceProperty": "src:anchor", "action": "reuse-property",
                                 "targetProperty": "nc:AnchorText", "reviewStatus": "accepted"}]})
        files = self._run_generation(inv, {"mappings": entries}, catalog={
            "namespaces": {"nc": "https://example.org/target/", "other": "https://example.org/other/"},
            "types": [{"qname": "nc:BaseType", "uri": "https://example.org/target/BaseType"}]})
        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        ontology = Graph().parse(data=files["test-edge-combined.ttl"], format="turtle")
        for cls, action in (("A", action_a), ("B", action_b)):
            shape = URIRef("http://testorg.gov/test/edge#" + cls + "Shape")
            prop_shape = shapes.value(shape, SH.property)
            assert int(shapes.value(prop_shape, SH.minCount)) == 1
            data = Graph()
            data += ontology
            base_namespace = "other" if cls == "B" and second_target == "other:BaseType" else "target"
            target = shapes.value(shape, SH.targetClass) or URIRef(f"https://example.org/{base_namespace}/BaseType")
            data.add((URIRef("urn:item"), RDF.type, target))
            data.add((URIRef("urn:item"), shapes.value(prop_shape, SH.path), Literal("a")))
            assert validate(data, shacl_graph=shapes, meta_shacl=True, inference="none")[0]
            if action == "extend":
                data.remove((URIRef("urn:item"), shapes.value(prop_shape, SH.path), None))
                other = URIRef("http://testorg.gov/test/edge#" + ("B" if cls == "A" else "A") + "Shape")
                other_property = shapes.value(other, SH.property)
                data.add((URIRef("urn:item"), shapes.value(other_property, SH.path), Literal("other")))
                assert not validate(data, shacl_graph=shapes, inference="none")[0]


class TestSharedSourceProfiles:
    SRC = "https://example.org/src/"
    TARGET = "https://example.org/target/"
    EXT = "http://testorg.gov/test/ext#"

    @classmethod
    def _generate(cls, source, actions=None, parents=None, targets=None, property_targets=None,
                  property_overrides=None):
        from rdflib import Graph
        from ontology_mapper.extract_concepts import extract_shacl_shapes, make_to_qname
        from ontology_mapper.build_strategy_reports import build_class_properties

        actions, parents, targets = actions or {}, parents or {}, targets or {}
        property_targets = property_targets or {}
        property_overrides = property_overrides or {}
        names = sorted({"A", "B"} | set(parents) | set(targets)
                       | {parent for values in parents.values() for parent in values})
        source_shapes = Graph().parse(data=f'''
            @prefix src: <{cls.SRC}> .
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            {source}
        ''', format="turtle")
        inv = TestNiemOWLPatterns._minimal_inventory(
            [{"qname": "src:" + name, "label": name, "comment": "",
              "subClassOf": ["src:" + parent for parent in parents.get(name, [])]} for name in names],
            dt_props=[{"qname": "src:" + p, "label": p, "domain": [], "range": []} for p in ("p", "q")],
            obj_props=[{"qname": "src:link", "label": "Link", "domain": [], "range": []}],
            shapes=extract_shacl_shapes(source_shapes, make_to_qname({cls.SRC: "src:"})))
        class_properties = build_class_properties(inv)
        matrix = {"mappings": []}
        for name in names:
            action = actions.get(name, "reuse")
            target = "nc:" + targets.get(name, "BaseType")
            matrix["mappings"].append({
                "sourceConcept": "src:" + name, "action": action, "targetType": target,
                "baseType": target if action == "extend" else None,
                "augmentsType": target if action == "augment" else None,
                "reviewStatus": "accepted", "propertyMappings": [
                    {"sourceProperty": "src:" + prop, "action": "reuse-property", "reviewStatus": "accepted",
                     "targetProperty": "nc:" + property_targets.get((name, prop), mapped),
                     **property_overrides.get((name, prop), {})}
                    for prop, mapped in (("p", "PText"), ("q", "QText"), ("link", "Link"))
                    if "src:" + prop in class_properties.get("src:" + name, set())]})
        return TestNiemOWLPatterns._run_generation(
            inv, matrix, catalog={"namespaces": {"nc": cls.TARGET}})

    @classmethod
    def _conforms(cls, files, values, target="BaseType", object_types=()):
        from rdflib import Graph, Literal, RDF, URIRef
        from pyshacl import validate

        shapes = Graph().parse(data=files["test-edge-shapes.ttl"], format="turtle")
        data = Graph().parse(data=files["test-edge-combined.ttl"], format="turtle")
        data.add((URIRef("urn:item"), RDF.type, URIRef(target if ":" in target else cls.TARGET + target)))
        for prop, items in values.items():
            for value in items:
                data.add((URIRef("urn:item"), URIRef(prop if ":" in prop else cls.TARGET + prop),
                          value if isinstance(value, URIRef) else Literal(value)))
        for obj, kind in object_types:
            data.add((URIRef(obj), RDF.type, URIRef(cls.TARGET + kind)))
        return validate(data, shacl_graph=shapes, meta_shacl=True, inference="none")[0]

    @pytest.mark.parametrize("action_a", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("action_b", ["reuse", "extend", "augment"])
    def test_maxima_are_alternatives_across_all_actions(self, action_a, action_b):
        files = self._generate('''
            src:AShape a sh:NodeShape; sh:targetClass src:A;
                sh:property [sh:path src:p; sh:minCount 0; sh:maxCount 1].
            src:BShape a sh:NodeShape; sh:targetClass src:B;
                sh:property [sh:path src:p; sh:minCount 0; sh:maxCount 2].
        ''', actions={"A": action_a, "B": action_b})
        target = self.EXT + "BType" if action_b == "extend" else "BaseType"
        assert self._conforms(files, {"PText": ["one", "two"]}, target)
        assert not self._conforms(files, {"PText": ["one", "two", "three"]}, target)
        if action_a == "extend":
            assert not self._conforms(files, {"PText": ["one", "two"]}, self.EXT + "AType")

    @pytest.mark.parametrize("p_count,q_count,expected", [(1, 1, True), (2, 2, True), (1, 2, False), (2, 1, False), (0, 0, False)])
    def test_each_alternative_requires_the_whole_source_profile(self, p_count, q_count, expected):
        files = self._generate('''
            src:AP a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:p; sh:minCount 1; sh:maxCount 1].
            src:AQ a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:q; sh:minCount 1; sh:maxCount 1].
            src:BP a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:p; sh:minCount 2; sh:maxCount 2].
            src:BQ a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:q; sh:minCount 2; sh:maxCount 2].
        ''')
        assert self._conforms(files, {"PText": list(range(p_count)), "QText": list(range(q_count))}) == expected

    @pytest.mark.parametrize("values,expected", [([], True), ([1], False), ([1, 2], True), ([1, 2, 3], False)])
    def test_zero_and_positive_bounds_survive(self, values, expected):
        files = self._generate('''
            src:A a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:p; sh:minCount 0; sh:maxCount 0].
            src:B a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:p; sh:minCount 2; sh:maxCount 2].
        ''')
        assert self._conforms(files, {"PText": values}) == expected

    @pytest.mark.parametrize("values,expected", [(["one"], True), ([1, 2], True), ([1], False), (["one", 2], False)])
    def test_datatypes_stay_with_their_source_bounds(self, values, expected):
        files = self._generate('''
            src:A a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:p; sh:datatype xsd:string; sh:minCount 1; sh:maxCount 1].
            src:B a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:p; sh:datatype xsd:integer; sh:minCount 2; sh:maxCount 2].
        ''')
        assert self._conforms(files, {"PText": values}) == expected

    @pytest.mark.parametrize("kind,expected", [("PersonType", True), ("LocationType", True), ("OtherType", False)])
    def test_object_class_constraints_are_alternatives(self, kind, expected):
        from rdflib import URIRef

        files = self._generate('''
            src:A a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:link; sh:class src:Person; sh:minCount 1].
            src:B a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:link; sh:class src:Place; sh:minCount 1].
        ''', targets={"Person": "PersonType", "Place": "LocationType"})
        assert self._conforms(files, {"Link": [URIRef("urn:object")]}, object_types=[("urn:object", kind)]) == expected

    @pytest.mark.parametrize("other_shape", ["", "src:B a sh:NodeShape; sh:targetClass src:B; sh:deactivated true; sh:property [sh:path src:p; sh:minCount 1].",
        "src:B a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:p; sh:minCount 1; sh:deactivated true]."])
    def test_unconstrained_source_is_a_valid_alternative(self, other_shape):
        files = self._generate('src:A a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:p; sh:minCount 1].' + other_shape)
        assert self._conforms(files, {})

    @pytest.mark.parametrize("action", ["reuse", "extend", "augment"])
    def test_inherited_constraints_use_child_property_mappings(self, action):
        files = self._generate('''
            src:A a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:p; sh:maxCount 1].
            src:B a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:p; sh:maxCount 2].
        ''', actions={"B": action}, parents={"B": ["A"]}, property_targets={("B", "p"): "QText"})
        target = self.EXT + "BType" if action == "extend" else "BaseType"
        assert self._conforms(files, {"PText": [1, 2], "QText": [1]}, target)
        assert not self._conforms(files, {"PText": [1, 2], "QText": [1, 2]}, target)
        if action == "extend":
            assert not self._conforms(files, {"PText": [1], "QText": [1, 2]}, target)

    @pytest.mark.parametrize("parents", [{"B": ["A"]}, {"B": ["A"], "C": ["B"]}, {"B": ["A"], "A": ["B"]}])
    def test_direct_transitive_and_cyclic_inheritance(self, parents):
        files = self._generate('''
            src:A a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:p; sh:maxCount 1].
            src:B a sh:NodeShape; sh:targetClass src:B; sh:property [sh:path src:p; sh:maxCount 2].
            src:C a sh:NodeShape; sh:targetClass src:C; sh:property [sh:path src:p; sh:maxCount 3].
        ''', parents=parents)
        assert self._conforms(files, {"PText": [1]})
        assert not self._conforms(files, {"PText": [1, 2]})

    def test_inherited_only_profile_is_not_unconstrained(self):
        files = self._generate('src:A a sh:NodeShape; sh:targetClass src:A; sh:property [sh:path src:p; sh:minCount 1].', parents={"B": ["A"]})
        assert self._conforms(files, {"PText": [1]})
        assert not self._conforms(files, {})

    @pytest.mark.parametrize("action_a", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("action_b", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("created", [False, True])
    @pytest.mark.parametrize("minimum", [0, 1])
    def test_inherited_property_without_child_decision_keeps_declaring_reference(
            self, action_a, action_b, created, minimum):
        from rdflib import Graph, OWL, RDF, URIRef

        files = self._generate(f'''
            src:A a sh:NodeShape; sh:targetClass src:A;
                sh:property [sh:path src:p; sh:minCount {minimum}; sh:maxCount 1].
            src:B a sh:NodeShape; sh:targetClass src:B;
                sh:property [sh:path src:q; sh:minCount 1; sh:maxCount 1].
        ''', actions={"A": action_a, "B": action_b}, parents={"B": ["A"]},
            property_overrides={("A", "p"): {"action": "create-property"}} if created else {})
        target = self.EXT + "BType" if action_b == "extend" else "BaseType"
        prop = (("http://testorg.gov/test/edge#" if action_a == "reuse" else self.EXT) + "p"
                if created else "PText")
        assert not self._conforms(files, {prop: ["one", "two"], "QText": ["one"]}, target)
        assert self._conforms(files, {prop: ["one"], "QText": ["one"]}, target)
        if minimum:
            assert not self._conforms(files, {"QText": ["one"]}, target)
        if created:
            ontology = Graph().parse(data=files["test-edge-combined.ttl"], format="turtle")
            assert (URIRef(prop), RDF.type, OWL.DatatypeProperty) in ontology

    @pytest.mark.parametrize("action", ["reuse", "extend", "augment"])
    @pytest.mark.parametrize("decision", [
        {"action": "create-property"},
        {"reviewStatus": "pending-review"},
        {"targetProperty": "[undecided]"},
    ])
    def test_explicit_child_decision_keeps_existing_nonreuse_resolution(self, action, decision):
        files = self._generate('''
            src:A a sh:NodeShape; sh:targetClass src:A;
                sh:property [sh:path src:p; sh:maxCount 1].
            src:B a sh:NodeShape; sh:targetClass src:B;
                sh:property [sh:path src:p; sh:maxCount 2].
        ''', actions={"B": action}, parents={"B": ["A"]},
            property_overrides={("B", "p"): decision})
        target = self.EXT + "BType" if action == "extend" else "BaseType"
        child_prop = ("http://testorg.gov/test/edge#" if action == "reuse" else self.EXT) + "p"
        assert self._conforms(files, {"PText": [1, 2], child_prop: [1]}, target)
        assert not self._conforms(files, {"PText": [1, 2], child_prop: [1, 2]}, target)

    @pytest.mark.parametrize("p_count,q_count,expected", [
        # One source property bounded at exactly one value, emitted under
        # two target identities: either identity satisfies it, and the
        # bound counts across both rather than once per identity.
        (1, 0, True), (0, 1, True), (0, 0, False), (1, 1, False),
        (2, 0, False), (2, 1, False), (1, 2, False),
    ])
    def test_inherited_multitarget_shape_offers_each_declaring_context(self, p_count, q_count, expected):
        files = self._generate('''
            src:Shared a sh:NodeShape; sh:targetClass src:A, src:C;
                sh:property [sh:path src:p; sh:minCount 1; sh:maxCount 1].
            src:B a sh:NodeShape; sh:targetClass src:B;
                sh:property [sh:path src:q; sh:minCount 1].
        ''', actions={"B": "extend"}, parents={"B": ["A", "C"]},
            property_targets={("C", "p"): "QText", ("B", "q"): "Link"})
        # Distinct values per identity: SHACL value nodes are a set, so
        # reusing one literal would hide the bound this case is about.
        assert self._conforms(files, {"PText": [f"p{i}" for i in range(p_count)],
                                      "QText": [f"q{i}" for i in range(q_count)],
                                      "Link": ["one"]}, self.EXT + "BType") == expected


def _write_run(tmp_path, matrix, properties):
    import json as _json
    inventory = {
        "classes": [{"qname": "src:Record", "iri": "https://sample.test/src/Record",
                     "label": "Record", "comment": "", "subClassOf": []}],
        "datatypeProperties": properties, "objectProperties": [], "shaclShapes": [],
        "codelistSchemes": [], "augmentingNamespaces": [],
        "primaryNamespace": {"prefix": "src", "namespace": "https://sample.test/src/"},
        "namespaceMap": {"https://sample.test/src/": "src:"},
    }
    (tmp_path / "concept-inventory.json").write_text(_json.dumps(inventory), encoding="utf-8")
    (tmp_path / "mapping-matrix.json").write_text(_json.dumps(matrix), encoding="utf-8")
    (tmp_path / ".mapper-state.json").write_text(_json.dumps({"inputs": {
        "organization": "sample", "source": "sample",
        "target_ontology": "niem", "target_version": "6.0"}}), encoding="utf-8")


def _emitted(tmp_path, suffix):
    return " ".join(f.read_text(encoding="utf-8")
                    for f in (tmp_path / "edge-package").rglob(suffix))


def test_all_three_emitters_name_one_identity_for_an_undeclared_namespace_property(tmp_path, monkeypatch):
    """`make_to_qname` leaves a property whose namespace the manifest does not
    name as a full IRI. OWL, CMF and the extension catalog must mint the same
    term for it - the OWL emitter previously declared it in the third party's
    own namespace while the other two minted `ext`."""
    import sys as _sys
    from ontology_mapper.generate_edge_ontology import main as generate

    prop = "https://other.test/ns/value"
    matrix = {"mappings": [{"sourceConcept": "src:Record", "action": "extend",
                            "targetType": "nc:TextType", "reviewStatus": "accepted",
                            "propertyMappings": [{"sourceProperty": prop,
                                                  "action": "create-property",
                                                  "reviewStatus": "accepted"}]}]}
    _write_run(tmp_path, matrix, [{"qname": prop, "iri": prop, "label": "Value", "comment": "",
                                   "domain": ["src:Record"],
                                   "range": ["http://www.w3.org/2001/XMLSchema#string"]}])
    monkeypatch.setattr(_sys, "argv", ["om-generate-ontology", "--run-dir", str(tmp_path)])

    generate()

    ttl = _emitted(tmp_path, "*.ttl")
    assert "other.test" not in ttl      # never mint into a namespace we do not own
    assert "ext:value" in ttl
    assert 'structures:id="ext.value"' in _emitted(tmp_path, "*.cmf")


def test_generation_refuses_a_saved_class_target_the_policy_rejects(tmp_path, monkeypatch):
    """Every driver - runner, web executor, a by-hand CLI - enters here."""
    import sys as _sys
    from ontology_mapper.generate_edge_ontology import main as generate

    matrix = {"mappings": [{"sourceConcept": "src:Record", "action": "reuse",
                            "targetType": "hs:PersonRoleCodeSimpleType",
                            "reviewStatus": "accepted", "propertyMappings": []}]}
    _write_run(tmp_path, matrix, [])
    monkeypatch.setattr(_sys, "argv", ["om-generate-ontology", "--run-dir", str(tmp_path)])

    with pytest.raises(ValueError, match="src:Record"):
        generate()

    assert not (tmp_path / "edge-package" / "ontology").exists()


class TestEmittedIdentityAcrossFiles:
    """A term the shapes constrain must be a term some file declares."""

    SRC = TestSharedSourceProfiles.SRC
    TARGET = TestSharedSourceProfiles.TARGET

    def test_a_property_inherited_from_an_excluded_parent_uses_the_emitting_identity(self):
        """The declaring parent is excluded, so it mints nothing; the reuse
        class that emits the property declares it under the edge prefix, and
        the shape has to constrain that same term."""
        files = TestSharedSourceProfiles._generate('''
            src:A a sh:NodeShape; sh:targetClass src:A;
                sh:property [sh:path src:p; sh:minCount 1].
        ''', actions={"A": "exclude"}, parents={"B": ["A"]},
            targets={"C": "BaseType"},
            property_overrides={("A", "p"): {"action": "create-property",
                                             "targetProperty": None},
                                ("B", "p"): {"action": "create-property",
                                             "targetProperty": None}})
        shapes = files["test-edge-shapes.ttl"]
        declared = files["test-edge-core.ttl"] + files["test-edge-extensions.ttl"]
        for term in ("test-edge:p", "ext:p"):
            if term in shapes:
                assert term in declared, (term, shapes)

    def test_two_source_classes_with_one_local_name_are_refused(self, tmp_path, monkeypatch):
        """`edge_class_name` is namespace-blind: emitting both would produce
        one type carrying both superclasses, both labels and both property
        sets, and no emitter could tell them apart afterwards."""
        import json as _json
        from ontology_mapper import generate_edge_ontology

        inventory = {"classes": [
            {"qname": "src:Thing", "iri": "https://sample.test/src/Thing",
             "label": "Source Thing", "comment": "", "subClassOf": []},
            {"qname": "aug:Thing", "iri": "https://aug.test/ns#Thing",
             "label": "Augmenting Thing", "comment": "", "subClassOf": []}],
            "datatypeProperties": [], "objectProperties": [], "shaclShapes": [],
            "codelistSchemes": [],
            "augmentingNamespaces": [{"prefix": "aug:", "namespace": "https://aug.test/ns#"}],
            "primaryNamespace": {"prefix": "src", "namespace": "https://sample.test/src/"},
            "namespaceMap": {"https://sample.test/src/": "src:"}}
        matrix = {"mappings": [
            {"sourceConcept": "src:Thing", "action": "reuse", "targetType": "nc:PersonType",
             "reviewStatus": "accepted", "propertyMappings": []},
            {"sourceConcept": "aug:Thing", "action": "reuse", "targetType": "nc:PersonType",
             "reviewStatus": "accepted", "propertyMappings": []}]}
        (tmp_path / "concept-inventory.json").write_text(_json.dumps(inventory), encoding="utf-8")
        (tmp_path / "mapping-matrix.json").write_text(_json.dumps(matrix), encoding="utf-8")
        (tmp_path / ".mapper-state.json").write_text(_json.dumps({"inputs": {
            "organization": "sample", "source": "sample",
            "target_ontology": "niem", "target_version": "6.0"}}), encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["om-generate-ontology", "--run-dir", str(tmp_path)])
        # The generator's own refusal, named: the CMF builder further down
        # also rejects the duplicate, but only after seven OWL, SHACL and
        # vocab files are already on disk.
        with pytest.raises(ValueError, match="more than one source concept"):
            generate_edge_ontology.main()

    def test_a_target_namespace_without_a_separator_has_one_spelling(self):
        """Three of the eight namespaces the NODS catalog binds do not end
        in a separator. Concatenating there produced a second spelling of
        one target in the same file, matching no term the catalog names."""
        inv = TestNiemOWLPatterns._minimal_inventory(
            [{"qname": "src:A", "label": "A", "comment": "", "subClassOf": []},
             {"qname": "src:B", "label": "B", "comment": "", "subClassOf": []}])
        # One target, two stored spellings — the QName and the full IRI a
        # pre-policy matrix carries. Identity comparison has to see them as
        # one class, and both must render the same way.
        matrix = {"mappings": [
            {"sourceConcept": "src:A", "action": "reuse",
             "targetType": "nods:CaseType", "reviewStatus": "accepted",
             "propertyMappings": []},
            {"sourceConcept": "src:B", "action": "reuse",
             "targetType": "http://ncsc.org/nods/nods/CaseType",
             "reviewStatus": "accepted", "propertyMappings": []}]}
        files = TestNiemOWLPatterns._run_generation(
            inv, matrix, catalog={"namespaces": {"nods": "http://ncsc.org/nods/nods"}})
        text = " ".join(files.values())
        assert "http://ncsc.org/nods/nodsCaseType" not in text

    def test_an_augments_type_in_another_namespace_keeps_its_prefix(self):
        """`augmentsType` is settable independently of `targetType`, and the
        emitters read it: unbound, the augmentation loses its SHACL
        constraint and its property is emitted with no domain."""
        inv = TestNiemOWLPatterns._minimal_inventory(
            [{"qname": "src:A", "label": "A", "comment": "", "subClassOf": []}],
            dt_props=[{"qname": "src:p", "label": "p", "domain": ["src:A"], "range": []}])
        matrix = {"mappings": [{"sourceConcept": "src:A", "action": "augment",
                                "targetType": "nc:BaseType", "augmentsType": "j:CaseType",
                                "augmentationType": "AAugmentationType",
                                "reviewStatus": "accepted",
                                "propertyMappings": [{"sourceProperty": "src:p",
                                                      "action": "create-property",
                                                      "reviewStatus": "accepted"}]}]}
        files = TestNiemOWLPatterns._run_generation(
            inv, matrix, catalog={"namespaces": {"nc": "https://example.org/target/",
                                                 "j": "https://example.org/j/"}})
        text = " ".join(files.values())
        assert "@prefix j:" in text
        assert "j:CaseType" in text


class TestRefusalsDoNotFireOnLegitimateRuns:
    """The author's pass on the emitted-name refusal: it must fire only
    where two concepts really do emit one name."""

    def _run(self, tmp_path, monkeypatch, mappings, classes):
        import json as _json
        from ontology_mapper import generate_edge_ontology

        inventory = {"classes": classes, "datatypeProperties": [],
                     "objectProperties": [], "shaclShapes": [],
                     "codelistSchemes": [],
                     "augmentingNamespaces": [{"prefix": "aug:",
                                               "namespace": "https://aug.test/ns#"}],
                     "primaryNamespace": {"prefix": "src",
                                          "namespace": "https://sample.test/src/"},
                     "namespaceMap": {"https://sample.test/src/": "src:"}}
        (tmp_path / "concept-inventory.json").write_text(
            _json.dumps(inventory), encoding="utf-8")
        (tmp_path / "mapping-matrix.json").write_text(
            _json.dumps({"mappings": mappings}), encoding="utf-8")
        (tmp_path / ".mapper-state.json").write_text(_json.dumps({"inputs": {
            "organization": "sample", "source": "sample",
            "target_ontology": "niem", "target_version": "6.0"}}), encoding="utf-8")
        monkeypatch.setattr("sys.argv",
                            ["om-generate-ontology", "--run-dir", str(tmp_path)])
        generate_edge_ontology.main()
        return " ".join(f.read_text(encoding="utf-8")
                        for f in (tmp_path / "edge-package").rglob("*.ttl"))

    def _classes(self):
        return [{"qname": "src:Thing", "iri": "https://sample.test/src/Thing",
                 "label": "Source Thing", "comment": "", "subClassOf": []},
                {"qname": "aug:Thing", "iri": "https://aug.test/ns#Thing",
                 "label": "Augmenting Thing", "comment": "", "subClassOf": []}]

    def _row(self, concept, action, **extra):
        row = {"sourceConcept": concept, "action": action,
               "targetType": "nc:PersonType", "reviewStatus": "accepted",
               "propertyMappings": []}
        row.update(extra)
        return row

    def test_two_augmentations_sharing_a_local_name_still_generate(self, tmp_path, monkeypatch):
        """An augmentation declares no class of its own in OWL — its
        properties land on the augmented target — so two augmentations share
        no emitted class name."""
        ttl = self._run(tmp_path, monkeypatch, [
            self._row("src:Thing", "augment", augmentsType="nc:PersonType",
                      augmentationType="SourceThingAugmentationType"),
            self._row("aug:Thing", "augment", augmentsType="nc:PersonType",
                      augmentationType="AugThingAugmentationType")],
            self._classes())
        assert "Augmentation of nc:PersonType" in ttl

    def test_a_reuse_class_beside_an_augmentation_still_generates(self, tmp_path, monkeypatch):
        ttl = self._run(tmp_path, monkeypatch, [
            self._row("src:Thing", "reuse"),
            self._row("aug:Thing", "augment", augmentsType="nc:PersonType",
                      augmentationType="AugThingAugmentationType")],
            self._classes())
        assert "sample-edge:ThingType" in ttl or "ThingType" in ttl

    def test_a_pending_class_mapping_is_not_emitted(self, tmp_path, monkeypatch):
        """"Only emit accepted mappings" (OM__GENERATORS.md). Review exit
        blocks pending concepts, so this is the by-hand path: emitting one
        ships a class decision the reviewer never made."""
        ttl = self._run(tmp_path, monkeypatch, [
            self._row("src:Thing", "reuse"),
            dict(self._row("aug:Thing", "reuse"), reviewStatus="pending-review")],
            self._classes())
        assert "Augmenting Thing" not in ttl
        assert "Source Thing" in ttl


class TestInheritedIdentityThroughChains:
    """Every `sh:path` must name a term some ontology file declares, and an
    accepted reuse decision must survive an inherited property."""

    TARGET = TestSharedSourceProfiles.TARGET

    def _cls(self, name, parents=()):
        return {"qname": "src:" + name, "iri": "https://sample.test/src/" + name,
                "label": name, "comment": "",
                "subClassOf": ["src:" + p for p in parents]}

    def _row(self, concept, action, **extra):
        row = {"sourceConcept": "src:" + concept, "action": action,
               "targetType": "nc:BaseType", "reviewStatus": "accepted",
               "propertyMappings": []}
        row.update(extra)
        return row

    def test_an_excluded_middle_parent_does_not_rename_the_declaring_extension(self):
        """The nearest EMITTING ancestor names the property. Taking the leaf
        named `edge:` for a term only the grandparent's extension declares —
        a shape constraining a predicate no file defines, exit 0."""
        inventory = TestNiemOWLPatterns._minimal_inventory(
            [self._cls("Grand"), self._cls("Middle", ["Grand"]),
             self._cls("Child", ["Middle"]), self._cls("Other")],
            dt_props=[{"qname": "src:code", "label": "code",
                       "domain": ["src:Grand"], "range": []}],
            shapes=[{"targetClasses": ["src:Grand"],
                     "properties": [{"path": "src:code", "minCount": 1}]}])
        matrix = {"mappings": [
            self._row("Grand", "extend", baseType="nc:BaseType"),
            self._row("Middle", "exclude"),
            self._row("Child", "reuse"),
            self._row("Other", "reuse")]}
        files = TestNiemOWLPatterns._run_generation(
            inventory, matrix, catalog={"namespaces": {"nc": self.TARGET}})
        shapes = files["test-edge-shapes.ttl"]
        assert "ext:code" in shapes
        assert "test-edge:code" not in shapes

    def test_an_accepted_reuse_decision_survives_an_inherited_property(self):
        """The property's domain is on the parent and the child's own shape
        attaches it; the decision was recorded under the legacy
    parent-prefix spelling. Dropping it would ship a created term where
        the reviewer accepted reuse of a target property."""
        inventory = TestNiemOWLPatterns._minimal_inventory(
            [self._cls("Parent"), self._cls("Kid", ["Parent"])],
            dt_props=[{"qname": "aug:code", "label": "code",
                       "domain": ["src:Parent"], "range": []}],
            shapes=[{"targetClasses": ["src:Kid"],
                     "properties": [{"path": "aug:code", "minCount": 1}]}])
        inventory["augmentingNamespaces"] = [{"prefix": "aug:",
                                              "namespace": "https://aug.test/ns#"}]
        matrix = {"mappings": [
            self._row("Parent", "reuse"),
            dict(self._row("Kid", "reuse"), propertyMappings=[
                {"sourceProperty": "src:code", "action": "reuse-property",
                 "reviewStatus": "accepted", "targetProperty": "nc:PersonFullName"}])]}
        files = TestNiemOWLPatterns._run_generation(
            inventory, matrix, catalog={"namespaces": {"nc": self.TARGET}})
        shapes = files["test-edge-shapes.ttl"]
        assert "nc:PersonFullName" in shapes
        assert "aug:code" not in shapes

    def test_one_target_named_two_ways_is_one_shared_target(self):
        """A pre-policy matrix can carry the IRI beside the QName. Comparing
        identities through `component_iri` is what makes them one target; a
        concatenated spelling made two, each with its own constraints."""
        inventory = TestNiemOWLPatterns._minimal_inventory(
            [self._cls("A"), self._cls("B")])
        matrix = {"mappings": [
            dict(self._row("A", "reuse"), targetType="nods:BondType"),
            dict(self._row("B", "reuse"),
                 targetType="http://ncsc.org/nods/nods/BondType")]}
        files = TestNiemOWLPatterns._run_generation(
            inventory, matrix,
            catalog={"namespaces": {"nods": "http://ncsc.org/nods/nods"}})
        text = " ".join(files.values())
        assert "http://ncsc.org/nods/nodsBondType" not in text
        assert text.count("sh:targetClass") <= 2


class TestReferentialClosure:
    """A shape may not constrain a term no ontology file in the package
    declares. Two defects of that shape shipped with exit 0, and none of
    Stage 7's twelve checks asks the question."""

    CORE = ("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix edge: <https://e.test/edge#> .\n"
            "@prefix ext: <https://e.test/ext#> .\n"
            "edge:declared a owl:DatatypeProperty .\n")

    SHAPES_HEAD = ("@prefix edge: <https://e.test/edge#> .\n"
                   "@prefix ext: <https://e.test/ext#> .\n"
                   "@prefix nc: <https://target.test/> .\n"
                   "@prefix sh: <http://www.w3.org/ns/shacl#> .\n")

    OWN = ("https://e.test/edge#", "https://e.test/ext#")

    def _ask(self, shapes_body):
        from ontology_mapper.generate_edge_ontology import undeclared_shape_paths
        return undeclared_shape_paths(self.CORE, "",
                                      self.SHAPES_HEAD + shapes_body, self.OWN)

    def test_a_declared_term_is_closed(self):
        assert self._ask("[] a sh:NodeShape ; sh:property [ sh:path edge:declared ] .") == []

    def test_an_undeclared_term_is_named(self):
        assert self._ask("[] a sh:NodeShape ; sh:property [ sh:path edge:missing ] .") == [
            "https://e.test/edge#missing"]

    def test_an_undeclared_alternative_is_named(self):
        body = ("[] a sh:NodeShape ; sh:property [ sh:path "
                "[ sh:alternativePath (edge:declared edge:missing) ] ] .")
        assert self._ask(body) == ["https://e.test/edge#missing"]

    def test_a_target_namespace_term_is_not_this_package_to_declare(self):
        assert self._ask("[] a sh:NodeShape ; sh:property [ sh:path nc:PersonName ] .") == []


class TestExclusionsAndDeclarations:
    """An exclusion is decided, not pending, and a property whose range this
    package does not emit is still the source's property."""

    TARGET = TestSharedSourceProfiles.TARGET

    def _cls(self, name, parents=()):
        return {"qname": "src:" + name, "iri": "https://sample.test/src/" + name,
                "label": name, "comment": "",
                "subClassOf": ["src:" + p for p in parents]}

    def _row(self, concept, action, status="accepted", **extra):
        row = {"sourceConcept": "src:" + concept, "action": action,
               "targetType": "nc:BaseType", "reviewStatus": status,
               "propertyMappings": []}
        row.update(extra)
        return row

    def _files(self, review_status):
        inventory = TestNiemOWLPatterns._minimal_inventory(
            [self._cls("Active"), self._cls("Gone")],
            obj_props=[{"qname": "src:hasGone", "label": "hasGone",
                        "domain": ["src:Active"],
                        "range": ["https://sample.test/src/Gone"]}])
        matrix = {"mappings": [self._row("Active", "reuse"),
                               self._row("Gone", "exclude", review_status)]}
        return TestNiemOWLPatterns._run_generation(
            inventory, matrix, catalog={"namespaces": {"nc": self.TARGET}})

    @pytest.mark.parametrize("review_status", ["pending-review", "accepted"])
    def test_a_property_ranged_on_an_excluded_class_is_still_declared(self, review_status):
        """`get_pending_items` never presents an exclusion, so its status stays
        `pending-review` for the life of the run. Reading that as undecided
        dropped the property from the OWL while the CMF kept declaring it."""
        files = self._files(review_status)
        core = files["test-edge-core.ttl"]
        assert "test-edge:hasGone" in core
        assert "rdfs:range owl:Thing" in core


class TestInheritedIdentityIsOrderIndependent:
    """`subClassOf` is a set in the source model: nothing emitted may depend
    on which parent happens to be written first."""

    TARGET = TestSharedSourceProfiles.TARGET

    def _files(self, parent_order):
        inventory = TestNiemOWLPatterns._minimal_inventory(
            [{"qname": "src:P1", "iri": "https://sample.test/src/P1", "label": "P1",
              "comment": "", "subClassOf": []},
             {"qname": "src:P2", "iri": "https://sample.test/src/P2", "label": "P2",
              "comment": "", "subClassOf": []},
             {"qname": "src:Kid", "iri": "https://sample.test/src/Kid", "label": "Kid",
              "comment": "", "subClassOf": list(parent_order)}],
            dt_props=[{"qname": "src:code", "label": "code",
                       "domain": ["src:P1"], "range": []}],
            shapes=[{"targetClasses": ["src:P1"],
                     "properties": [{"path": "src:code", "minCount": 1}]}])
        matrix = {"mappings": [
            {"sourceConcept": "src:P1", "action": "extend", "targetType": "nc:BaseType",
             "baseType": "nc:BaseType", "reviewStatus": "accepted", "propertyMappings": []},
            {"sourceConcept": "src:P2", "action": "reuse", "targetType": "nc:BaseType",
             "reviewStatus": "accepted", "propertyMappings": []},
            {"sourceConcept": "src:Kid", "action": "reuse", "targetType": "nc:BaseType",
             "reviewStatus": "accepted", "propertyMappings": []}]}
        return TestNiemOWLPatterns._run_generation(
            inventory, matrix, catalog={"namespaces": {"nc": self.TARGET}})

    def test_the_declaring_class_names_the_property_either_way(self):
        first = self._files(["src:P1", "src:P2"])["test-edge-shapes.ttl"]
        second = self._files(["src:P2", "src:P1"])["test-edge-shapes.ttl"]
        paths = lambda text: sorted(line.strip() for line in text.splitlines()
                                    if "sh:path" in line)
        assert paths(first) == paths(second)
