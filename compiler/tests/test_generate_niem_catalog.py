#!/usr/bin/env python3
"""Tests for generate_niem_catalog.py — Property.csv parsing, resolution, and augmentation map."""

import pytest
from ontology_mapper.generate_niem_catalog import (
    build_augmentation_map,
    build_catalog_summary,
    build_type_directory,
    compute_terminal_types,
    format_type_directory,
    parse_property_csv,
    resolve_property_definition,
    DIRECTORY_EXCLUDE_PATTERNS,
    EXCLUDE_NAMESPACES,
    INCLUDE_EXTRA_TYPES,
    INCLUDE_PATTERNS,
    TERMINAL_PATTERNS,
)


class TestParsePropertyCsv:
    """Tests for parse_property_csv()."""

    SAMPLE_ROWS = [
        {
            "QualifiedProperty": "nc:PersonName",
            "Definition": "A name of a person.",
            "QualifiedType": "nc:PersonNameType",
            "IsAbstract": "0",
            "SubstitutionGroupQualifiedProperty": "",
        },
        {
            "QualifiedProperty": "nc:PersonBirthDate",
            "Definition": "A date of birth of a person.",
            "QualifiedType": "nc:DateType",
            "IsAbstract": "0",
            "SubstitutionGroupQualifiedProperty": "",
        },
        {
            "QualifiedProperty": "j:ArrestCharge",
            "Definition": "A charge associated with an arrest.",
            "QualifiedType": "j:ChargeType",
            "IsAbstract": "0",
            "SubstitutionGroupQualifiedProperty": "",
        },
        {
            "QualifiedProperty": "nc:CountryRepresentation",
            "Definition": "A representation of a country.",
            "QualifiedType": "",
            "IsAbstract": "1",
            "SubstitutionGroupQualifiedProperty": "",
        },
        {
            "QualifiedProperty": "genc:CountryAlpha2Code",
            "Definition": "A country code.",
            "QualifiedType": "genc:CountryAlpha2CodeType",
            "IsAbstract": "0",
            "SubstitutionGroupQualifiedProperty": "nc:CountryRepresentation",
        },
    ]

    def test_parses_basic_properties(self):
        result = parse_property_csv(self.SAMPLE_ROWS)
        assert "PersonName" in result
        assert len(result["PersonName"]) == 1
        assert result["PersonName"][0]["qualifiedProperty"] == "nc:PersonName"
        assert result["PersonName"][0]["definition"] == "A name of a person."

    def test_parses_type(self):
        result = parse_property_csv(self.SAMPLE_ROWS)
        assert result["PersonName"][0]["qualifiedType"] == "nc:PersonNameType"

    def test_parses_abstract_flag(self):
        result = parse_property_csv(self.SAMPLE_ROWS)
        assert result["CountryRepresentation"][0]["isAbstract"] is True
        assert result["PersonName"][0]["isAbstract"] is False

    def test_parses_substitution_group(self):
        result = parse_property_csv(self.SAMPLE_ROWS)
        assert result["CountryAlpha2Code"][0]["substitutionGroup"] == "nc:CountryRepresentation"

    def test_null_type_when_empty(self):
        result = parse_property_csv(self.SAMPLE_ROWS)
        assert result["CountryRepresentation"][0]["qualifiedType"] is None

    def test_same_name_multiple_namespaces(self):
        rows = [
            {"QualifiedProperty": "nc:Date", "Definition": "A date.", "QualifiedType": "nc:DateType",
             "IsAbstract": "0", "SubstitutionGroupQualifiedProperty": ""},
            {"QualifiedProperty": "j:Date", "Definition": "A justice date.", "QualifiedType": "j:DateType",
             "IsAbstract": "0", "SubstitutionGroupQualifiedProperty": ""},
        ]
        result = parse_property_csv(rows)
        assert len(result["Date"]) == 2
        prefixes = {d["prefix"] for d in result["Date"]}
        assert prefixes == {"nc", "j"}

    def test_skips_empty_qualified_property(self):
        rows = [{"QualifiedProperty": "", "Definition": "X", "QualifiedType": "nc:T",
                 "IsAbstract": "0", "SubstitutionGroupQualifiedProperty": ""}]
        result = parse_property_csv(rows)
        assert len(result) == 0

    def test_prefix_extraction(self):
        result = parse_property_csv(self.SAMPLE_ROWS)
        assert result["ArrestCharge"][0]["prefix"] == "j"
        assert result["PersonName"][0]["prefix"] == "nc"


class TestResolvePropertyDefinition:
    """Tests for resolve_property_definition()."""

    @pytest.fixture
    def lookup(self):
        return parse_property_csv([
            {"QualifiedProperty": "nc:PersonName", "Definition": "NC name.",
             "QualifiedType": "nc:PersonNameType", "IsAbstract": "0",
             "SubstitutionGroupQualifiedProperty": ""},
            {"QualifiedProperty": "j:PersonName", "Definition": "J name.",
             "QualifiedType": "j:PersonNameType", "IsAbstract": "0",
             "SubstitutionGroupQualifiedProperty": ""},
            {"QualifiedProperty": "j:ArrestCharge", "Definition": "A charge.",
             "QualifiedType": "j:ChargeType", "IsAbstract": "0",
             "SubstitutionGroupQualifiedProperty": ""},
        ])

    def test_prefers_same_namespace(self, lookup):
        result = resolve_property_definition("PersonName", "j", lookup)
        assert result["qualifiedProperty"] == "j:PersonName"
        assert result["definition"] == "J name."

    def test_falls_back_to_nc(self, lookup):
        # Requesting from "hs" namespace, but only nc: and j: exist
        result = resolve_property_definition("PersonName", "hs", lookup)
        assert result["qualifiedProperty"] == "nc:PersonName"

    def test_falls_back_to_first_when_no_nc(self, lookup):
        result = resolve_property_definition("ArrestCharge", "nc", lookup)
        # Only j: exists, so falls back to first candidate
        assert result["qualifiedProperty"] == "j:ArrestCharge"

    def test_returns_none_when_not_found(self, lookup):
        result = resolve_property_definition("NonExistentProperty", "nc", lookup)
        assert result is None

    def test_result_excludes_prefix_key(self, lookup):
        result = resolve_property_definition("ArrestCharge", "j", lookup)
        assert "prefix" not in result
        assert "qualifiedProperty" in result
        assert "definition" in result
        assert "qualifiedType" in result


class TestExcludeNamespaces:
    """Tests for namespace exclusion configuration."""

    def test_mo_excluded(self):
        assert "mo" in EXCLUDE_NAMESPACES

    def test_usmtf_excluded(self):
        assert "usmtf" in EXCLUDE_NAMESPACES

    def test_core_namespaces_not_excluded(self):
        for ns in ("nc", "j", "hs"):
            assert ns not in EXCLUDE_NAMESPACES


class TestIncludePatterns:
    """Tests for type pattern inclusion configuration — all NIEM patterns included."""

    @pytest.mark.parametrize("pattern", [
        "object", "augmentation", "association", "complex_value",
        "simple_value", "simple_list", "simple_union", "metadata",
    ])
    def test_includes_all_niem_patterns(self, pattern):
        assert pattern in INCLUDE_PATTERNS


class TestIncludeExtraTypes:
    """Tests for extra type inclusion configuration."""

    def test_structures_object_type_included(self):
        assert "structures:ObjectType" in INCLUDE_EXTRA_TYPES


class TestBuildCatalogSummary:
    """Tests for build_catalog_summary()."""

    @pytest.fixture
    def ns_map(self):
        return {
            "nc": {"prefix": "nc", "name": "niem-core", "uri": "https://docs.oasis-open.org/niemopen/ns/model/niem-core/6.0/", "category": "core"},
            "j": {"prefix": "j", "name": "justice", "uri": "https://docs.oasis-open.org/niemopen/ns/model/domains/justice/6.0/", "category": "domain"},
        }

    @pytest.fixture
    def sample_types(self):
        return [
            {"qname": "nc:PersonType", "pattern": "object", "definition": "A person.", "baseType": "structures:ObjectType", "properties": ["PersonName"]},
            {"qname": "nc:ActivityType", "pattern": "object", "definition": "An activity.", "baseType": "structures:ObjectType", "properties": []},
            {"qname": "j:CaseType", "pattern": "object", "definition": "A case.", "baseType": "nc:CaseType", "properties": ["CaseCourt"]},
            {"qname": "j:CaseAugmentationType", "pattern": "augmentation", "definition": "Augments case.", "baseType": None, "properties": ["CaseCourt"]},
            {"qname": "nc:PersonAssociationType", "pattern": "association", "definition": "An association.", "baseType": "nc:AssociationType", "properties": []},
            {"qname": "nc:DateType", "pattern": "complex_value", "definition": "A date.", "baseType": None, "properties": ["DateRepresentation"]},
            {"qname": "nc:PersonSexCodeSimpleType", "pattern": "simple_value", "definition": "A code for sex.", "baseType": None, "properties": []},
            {"qname": "nc:TokenListSimpleType", "pattern": "simple_list", "definition": "A list of tokens.", "baseType": None, "properties": []},
            {"qname": "nc:DateRepresentationType", "pattern": "simple_union", "definition": "A union of date types.", "baseType": None, "properties": []},
            {"qname": "nc:MetadataType", "pattern": "metadata", "definition": "Metadata about data.", "baseType": None, "properties": ["ReportedDate"]},
        ]

    def test_excludes_augmentation_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "j:CaseAugmentationType" not in all_qnames

    def test_includes_object_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "nc:PersonType" in all_qnames
        assert "j:CaseType" in all_qnames

    def test_includes_association_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "nc:PersonAssociationType" in all_qnames

    def test_includes_complex_value_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "nc:DateType" in all_qnames

    def test_includes_simple_value_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "nc:PersonSexCodeSimpleType" in all_qnames

    def test_includes_simple_list_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "nc:TokenListSimpleType" in all_qnames

    def test_includes_simple_union_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "nc:DateRepresentationType" in all_qnames

    def test_includes_metadata_types(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        all_qnames = [t["qname"] for ns in summary.values() for t in ns["types"]]
        assert "nc:MetadataType" in all_qnames

    def test_groups_by_namespace(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        assert "nc" in summary
        assert "j" in summary
        nc_qnames = {t["qname"] for t in summary["nc"]["types"]}
        assert "nc:PersonType" in nc_qnames
        assert "j:CaseType" not in nc_qnames

    def test_includes_property_count(self, sample_types, ns_map):
        summary = build_catalog_summary(sample_types, ns_map)
        person = [t for t in summary["nc"]["types"] if t["qname"] == "nc:PersonType"][0]
        assert person["propertyCount"] == 1

    def test_empty_catalog(self):
        summary = build_catalog_summary([], {})
        assert summary == {}


class TestComputeTerminalTypes:
    """Tests for compute_terminal_types()."""

    def test_includes_structures_object_type(self):
        terminals = compute_terminal_types([])
        assert "structures:ObjectType" in terminals

    def test_includes_complex_value_types(self):
        types = [{"qname": "nc:TextType", "pattern": "complex_value"}]
        terminals = compute_terminal_types(types)
        assert "nc:TextType" in terminals

    def test_includes_simple_value_types(self):
        types = [{"qname": "j:SexCodeSimpleType", "pattern": "simple_value"}]
        terminals = compute_terminal_types(types)
        assert "j:SexCodeSimpleType" in terminals

    def test_includes_simple_list_types(self):
        types = [{"qname": "nc:TokenListSimpleType", "pattern": "simple_list"}]
        terminals = compute_terminal_types(types)
        assert "nc:TokenListSimpleType" in terminals

    def test_includes_simple_union_types(self):
        types = [{"qname": "nc:DateRepresentationType", "pattern": "simple_union"}]
        terminals = compute_terminal_types(types)
        assert "nc:DateRepresentationType" in terminals

    def test_excludes_object_types(self):
        types = [
            {"qname": "nc:PersonType", "pattern": "object"},
            {"qname": "nc:TextType", "pattern": "complex_value"},
        ]
        terminals = compute_terminal_types(types)
        assert "nc:PersonType" not in terminals
        assert "nc:TextType" in terminals

    def test_excludes_association_types(self):
        types = [{"qname": "nc:PersonAssociationType", "pattern": "association"}]
        terminals = compute_terminal_types(types)
        assert "nc:PersonAssociationType" not in terminals

    def test_excludes_augmentation_types(self):
        types = [{"qname": "j:CaseAugmentationType", "pattern": "augmentation"}]
        terminals = compute_terminal_types(types)
        assert "j:CaseAugmentationType" not in terminals

    def test_excludes_metadata_types(self):
        types = [{"qname": "nc:MetadataType", "pattern": "metadata"}]
        terminals = compute_terminal_types(types)
        assert "nc:MetadataType" not in terminals

    def test_returns_frozenset(self):
        terminals = compute_terminal_types([])
        assert isinstance(terminals, frozenset)

    def test_terminal_patterns_has_four_value_patterns(self):
        assert TERMINAL_PATTERNS == {"complex_value", "simple_value", "simple_list", "simple_union"}


class TestBuildTypeDirectory:
    """Tests for build_type_directory() and format_type_directory()."""

    @pytest.fixture
    def sample_types(self):
        return [
            {"qname": "nc:PersonType", "pattern": "object", "definition": "A data type for a human being.", "baseType": "structures:ObjectType", "properties": ["PersonName", "PersonBirthDate", "PersonSex"]},
            {"qname": "j:CaseType", "pattern": "object", "definition": "A data type for a set of related court proceedings.", "baseType": "nc:CaseType", "properties": ["CaseCourt", "CaseJudge"]},
            {"qname": "j:CaseAugmentationType", "pattern": "augmentation", "definition": "Augments case.", "baseType": None, "properties": ["CaseCourt"]},
            {"qname": "nc:PersonAssociationType", "pattern": "association", "definition": "An association between persons.", "baseType": "nc:AssociationType", "properties": []},
            {"qname": "nc:DateType", "pattern": "complex_value", "definition": "A data type for a date.", "baseType": None, "properties": ["DateRepresentation"]},
            {"qname": "nc:PersonSexCodeSimpleType", "pattern": "simple_value", "definition": "A code for sex.", "baseType": None, "properties": []},
            {"qname": "nc:TokenListSimpleType", "pattern": "simple_list", "definition": "A list.", "baseType": None, "properties": []},
            {"qname": "nc:DateRepresentationType", "pattern": "simple_union", "definition": "A union.", "baseType": None, "properties": []},
            {"qname": "nc:MetadataType", "pattern": "metadata", "definition": "Metadata.", "baseType": None, "properties": ["ReportedDate"]},
        ]

    def test_excludes_augmentation_types(self, sample_types):
        directory = build_type_directory(sample_types)
        qnames = [e["qname"] for e in directory]
        assert "j:CaseAugmentationType" not in qnames

    def test_includes_all_non_augmentation_patterns(self, sample_types):
        directory = build_type_directory(sample_types)
        qnames = {e["qname"] for e in directory}
        assert "nc:PersonType" in qnames
        assert "j:CaseType" in qnames
        assert "nc:PersonAssociationType" in qnames
        assert "nc:DateType" in qnames
        assert "nc:PersonSexCodeSimpleType" in qnames
        assert "nc:TokenListSimpleType" in qnames
        assert "nc:DateRepresentationType" in qnames
        assert "nc:MetadataType" in qnames

    def test_sorted_by_qname(self, sample_types):
        directory = build_type_directory(sample_types)
        qnames = [e["qname"] for e in directory]
        assert qnames == sorted(qnames)

    def test_truncates_long_definitions(self):
        types = [{"qname": "nc:TestType", "pattern": "object", "definition": "A" * 300, "baseType": None, "properties": []}]
        directory = build_type_directory(types)
        assert len(directory[0]["definition"]) == 200

    def test_top_properties_limited_to_8(self):
        props = [f"Prop{i}" for i in range(15)]
        types = [{"qname": "nc:BigType", "pattern": "object", "definition": "Big.", "baseType": None, "properties": props}]
        directory = build_type_directory(types)
        assert len(directory[0]["topProperties"]) == 8
        assert directory[0]["propertyCount"] == 15

    def test_property_count_reflects_all_properties(self):
        props = [f"Prop{i}" for i in range(20)]
        types = [{"qname": "nc:BigType", "pattern": "object", "definition": "Big.", "baseType": None, "properties": props}]
        directory = build_type_directory(types)
        assert directory[0]["propertyCount"] == 20

    def test_empty_catalog(self):
        directory = build_type_directory([])
        assert directory == []

    def test_preserves_base_type(self, sample_types):
        directory = build_type_directory(sample_types)
        person = [e for e in directory if e["qname"] == "nc:PersonType"][0]
        assert person["baseType"] == "structures:ObjectType"

    def test_preserves_pattern(self, sample_types):
        directory = build_type_directory(sample_types)
        assoc = [e for e in directory if e["qname"] == "nc:PersonAssociationType"][0]
        assert assoc["pattern"] == "association"

    def test_format_produces_text(self, sample_types):
        directory = build_type_directory(sample_types)
        text = format_type_directory(directory)
        assert isinstance(text, str)
        assert text.endswith("\n")

    def test_format_header_includes_count(self, sample_types):
        directory = build_type_directory(sample_types)
        text = format_type_directory(directory)
        assert f"# Total: {len(directory)} types" in text

    def test_format_has_one_line_per_type(self, sample_types):
        directory = build_type_directory(sample_types)
        text = format_type_directory(directory)
        data_lines = [l for l in text.strip().split("\n") if not l.startswith("#")]
        assert len(data_lines) == len(directory)

    def test_format_pipe_delimited(self, sample_types):
        directory = build_type_directory(sample_types)
        text = format_type_directory(directory)
        data_lines = [l for l in text.strip().split("\n") if not l.startswith("#")]
        for line in data_lines:
            # 6 fields separated by " | "
            fields = line.split(" | ")
            assert len(fields) == 6, f"Expected 6 fields, got {len(fields)}: {line}"

    def test_format_definition_truncated_at_120(self):
        types = [{"qname": "nc:TestType", "pattern": "object", "definition": "X" * 300, "baseType": None, "properties": []}]
        directory = build_type_directory(types)
        text = format_type_directory(directory)
        data_line = [l for l in text.strip().split("\n") if not l.startswith("#")][0]
        fields = data_line.split(" | ")
        assert len(fields) == 6
        # Definition field (index 4) should be <= 120 chars
        assert len(fields[4]) <= 120

    def test_format_escapes_pipes_in_definitions(self):
        types = [{"qname": "nc:TestType", "pattern": "object", "definition": "A|B|C type", "baseType": None, "properties": []}]
        directory = build_type_directory(types)
        text = format_type_directory(directory)
        data_line = [l for l in text.strip().split("\n") if not l.startswith("#")][0]
        fields = data_line.split(" | ")
        # Should still produce exactly 6 fields (pipes in definition replaced with /)
        assert len(fields) == 6
        assert "A/B/C type" in fields[4]

    def test_directory_exclude_patterns_matches_summary(self):
        """Directory and summary exclude the same patterns (augmentation)."""
        assert DIRECTORY_EXCLUDE_PATTERNS == {"augmentation"}


class TestBuildAugmentationMap:
    """Tests for build_augmentation_map()."""

    @pytest.fixture
    def catalog_types(self):
        return [
            {"qname": "nc:CaseType", "pattern": "object", "properties": []},
            {"qname": "nc:PersonType", "pattern": "object", "properties": []},
            {"qname": "nc:ActivityType", "pattern": "object", "properties": []},
            {
                "qname": "j:CaseAugmentationType",
                "pattern": "augmentation",
                "properties": ["CaseCourt", "CaseJudge", "CaseAugmentationPoint"],
            },
            {
                "qname": "j:PersonAugmentationType",
                "pattern": "augmentation",
                "properties": ["DriverLicense", "PersonAdultIndicator", "PersonAugmentationPoint"],
            },
            {
                "qname": "hs:PersonAugmentationType",
                "pattern": "augmentation",
                "properties": ["Case", "Eligibility"],
            },
        ]

    @pytest.fixture
    def type_properties(self):
        return {
            "j:CaseAugmentationType": ["CaseCourt", "CaseJudge", "CaseAugmentationPoint"],
            "j:PersonAugmentationType": ["DriverLicense", "PersonAdultIndicator", "PersonAugmentationPoint"],
            "hs:PersonAugmentationType": ["Case", "Eligibility"],
        }

    def test_maps_case_augmentation(self, catalog_types, type_properties):
        aug_map, count = build_augmentation_map(catalog_types, type_properties)
        assert "nc:CaseType" in aug_map
        case_augs = aug_map["nc:CaseType"]
        assert len(case_augs) == 1
        assert case_augs[0]["augType"] == "j:CaseAugmentationType"

    def test_excludes_augmentation_point_properties(self, catalog_types, type_properties):
        aug_map, _ = build_augmentation_map(catalog_types, type_properties)
        case_props = aug_map["nc:CaseType"][0]["properties"]
        assert "CaseAugmentationPoint" not in case_props
        assert "CaseCourt" in case_props
        assert "CaseJudge" in case_props

    def test_multiple_augmentations_for_same_base(self, catalog_types, type_properties):
        aug_map, _ = build_augmentation_map(catalog_types, type_properties)
        person_augs = aug_map["nc:PersonType"]
        aug_types = {a["augType"] for a in person_augs}
        assert "j:PersonAugmentationType" in aug_types
        assert "hs:PersonAugmentationType" in aug_types

    def test_count_matches_augmentation_types(self, catalog_types, type_properties):
        _, count = build_augmentation_map(catalog_types, type_properties)
        # j:CaseAugmentationType, j:PersonAugmentationType, hs:PersonAugmentationType
        assert count == 3

    def test_empty_catalog(self):
        aug_map, count = build_augmentation_map([], {})
        assert aug_map == {}
        assert count == 0

    def test_augmentation_with_no_properties_excluded(self):
        catalog_types = [
            {"qname": "nc:CaseType", "pattern": "object", "properties": []},
            {
                "qname": "j:CaseAugmentationType",
                "pattern": "augmentation",
                "properties": ["CaseAugmentationPoint"],
            },
        ]
        type_properties = {
            "j:CaseAugmentationType": ["CaseAugmentationPoint"],
        }
        aug_map, count = build_augmentation_map(catalog_types, type_properties)
        # After filtering out AugmentationPoint, no properties remain
        assert "nc:CaseType" not in aug_map
        assert count == 0

    def test_prefers_nc_base_over_other_namespaces(self):
        """When multiple types have the same local name, prefer nc:."""
        catalog_types = [
            {"qname": "nc:ItemType", "pattern": "object", "properties": []},
            {"qname": "custom:ItemType", "pattern": "object", "properties": []},
            {
                "qname": "j:ItemAugmentationType",
                "pattern": "augmentation",
                "properties": ["ItemDetail"],
            },
        ]
        type_properties = {"j:ItemAugmentationType": ["ItemDetail"]}
        aug_map, _ = build_augmentation_map(catalog_types, type_properties)
        assert "nc:ItemType" in aug_map
        assert "custom:ItemType" not in aug_map

    def test_sorted_augmentation_entries(self, catalog_types, type_properties):
        aug_map, _ = build_augmentation_map(catalog_types, type_properties)
        person_augs = aug_map["nc:PersonType"]
        aug_type_names = [a["augType"] for a in person_augs]
        assert aug_type_names == sorted(aug_type_names)

    def test_sorted_properties_within_augmentation(self, catalog_types, type_properties):
        aug_map, _ = build_augmentation_map(catalog_types, type_properties)
        for augs in aug_map.values():
            for aug in augs:
                assert aug["properties"] == sorted(aug["properties"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
