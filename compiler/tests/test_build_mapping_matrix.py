#!/usr/bin/env python3
"""Tests for Stage 4: build_mapping_matrix.py

Covers schema transformation from alignment report to mapping matrix.
No reasoning — just verifies fields carry through correctly.
"""

import pytest
from ontology_mapper.build_mapping_matrix import (
    build_mapping_entry,
    _build_property_mappings,
    build_decision_log,
    compute_summary,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

REUSE_ENTRY = {
    "sourceConcept": "court:Case",
    "sourceDefinition": "A court case.",
    "sourcePath": "court:Case",
    "action": "reuse",
    "actionRationale": "All properties found on target type.",
    "targetType": "j:CaseType",
    "targetDefinition": "A NIEM case type.",
    "targetPath": "nc:ActivityType/j:CaseType",
    "rationale": "Both represent court cases.",
    "properties": [
        {
            "sourceProperty": "court:caseNumber",
            "sourceDefinition": "The case number.",
            "sourcePath": "court:Case/court:caseNumber",
            "targetProperty": "j:CaseNumberText",
            "targetDefinition": "A case number.",
            "targetPath": "j:CaseType/j:CaseNumberText",
            "propertyAction": "reuse-property",
            "rationale": "Both represent case identifiers.",
        },
        {
            "sourceProperty": "court:filingDate",
            "sourceDefinition": "Date case was filed.",
            "sourcePath": "court:Case/court:filingDate",
            "targetProperty": None,
            "targetDefinition": None,
            "targetPath": None,
            "propertyAction": "create-property",
            "newPropertyName": "court-edge:CaseFilingDate",
            "rationale": "No equivalent in target.",
        },
    ],
}

EXTEND_ENTRY = {
    "sourceConcept": "court:SpecialCase",
    "sourceDefinition": "A specialized case.",
    "sourcePath": "court:SpecialCase",
    "action": "extend",
    "actionRationale": "Most properties not found in target.",
    "targetType": "j:CaseType",
    "targetDefinition": "A NIEM case type.",
    "targetPath": "nc:ActivityType/j:CaseType",
    "rationale": "Source is more specific.",
    "extensionType": "court-edge:SpecialCaseType",
    "baseType": "j:CaseType",
    "properties": [],
}

AUGMENT_ENTRY = {
    "sourceConcept": "court:Person",
    "sourceDefinition": "A person in court.",
    "sourcePath": "court:Person",
    "action": "augment",
    "actionRationale": ">=50% of unmatched properties exist elsewhere in NIEM.",
    "targetType": "nc:PersonType",
    "targetDefinition": "A NIEM person.",
    "targetPath": "nc:PersonType",
    "rationale": "Semantically equivalent.",
    "augmentationType": "court-edge:PersonAugmentationType",
    "augmentsType": "nc:PersonType",
    "properties": [
        {
            "sourceProperty": "court:personName",
            "sourceDefinition": "Full name.",
            "sourcePath": "court:Person/court:personName",
            "targetProperty": "nc:PersonName",
            "targetDefinition": "A name of a person.",
            "targetPath": "nc:PersonType/nc:PersonName",
            "propertyAction": "reuse-property",
            "rationale": "Direct match.",
        },
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# build_mapping_entry
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildMappingEntry:

    def test_reuse_carries_all_fields(self):
        m = build_mapping_entry(REUSE_ENTRY)
        assert m["sourceConcept"] == "court:Case"
        assert m["sourceDefinition"] == "A court case."
        assert m["sourcePath"] == "court:Case"
        assert m["action"] == "reuse"
        assert m["actionRationale"] == "All properties found on target type."
        assert m["targetType"] == "j:CaseType"
        assert m["targetDefinition"] == "A NIEM case type."
        assert m["targetPath"] == "nc:ActivityType/j:CaseType"
        assert m["rationale"] == "Both represent court cases."
        assert m["reviewStatus"] == "pending-review"

    def test_reuse_carries_property_mappings(self):
        m = build_mapping_entry(REUSE_ENTRY)
        assert len(m["propertyMappings"]) == 2

    def test_extend_carries_scaffolding(self):
        m = build_mapping_entry(EXTEND_ENTRY)
        assert m["extensionType"] == "court-edge:SpecialCaseType"
        assert m["baseType"] == "j:CaseType"

    def test_augment_carries_scaffolding(self):
        m = build_mapping_entry(AUGMENT_ENTRY)
        assert m["augmentationType"] == "court-edge:PersonAugmentationType"
        assert m["augmentsType"] == "nc:PersonType"

    def test_carries_target_definition_hash(self):
        entry = {**REUSE_ENTRY, "targetDefinitionHash": "a1b2c3d4e5f67890"}
        m = build_mapping_entry(entry)
        assert m["targetDefinitionHash"] == "a1b2c3d4e5f67890"

    def test_no_hash_when_absent(self):
        m = build_mapping_entry(REUSE_ENTRY)
        assert "targetDefinitionHash" not in m

    def test_no_scaffolding_for_reuse(self):
        m = build_mapping_entry(REUSE_ENTRY)
        assert "extensionType" not in m
        assert "baseType" not in m
        assert "augmentationType" not in m
        assert "augmentsType" not in m

    def test_no_property_mappings_when_empty(self):
        m = build_mapping_entry(EXTEND_ENTRY)
        assert "propertyMappings" not in m

    def test_carries_target_type_label(self):
        entry = {**REUSE_ENTRY, "targetTypeLabel": "Legal Services"}
        m = build_mapping_entry(entry)
        assert m["targetTypeLabel"] == "Legal Services"

    def test_no_label_when_absent(self):
        m = build_mapping_entry(REUSE_ENTRY)
        assert m["targetTypeLabel"] is None

    def test_pending_entry(self):
        entry = {
            "sourceConcept": "court:Thing",
            "sourceDefinition": "",
        }
        m = build_mapping_entry(entry)
        assert m["action"] == "pending"
        assert m["reviewStatus"] == "pending-review"


# ═══════════════════════════════════════════════════════════════════════════
# _build_property_mappings
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildPropertyMappings:

    def test_reuse_property_carries_fields(self):
        pms = _build_property_mappings(REUSE_ENTRY["properties"])
        reuse_pm = pms[0]
        assert reuse_pm["sourceProperty"] == "court:caseNumber"
        assert reuse_pm["action"] == "reuse-property"
        assert reuse_pm["targetProperty"] == "j:CaseNumberText"
        assert reuse_pm["targetPath"] == "j:CaseType/j:CaseNumberText"
        assert reuse_pm["reviewStatus"] == "pending-review"

    def test_create_property_carries_new_name(self):
        pms = _build_property_mappings(REUSE_ENTRY["properties"])
        create_pm = pms[1]
        assert create_pm["action"] == "create-property"
        assert create_pm["targetProperty"] is None
        assert create_pm["newPropertyName"] == "court-edge:CaseFilingDate"

    def test_carries_target_property_label(self):
        props = [{
            **REUSE_ENTRY["properties"][0],
            "targetPropertyLabel": "Case Number",
        }]
        pms = _build_property_mappings(props)
        assert pms[0]["targetPropertyLabel"] == "Case Number"

    def test_no_property_label_when_absent(self):
        pms = _build_property_mappings(REUSE_ENTRY["properties"])
        assert pms[0]["targetPropertyLabel"] is None

    def test_no_new_name_when_absent(self):
        pms = _build_property_mappings(AUGMENT_ENTRY["properties"])
        assert "newPropertyName" not in pms[0]

    def test_carries_target_definition_hash(self):
        props = [{
            "sourceProperty": "court:x",
            "sourceDefinition": "X.",
            "sourcePath": "court:Case/court:x",
            "propertyAction": "reuse-property",
            "targetProperty": "nc:X",
            "targetDefinition": "An X.",
            "targetPath": "nc:X",
            "rationale": "Match.",
            "targetDefinitionHash": "f6789012a1b2c3d4",
        }]
        pms = _build_property_mappings(props)
        assert pms[0]["targetDefinitionHash"] == "f6789012a1b2c3d4"

    def test_no_hash_when_absent(self):
        pms = _build_property_mappings(REUSE_ENTRY["properties"])
        assert "targetDefinitionHash" not in pms[0]

    def test_source_paths_carry_through(self):
        pms = _build_property_mappings(REUSE_ENTRY["properties"])
        assert pms[0]["sourcePath"] == "court:Case/court:caseNumber"
        assert pms[1]["sourcePath"] == "court:Case/court:filingDate"


# ═══════════════════════════════════════════════════════════════════════════
# build_decision_log
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildDecisionLog:

    def test_one_decision_per_entry(self):
        entries = [REUSE_ENTRY, EXTEND_ENTRY, AUGMENT_ENTRY]
        log = build_decision_log(entries)
        assert len(log) == 3

    def test_sequential_ids(self):
        log = build_decision_log([REUSE_ENTRY, EXTEND_ENTRY])
        assert log[0]["id"] == 1
        assert log[1]["id"] == 2

    def test_prefers_action_rationale(self):
        log = build_decision_log([REUSE_ENTRY])
        assert log[0]["rationale"] == "All properties found on target type."

    def test_falls_back_to_rationale(self):
        entry = {
            "sourceConcept": "court:Thing",
            "rationale": "Fallback rationale.",
        }
        log = build_decision_log([entry])
        assert log[0]["rationale"] == "Fallback rationale."

    def test_source_is_resolve_alignment(self):
        log = build_decision_log([REUSE_ENTRY])
        assert log[0]["source"] == "resolve_alignment"


# ═══════════════════════════════════════════════════════════════════════════
# compute_summary
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeSummary:

    def _build_mappings(self):
        return [
            build_mapping_entry(REUSE_ENTRY),
            build_mapping_entry(EXTEND_ENTRY),
            build_mapping_entry(AUGMENT_ENTRY),
        ]

    def test_total_concepts(self):
        s = compute_summary(self._build_mappings())
        assert s["totalConcepts"] == 3

    def test_action_counts(self):
        s = compute_summary(self._build_mappings())
        assert s["actionCounts"] == {"reuse": 1, "extend": 1, "augment": 1}

    def test_all_pending_review(self):
        s = compute_summary(self._build_mappings())
        assert s["pendingReview"] == 3

    def test_property_stats(self):
        s = compute_summary(self._build_mappings())
        ps = s["propertyStats"]
        # REUSE_ENTRY has 2 props (1 reuse, 1 create), AUGMENT_ENTRY has 1 (reuse)
        assert ps["total"] == 3
        assert ps["reuseProperty"] == 2
        assert ps["createProperty"] == 1

    def test_ask_human_property_counted(self):
        entry = {
            "sourceConcept": "court:Hearing",
            "action": "extend",
            "properties": [
                {
                    "sourceProperty": "court:judge",
                    "propertyAction": "human-must-decide",
                    "targetProperty": "[undecided]",
                },
            ],
        }
        mappings = [build_mapping_entry(entry)]
        s = compute_summary(mappings)
        assert s["propertyStats"]["humanMustDecide"] == 1
        assert s["propertyStats"]["total"] == 1

    def test_empty_mappings(self):
        s = compute_summary([])
        assert s["totalConcepts"] == 0
        assert s["actionCounts"] == {}
        assert s["propertyStats"]["total"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
