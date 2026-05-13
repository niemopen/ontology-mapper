#!/usr/bin/env python3
"""Tests for generate_cmf_catalog.py — CMF-based reference catalog generation."""

import json
import pytest
from pathlib import Path

from ontology_mapper.generate_cmf_catalog import (
    _cmf_id_to_qname,
    _classify_pattern,
    parse_genericode_file,
    load_codelists,
    extract_namespaces,
    extract_types,
    extract_properties,
    build_property_index,
    build_inheritance_chains,
    build_augmentation_map,
    enrich_with_codelists,
    definition_quality_report,
    build_catalog,
    build_catalog_summary,
    build_type_directory,
)
from ontology_mapper.owl_cmf_bridge import (
    CmfModel,
    CmfNamespace,
    CmfClass,
    CmfProperty,
    CmfHasProperty,
    CmfAugmentationRecord,
    CmfRestriction,
    CmfFacet,
)


# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_model():
    """A minimal CmfModel for testing."""
    return CmfModel(
        namespaces=[
            CmfNamespace(
                ns_id="ext", uri="http://example.org/ext", prefix="ext",
                documentation="Extension namespace", category="EXTENSION",
            ),
            CmfNamespace(
                ns_id="nc", uri="http://example.org/core", prefix="nc",
                documentation="Core namespace", category="CORE",
            ),
        ],
        classes=[
            CmfClass(
                class_id="nc.PersonType", name="PersonType",
                namespace_ref="nc",
                documentation="A data type for a human being.",
                sub_class_of="",
                properties=[
                    CmfHasProperty(property_ref="nc.PersonName", is_object=True,
                                   min_occurs=0, max_occurs="unbounded"),
                    CmfHasProperty(property_ref="nc.PersonBirthDate", is_object=False,
                                   min_occurs=0, max_occurs="1"),
                ],
            ),
            CmfClass(
                class_id="ext.EmployeeType", name="EmployeeType",
                namespace_ref="ext",
                documentation="A data type for an employee.",
                sub_class_of="nc.PersonType",
                properties=[
                    CmfHasProperty(property_ref="ext.EmployeeID", is_object=False,
                                   min_occurs=1, max_occurs="1"),
                ],
            ),
            CmfClass(
                class_id="ext.PersonCaseAssociationType", name="PersonCaseAssociationType",
                namespace_ref="ext",
                documentation="An association between a person and a case.",
                sub_class_of="",
                properties=[],
            ),
        ],
        properties=[
            CmfProperty(
                prop_id="nc.PersonName", name="PersonName",
                namespace_ref="nc", documentation="A name of a person.",
                is_object=True, class_ref="nc.PersonNameType",
            ),
            CmfProperty(
                prop_id="nc.PersonBirthDate", name="PersonBirthDate",
                namespace_ref="nc", documentation="A date of birth.",
                is_object=False, datatype_ref="xs.date",
            ),
            CmfProperty(
                prop_id="ext.EmployeeID", name="EmployeeID",
                namespace_ref="ext", documentation="An employee identifier.",
                is_object=False, datatype_ref="xs.string",
            ),
        ],
    )


@pytest.fixture
def sample_gc_file(tmp_path):
    """A minimal .gc codelist file."""
    content = """\
<?xml version="1.0" encoding="UTF-8"?>
<gc:CodeList xmlns:gc="http://docs.oasis-open.org/codelist/ns/genericode/1.0/">
  <Identification>
    <ShortName>StatusCode</ShortName>
    <Version>1.0</Version>
  </Identification>
  <ColumnSet>
    <Column Id="code" Use="required">
      <ShortName>code</ShortName>
      <CanonicalUri>http://reference.niem.gov/niem/specification/code-lists/1.0/column/code</CanonicalUri>
    </Column>
    <Column Id="definition" Use="optional">
      <ShortName>definition</ShortName>
      <CanonicalUri>http://reference.niem.gov/niem/specification/code-lists/1.0/column/definition</CanonicalUri>
    </Column>
  </ColumnSet>
  <SimpleCodeList>
    <Row>
      <Value ColumnRef="code"><SimpleValue>Active</SimpleValue></Value>
      <Value ColumnRef="definition"><SimpleValue>Currently active</SimpleValue></Value>
    </Row>
    <Row>
      <Value ColumnRef="code"><SimpleValue>Closed</SimpleValue></Value>
      <Value ColumnRef="definition"><SimpleValue>No longer active</SimpleValue></Value>
    </Row>
    <Row>
      <Value ColumnRef="code"><SimpleValue>Pending</SimpleValue></Value>
    </Row>
  </SimpleCodeList>
</gc:CodeList>
"""
    gc_path = tmp_path / "StatusCode.gc"
    gc_path.write_text(content, encoding="utf-8")
    return gc_path


@pytest.fixture
def sample_gc_unprefixed(tmp_path):
    """A .gc file with unprefixed child elements (like real NODS files)."""
    content = """\
<?xml version="1.0" encoding="US-ASCII"?>
<gc:CodeList xmlns:gc="http://docs.oasis-open.org/codelist/ns/genericode/1.0/">
<Identification><ShortName>BondCategoryCode</ShortName><Version>1.0</Version><CanonicalUri>http://ncsc.org/nods/BondCategoryCode</CanonicalUri></Identification>
<ColumnSet><Column Id="code" Use="required"><ShortName>code</ShortName><CanonicalUri>http://reference.niem.gov/niem/specification/code-lists/1.0/column/code</CanonicalUri><Data Type="normalizedString" Lang="en"/></Column><Key Id="codeKey"><ShortName>CodeKey</ShortName><ColumnRef Ref="code"/></Key></ColumnSet>
<SimpleCodeList><Row><Value ColumnRef="code"><SimpleValue>Cash</SimpleValue></Value></Row><Row><Value ColumnRef="code"><SimpleValue>Surety</SimpleValue></Value></Row></SimpleCodeList>
</gc:CodeList>
"""
    gc_path = tmp_path / "BondCategoryCode.gc"
    gc_path.write_text(content, encoding="utf-8")
    return gc_path


# ─── _cmf_id_to_qname ───────────────────────────────────────────────────

class TestCmfIdToQname:
    def test_dot_to_colon(self):
        assert _cmf_id_to_qname("nods.ChargeType") == "nods:ChargeType"

    def test_xs_prefix(self):
        assert _cmf_id_to_qname("xs.string") == "xs:string"

    def test_empty(self):
        assert _cmf_id_to_qname("") == ""

    def test_no_dot(self):
        assert _cmf_id_to_qname("SimpleType") == "SimpleType"

    def test_multiple_dots(self):
        # Only split on first dot
        assert _cmf_id_to_qname("a.b.c") == "a:b.c"


# ─── _classify_pattern ──────────────────────────────────────────────────

class TestClassifyPattern:
    def test_augmentation(self):
        assert _classify_pattern("PersonAugmentationType") == "augmentation"

    def test_association(self):
        assert _classify_pattern("PersonCaseAssociationType") == "association"

    def test_metadata(self):
        assert _classify_pattern("CaseMetadataType") == "metadata"

    def test_code_simple(self):
        assert _classify_pattern("StatusCodeSimpleType") == "simple_value"

    def test_code_type(self):
        assert _classify_pattern("StatusCodeType") == "simple_value"

    def test_simple_type(self):
        assert _classify_pattern("TextSimpleType") == "simple_value"

    def test_object_default(self):
        assert _classify_pattern("PersonType") == "object"

    def test_adapter(self):
        assert _classify_pattern("GeospatialAdapterType") == "adapter"


# ─── Genericode Parsing ─────────────────────────────────────────────────

class TestParseGenericode:
    def test_prefixed_gc(self, sample_gc_file):
        name, values = parse_genericode_file(sample_gc_file)
        assert name == "StatusCode"
        assert len(values) == 3
        assert values[0]["value"] == "Active"
        assert values[0]["definition"] == "Currently active"
        # Third entry has no definition
        pending = [v for v in values if v["value"] == "Pending"][0]
        assert pending["definition"] == ""

    def test_unprefixed_gc(self, sample_gc_unprefixed):
        name, values = parse_genericode_file(sample_gc_unprefixed)
        assert name == "BondCategoryCode"
        assert len(values) == 2
        assert {v["value"] for v in values} == {"Cash", "Surety"}

    def test_load_codelists(self, tmp_path, sample_gc_file):
        codelists = load_codelists(tmp_path)
        assert "StatusCode" in codelists
        assert len(codelists["StatusCode"]) == 3


# ─── Extract Namespaces ─────────────────────────────────────────────────

class TestExtractNamespaces:
    def test_basic(self, sample_model):
        ns_map = extract_namespaces(sample_model)
        assert "ext" in ns_map
        assert "nc" in ns_map
        assert ns_map["ext"]["category"] == "EXTENSION"
        assert ns_map["nc"]["uri"] == "http://example.org/core"


# ─── Extract Types ───────────────────────────────────────────────────────

class TestExtractTypes:
    def test_count(self, sample_model):
        types = extract_types(sample_model)
        assert len(types) == 3

    def test_qname_conversion(self, sample_model):
        types = extract_types(sample_model)
        qnames = {t["qname"] for t in types}
        assert "nc:PersonType" in qnames
        assert "ext:EmployeeType" in qnames

    def test_base_type(self, sample_model):
        types = extract_types(sample_model)
        emp = next(t for t in types if t["qname"] == "ext:EmployeeType")
        assert emp["baseType"] == "nc:PersonType"

    def test_no_base_type(self, sample_model):
        types = extract_types(sample_model)
        person = next(t for t in types if t["qname"] == "nc:PersonType")
        assert person["baseType"] is None

    def test_properties_list(self, sample_model):
        types = extract_types(sample_model)
        person = next(t for t in types if t["qname"] == "nc:PersonType")
        assert "PersonName" in person["properties"]
        assert "PersonBirthDate" in person["properties"]

    def test_cardinalities(self, sample_model):
        types = extract_types(sample_model)
        person = next(t for t in types if t["qname"] == "nc:PersonType")
        assert "PersonBirthDate" in person["propertyCardinalities"]
        card = person["propertyCardinalities"]["PersonBirthDate"]
        assert card["minOccurs"] == "0"
        assert card["maxOccurs"] == "1"

    def test_property_definitions(self, sample_model):
        types = extract_types(sample_model)
        person = next(t for t in types if t["qname"] == "nc:PersonType")
        assert "PersonName" in person["propertyDefinitions"]
        assert person["propertyDefinitions"]["PersonName"]["definition"] == "A name of a person."

    def test_pattern_classification(self, sample_model):
        types = extract_types(sample_model)
        assoc = next(t for t in types if "Association" in t["qname"])
        assert assoc["pattern"] == "association"

    def test_sorted_by_qname(self, sample_model):
        types = extract_types(sample_model)
        qnames = [t["qname"] for t in types]
        assert qnames == sorted(qnames)


# ─── Extract Properties ─────────────────────────────────────────────────

class TestExtractProperties:
    def test_count(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        assert len(props) == 3

    def test_qualified_property(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        qps = {p["qualifiedProperty"] for p in props}
        assert "nc:PersonName" in qps

    def test_containing_types(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        pn = next(p for p in props if p["qualifiedProperty"] == "nc:PersonName")
        assert "nc:PersonType" in pn["containingTypes"]

    def test_object_property_type(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        pn = next(p for p in props if p["qualifiedProperty"] == "nc:PersonName")
        assert pn["qualifiedType"] == "nc:PersonNameType"

    def test_data_property_type(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        bd = next(p for p in props if p["qualifiedProperty"] == "nc:PersonBirthDate")
        assert bd["qualifiedType"] == "xs:date"


# ─── Property Index ──────────────────────────────────────────────────────

class TestBuildPropertyIndex:
    def test_grouped_by_namespace(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        index = build_property_index(props)
        assert "nc" in index
        assert "ext" in index
        assert index["nc"]["propertyCount"] == 2
        assert index["ext"]["propertyCount"] == 1


# ─── Inheritance Chains ──────────────────────────────────────────────────

class TestBuildInheritanceChains:
    def test_single_hop(self, sample_model):
        types = extract_types(sample_model)
        build_inheritance_chains(types)
        emp = next(t for t in types if t["qname"] == "ext:EmployeeType")
        assert emp["inheritanceChain"] == ["nc:PersonType"]

    def test_no_chain(self, sample_model):
        types = extract_types(sample_model)
        build_inheritance_chains(types)
        person = next(t for t in types if t["qname"] == "nc:PersonType")
        assert person["inheritanceChain"] == []

    def test_multi_hop(self):
        """Three-level hierarchy: C extends B extends A."""
        model = CmfModel(
            classes=[
                CmfClass(class_id="x.A", name="AType", namespace_ref="x"),
                CmfClass(class_id="x.B", name="BType", namespace_ref="x",
                         sub_class_of="x.A"),
                CmfClass(class_id="x.C", name="CType", namespace_ref="x",
                         sub_class_of="x.B"),
            ],
        )
        types = extract_types(model)
        build_inheritance_chains(types)
        c = next(t for t in types if t["qname"] == "x:C")
        assert c["inheritanceChain"] == ["x:A", "x:B"]


# ─── Augmentation Map ───────────────────────────────────────────────────

class TestBuildAugmentationMap:
    def test_with_augmentations(self):
        model = CmfModel(
            namespaces=[
                CmfNamespace(
                    ns_id="ext", uri="http://ext", prefix="ext",
                    augmentations=[
                        CmfAugmentationRecord(
                            class_ref="nc.PersonType",
                            property_ref="ext.Badge",
                            is_object=True,
                            min_occurs=0,
                            max_occurs="unbounded",
                        ),
                    ],
                ),
            ],
            properties=[
                CmfProperty(prop_id="ext.Badge", name="Badge",
                            namespace_ref="ext", is_object=True,
                            class_ref="ext.BadgeType"),
            ],
        )
        aug_map = build_augmentation_map(model)
        assert "nc:PersonType" in aug_map
        assert len(aug_map["nc:PersonType"]["augProperties"]) == 1
        assert aug_map["nc:PersonType"]["augProperties"][0]["name"] == "Badge"

    def test_empty_augmentations(self, sample_model):
        aug_map = build_augmentation_map(sample_model)
        assert aug_map == {}


# ─── Enrich with Codelists ───────────────────────────────────────────────

class TestEnrichWithCodelists:
    def test_match_code_simple_type(self):
        types = [{"qname": "ext:StatusCodeSimpleType", "pattern": "simple_value"}]
        codelists = {"Status": [{"value": "Active", "definition": ""}]}
        count = enrich_with_codelists(types, codelists)
        assert count == 1
        assert "facets" in types[0]

    def test_no_match(self):
        types = [{"qname": "ext:PersonType", "pattern": "object"}]
        codelists = {"Status": [{"value": "Active", "definition": ""}]}
        count = enrich_with_codelists(types, codelists)
        assert count == 0

    def test_empty_codelists(self):
        types = [{"qname": "ext:PersonType", "pattern": "object"}]
        count = enrich_with_codelists(types, {})
        assert count == 0


# ─── Catalog Assembly ────────────────────────────────────────────────────

class TestBuildCatalog:
    def test_required_keys(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        build_inheritance_chains(types)
        ns_map = extract_namespaces(sample_model)
        aug_map = build_augmentation_map(sample_model)
        prop_idx = build_property_index(props)

        cat = build_catalog(types, props, ns_map, aug_map, prop_idx,
                            "test", "1.0", ["test.cmf"], 0)

        required_keys = {"version", "description", "generatedAt", "sources",
                         "actions", "typePatterns", "stats", "namespaces",
                         "propertyIndex", "augmentationMap", "types"}
        assert required_keys <= set(cat.keys())

    def test_actions(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        ns_map = extract_namespaces(sample_model)
        cat = build_catalog(types, props, ns_map, {}, {}, "test", "1.0", [], 0)
        assert set(cat["actions"].keys()) == {"reuse", "extend", "augment"}

    def test_type_patterns_reflect_model(self, sample_model):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        ns_map = extract_namespaces(sample_model)
        cat = build_catalog(types, props, ns_map, {}, {}, "test", "1.0", [], 0)
        # Model has object and association types
        assert "object" in cat["typePatterns"]
        assert "association" in cat["typePatterns"]


# ─── Summary and Directory ───────────────────────────────────────────────

class TestBuildCatalogSummary:
    def test_grouped_by_namespace(self, sample_model):
        types = extract_types(sample_model)
        summary = build_catalog_summary(types)
        assert "nc" in summary
        assert "ext" in summary

    def test_type_count(self, sample_model):
        types = extract_types(sample_model)
        summary = build_catalog_summary(types)
        nc_types = summary["nc"]["types"]
        assert len(nc_types) == 1  # PersonType


class TestBuildTypeDirectory:
    def test_header_and_lines(self, sample_model):
        types = extract_types(sample_model)
        directory = build_type_directory(types)
        lines = directory.strip().split("\n")
        assert lines[0].startswith("# Type Directory")
        # 4 header lines + 3 types
        assert len(lines) == 7

    def test_pipe_separated(self, sample_model):
        types = extract_types(sample_model)
        directory = build_type_directory(types)
        data_lines = [l for l in directory.strip().split("\n") if not l.startswith("#")]
        for line in data_lines:
            assert "|" in line


# ─── Definition Quality Report ───────────────────────────────────────────

class TestDefinitionQualityReport:
    def test_coverage(self, sample_model, capsys):
        types = extract_types(sample_model)
        props = extract_properties(sample_model, types)
        report = definition_quality_report(types, props, "test")
        assert report["types"]["total"] == 3
        assert report["types"]["withDefinitions"] == 3
        assert report["properties"]["total"] == 3

    def test_missing_definitions(self, capsys):
        types = [
            {"qname": "x:A", "definition": "Has def"},
            {"qname": "x:B", "definition": ""},
        ]
        props = [{"qualifiedProperty": "x:p1", "definition": ""}]
        report = definition_quality_report(types, props, "test")
        assert report["types"]["missingCount"] == 1
        assert report["properties"]["missingCount"] == 1
