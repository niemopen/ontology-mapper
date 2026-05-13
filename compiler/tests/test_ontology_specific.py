#!/usr/bin/env python3
"""Tests for ontology_specific.py — ontology-specific logic."""

import pytest
from ontology_mapper.ontology_specific import (
    resolve_alignment,
    reclassify_for_target_type_change,
    _classify_niem_properties,
    _determine_niem_action,
    _local_name,
    _niem_augmentation_type_name,
    _resolve_property_actions,
)


# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def type_lookup():
    """Minimal type_lookup simulating catalog entries."""
    return {
        "nc:CaseType": {
            "qname": "nc:CaseType",
            "pattern": "object",
            "baseType": "nc:ActivityType",
            "inheritanceChain": ["nc:ActivityType", "structures:ObjectType"],
            "properties": ["CaseTrackingID", "CaseTitleText", "CaseAugmentationPoint"],
            "propertyDefinitions": {
                "CaseTrackingID": {
                    "qualifiedProperty": "nc:CaseTrackingID",
                    "definition": "An identifier for a case.",
                    "qualifiedType": "nc:IdentificationType",
                },
                "CaseTitleText": {
                    "qualifiedProperty": "nc:CaseTitleText",
                    "definition": "A title for a case.",
                    "qualifiedType": "nc:TextType",
                },
            },
        },
        "nc:ActivityType": {
            "qname": "nc:ActivityType",
            "pattern": "object",
            "baseType": "structures:ObjectType",
            "inheritanceChain": ["structures:ObjectType"],
            "properties": ["ActivityDate", "ActivityName"],
            "propertyDefinitions": {
                "ActivityDate": {
                    "qualifiedProperty": "nc:ActivityDate",
                    "definition": "A date of an activity.",
                    "qualifiedType": "nc:DateType",
                },
                "ActivityName": {
                    "qualifiedProperty": "nc:ActivityName",
                    "definition": "A name of an activity.",
                    "qualifiedType": "nc:TextType",
                },
            },
        },
        "j:CaseAugmentationType": {
            "qname": "j:CaseAugmentationType",
            "pattern": "augmentation",
            "baseType": None,
            "properties": ["CaseCourt", "CaseJudge", "CaseCharge"],
            "propertyDefinitions": {
                "CaseCourt": {
                    "qualifiedProperty": "j:CaseCourt",
                    "definition": "A court of a case.",
                    "qualifiedType": "j:CourtType",
                },
                "CaseJudge": {
                    "qualifiedProperty": "j:CaseJudge",
                    "definition": "A judge of a case.",
                    "qualifiedType": "j:JudicialOfficialType",
                },
                "CaseCharge": {
                    "qualifiedProperty": "j:CaseCharge",
                    "definition": "A charge in a case.",
                    "qualifiedType": "j:ChargeType",
                },
            },
        },
        "j:ActivityAugmentationType": {
            "qname": "j:ActivityAugmentationType",
            "pattern": "augmentation",
            "baseType": None,
            "properties": ["ActivityOfficial", "CaseLinkage"],
            "propertyDefinitions": {
                "ActivityOfficial": {
                    "qualifiedProperty": "j:ActivityOfficial",
                    "definition": "An official for an activity.",
                    "qualifiedType": "j:EnforcementOfficialType",
                },
                "CaseLinkage": {
                    "qualifiedProperty": "j:CaseLinkage",
                    "definition": "A linkage between cases.",
                    "qualifiedType": "j:CaseLinkageType",
                },
            },
        },
        "hs:PersonAugmentationType": {
            "qname": "hs:PersonAugmentationType",
            "pattern": "augmentation",
            "baseType": None,
            "properties": ["Case", "Eligibility"],
            "propertyDefinitions": {
                "Case": {
                    "qualifiedProperty": "hs:Case",
                    "definition": "A case.",
                    "qualifiedType": "nc:CaseType",
                },
                "Eligibility": {
                    "qualifiedProperty": "hs:Eligibility",
                    "definition": "An eligibility determination.",
                    "qualifiedType": "hs:EligibilityType",
                },
            },
        },
        "nc:PersonType": {
            "qname": "nc:PersonType",
            "pattern": "object",
            "baseType": "structures:ObjectType",
            "inheritanceChain": ["structures:ObjectType"],
            "properties": ["PersonName", "PersonBirthDate"],
            "propertyDefinitions": {},
        },
        "structures:ObjectType": {
            "qname": "structures:ObjectType",
            "pattern": "object",
            "baseType": None,
            "inheritanceChain": [],
            "properties": [],
            "propertyDefinitions": {},
        },
        "j:PersonSexCodeSimpleType": {
            "qname": "j:PersonSexCodeSimpleType",
            "pattern": "simple_value",
            "baseType": "niem-xs:token",
            "inheritanceChain": [],
            "properties": [],
            "propertyDefinitions": {},
        },
    }



# ─── Tests: _classify_niem_properties ──────────────────────────────────

class TestClassifyNiemProperties:
    """Tests for the three-way property classification."""

    def test_all_on_target(self):
        props = [
            {"targetProperty": "nc:ActivityDate", "targetPath": "nc:ActivityType/nc:ActivityDate"},
            {"targetProperty": "nc:ActivityName", "targetPath": "nc:ActivityType/nc:ActivityName"},
        ]
        on, els, nf = _classify_niem_properties(props, {"nc:ActivityDate", "nc:ActivityName"})
        assert (on, els, nf) == (2, 0, 0)

    def test_all_elsewhere(self):
        props = [
            {"targetProperty": "j:CaseCourt", "targetPath": "j:CaseAugmentationType/j:CaseCourt"},
            {"targetProperty": "j:CaseJudge", "targetPath": "j:CaseAugmentationType/j:CaseJudge"},
        ]
        on, els, nf = _classify_niem_properties(props, {"nc:CaseTrackingID"})
        assert (on, els, nf) == (0, 2, 0)

    def test_all_not_found(self):
        props = [
            {"targetProperty": None, "targetPath": None},
            {"targetProperty": None, "targetPath": None},
        ]
        on, els, nf = _classify_niem_properties(props, {"nc:ActivityDate"})
        assert (on, els, nf) == (0, 0, 2)

    def test_mixed_three_way(self):
        props = [
            {"targetProperty": "nc:ActivityDate", "targetPath": "nc:ActivityType/nc:ActivityDate"},
            {"targetProperty": "j:CaseCourt", "targetPath": "j:CaseAugmentationType/j:CaseCourt"},
            {"targetProperty": None, "targetPath": None},
        ]
        on, els, nf = _classify_niem_properties(props, {"nc:ActivityDate"})
        assert (on, els, nf) == (1, 1, 1)

    def test_empty_properties(self):
        on, els, nf = _classify_niem_properties([], {"nc:ActivityDate"})
        assert (on, els, nf) == (0, 0, 0)

    def test_undecided_counts_as_not_found(self):
        props = [
            {"targetProperty": "[undecided]", "targetPath": None},
            {"targetProperty": "nc:ActivityDate", "targetPath": "nc:ActivityType/nc:ActivityDate"},
        ]
        on, els, nf = _classify_niem_properties(props, {"nc:ActivityDate"})
        assert (on, els, nf) == (1, 0, 1)

    def test_empty_target_type_properties(self):
        props = [
            {"targetProperty": "nc:ActivityDate", "targetPath": "nc:ActivityType/nc:ActivityDate"},
        ]
        on, els, nf = _classify_niem_properties(props, set())
        assert (on, els, nf) == (0, 1, 0)


# ─── Tests: _determine_niem_action ─────────────────────────────────────

class TestDetermineNiemAction:
    """Tests for NIEM action threshold logic."""

    # --- Pure reuse ---
    def test_all_on_target_returns_reuse(self):
        action, rationale = _determine_niem_action(on_target=5, elsewhere=0, not_found=0)
        assert action == "reuse"
        assert "5" in rationale

    def test_one_on_target_returns_reuse(self):
        action, _ = _determine_niem_action(on_target=1, elsewhere=0, not_found=0)
        assert action == "reuse"

    # --- Pure augment (all elsewhere, none missing) ---
    def test_all_elsewhere_returns_augment(self):
        action, rationale = _determine_niem_action(on_target=0, elsewhere=4, not_found=0)
        assert action == "augment"
        assert "4 of 4" in rationale

    # --- Pure extend (all missing) ---
    def test_all_not_found_returns_extend(self):
        action, rationale = _determine_niem_action(on_target=0, elsewhere=0, not_found=4)
        assert action == "extend"
        assert "4 of 4" in rationale

    # --- 50/50 threshold: ties go to augment ---
    def test_equal_elsewhere_and_not_found_returns_augment(self):
        action, _ = _determine_niem_action(on_target=0, elsewhere=3, not_found=3)
        assert action == "augment"

    def test_50_50_with_on_target_returns_augment(self):
        action, _ = _determine_niem_action(on_target=2, elsewhere=3, not_found=3)
        assert action == "augment"

    # --- Majority elsewhere → augment ---
    def test_majority_elsewhere_returns_augment(self):
        action, _ = _determine_niem_action(on_target=1, elsewhere=4, not_found=2)
        assert action == "augment"

    # --- Majority not found → extend ---
    def test_majority_not_found_returns_extend(self):
        action, _ = _determine_niem_action(on_target=1, elsewhere=2, not_found=4)
        assert action == "extend"

    # --- Edge: one elsewhere, zero not found ---
    def test_one_elsewhere_zero_not_found_returns_augment(self):
        action, _ = _determine_niem_action(on_target=3, elsewhere=1, not_found=0)
        assert action == "augment"

    # --- Edge: zero elsewhere, one not found ---
    def test_zero_elsewhere_one_not_found_returns_extend(self):
        action, _ = _determine_niem_action(on_target=3, elsewhere=0, not_found=1)
        assert action == "extend"

    # --- Edge: no properties at all ---
    def test_zero_everything_returns_reuse(self):
        action, _ = _determine_niem_action(on_target=0, elsewhere=0, not_found=0)
        assert action == "reuse"

    # --- Rationale includes counts ---
    def test_augment_rationale_mentions_on_target(self):
        _, rationale = _determine_niem_action(on_target=2, elsewhere=3, not_found=1)
        assert "2 already on the target type" in rationale

    def test_extend_rationale_mentions_elsewhere(self):
        _, rationale = _determine_niem_action(on_target=1, elsewhere=1, not_found=4)
        assert "1 found elsewhere" in rationale

    def test_reuse_rationale_mentions_count(self):
        _, rationale = _determine_niem_action(on_target=7, elsewhere=0, not_found=0)
        assert "7" in rationale


# ─── Tests: _resolve_property_actions ──────────────────────────────────

class TestResolvePropertyActions:
    """Tests for property-level action assignment."""

    def test_reuse_property_when_target_found(self):
        props = [{"sourceProperty": "court:date", "targetProperty": "nc:ActivityDate"}]
        result = _resolve_property_actions(props, set())
        assert result[0]["propertyAction"] == "reuse-property"
        assert "newPropertyName" not in result[0]

    def test_create_property_when_target_null(self):
        props = [{"sourceProperty": "court:hearingNotes", "targetProperty": None}]
        result = _resolve_property_actions(props, set())
        assert result[0]["propertyAction"] == "create-property"
        assert result[0]["newPropertyName"] == "hearingNotes"

    def test_does_not_mutate_input(self):
        props = [{"sourceProperty": "court:foo", "targetProperty": None}]
        _resolve_property_actions(props, set())
        assert "propertyAction" not in props[0]

    def test_mixed_properties(self):
        props = [
            {"sourceProperty": "court:date", "targetProperty": "nc:ActivityDate"},
            {"sourceProperty": "court:notes", "targetProperty": None},
        ]
        result = _resolve_property_actions(props, set())
        assert result[0]["propertyAction"] == "reuse-property"
        assert result[1]["propertyAction"] == "create-property"
        assert result[1]["newPropertyName"] == "notes"

    def test_ask_human_when_target_undecided(self):
        props = [{"sourceProperty": "court:judge", "targetProperty": "[undecided]"}]
        result = _resolve_property_actions(props, set())
        assert result[0]["propertyAction"] == "human-must-decide"
        assert "newPropertyName" not in result[0]

    def test_mixed_with_undecided(self):
        props = [
            {"sourceProperty": "court:date", "targetProperty": "nc:ActivityDate"},
            {"sourceProperty": "court:judge", "targetProperty": "[undecided]"},
            {"sourceProperty": "court:notes", "targetProperty": None},
        ]
        result = _resolve_property_actions(props, set())
        assert result[0]["propertyAction"] == "reuse-property"
        assert result[1]["propertyAction"] == "human-must-decide"
        assert result[2]["propertyAction"] == "create-property"

    def test_empty_properties(self):
        assert _resolve_property_actions([], set()) == []

    def test_source_property_without_prefix(self):
        props = [{"sourceProperty": "hearingNotes", "targetProperty": None}]
        result = _resolve_property_actions(props, set())
        assert result[0]["newPropertyName"] == "hearingNotes"


# ─── Tests: naming helpers ─────────────────────────────────────────────

class TestNamingHelpers:
    def test_local_name_with_prefix(self):
        assert _local_name("nc:CaseType") == "CaseType"

    def test_local_name_without_prefix(self):
        assert _local_name("CaseType") == "CaseType"

    def test_augmentation_type_name_standard(self):
        assert _niem_augmentation_type_name("nc:PersonType") == "PersonAugmentationType"

    def test_augmentation_type_name_no_type_suffix(self):
        assert _niem_augmentation_type_name("nc:Person") == "PersonAugmentationType"

    def test_augmentation_type_name_with_prefix(self):
        assert _niem_augmentation_type_name("j:CaseType") == "CaseAugmentationType"


# ─── Tests: resolve_alignment (integration) ────────────────────────────

class TestResolveAlignment:
    """Integration tests for the full resolve_alignment dispatch."""

    @pytest.fixture
    def niem_catalog(self, type_lookup):
        """Catalog with NIEM types and actions."""
        return {
            "types": list(type_lookup.values()),
            "defaultBaseType": "structures:ObjectType",
            "actions": {
                "reuse": "Map directly to existing type.",
                "extend": "Create subclass.",
                "augment": "Contribute properties via augmentation.",
            },
        }

    @pytest.fixture
    def owl_catalog(self):
        """Minimal OWL catalog (no augmentation concept)."""
        return {
            "types": [],
            "actions": {
                "reuse": "Map directly to existing class.",
                "extend": "Create subclass.",
            },
        }

    # --- NIEM: reuse — action + no scaffolding ---
    def test_niem_reuse_all_on_target(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:CaseType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:trackingId", "targetProperty": "nc:CaseTrackingID", "targetPath": "nc:CaseType/nc:CaseTrackingID"},
                {"sourceProperty": "court:title", "targetProperty": "nc:CaseTitleText", "targetPath": "nc:CaseType/nc:CaseTitleText"},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["action"] == "reuse"
        assert "actionRationale" in result
        assert "extensionType" not in result
        assert "augmentationType" not in result
        assert "action" not in evaluation  # original not mutated

    def test_niem_reuse_properties_get_reuse_action(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:CaseType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:trackingId", "targetProperty": "nc:CaseTrackingID", "targetPath": "nc:CaseType/nc:CaseTrackingID"},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["properties"][0]["propertyAction"] == "reuse-property"

    # --- NIEM: augment — action + augmentation scaffolding ---
    def test_niem_augment_majority_elsewhere(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:HearingType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:judge", "targetProperty": "j:CaseJudge", "targetPath": "j:CaseAugmentationType/j:CaseJudge"},
                {"sourceProperty": "court:court", "targetProperty": "j:CaseCourt", "targetPath": "j:CaseAugmentationType/j:CaseCourt"},
                {"sourceProperty": "court:hearingNotes", "targetProperty": None, "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["action"] == "augment"
        assert result["augmentationType"] == "CaseAugmentationType"
        assert result["augmentsType"] == "nc:CaseType"

    def test_niem_augment_has_property_actions(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:HearingType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:judge", "targetProperty": "j:CaseJudge", "targetPath": "j:CaseAugmentationType/j:CaseJudge"},
                {"sourceProperty": "court:hearingNotes", "targetProperty": None, "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["properties"][0]["propertyAction"] == "reuse-property"
        assert result["properties"][1]["propertyAction"] == "create-property"
        assert result["properties"][1]["newPropertyName"] == "hearingNotes"

    def test_niem_augment_no_extension_scaffolding(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:HearingType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:judge", "targetProperty": "j:CaseJudge", "targetPath": "j:CaseAugmentationType/j:CaseJudge"},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert "extensionType" not in result
        assert "baseType" not in result

    # --- NIEM: extend — action + extension scaffolding ---
    def test_niem_extend_majority_not_found(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:SpecialProceedingType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:proceedingCode", "targetProperty": None, "targetPath": None},
                {"sourceProperty": "court:filingDeadline", "targetProperty": None, "targetPath": None},
                {"sourceProperty": "court:trackingId", "targetProperty": "nc:CaseTrackingID", "targetPath": "nc:CaseType/nc:CaseTrackingID"},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["action"] == "extend"
        assert result["extensionType"] == "SpecialProceedingType"
        assert result["baseType"] == "nc:CaseType"

    def test_niem_extend_has_create_properties(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:SpecialProceedingType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:proceedingCode", "targetProperty": None, "targetPath": None},
                {"sourceProperty": "court:trackingId", "targetProperty": "nc:CaseTrackingID", "targetPath": "nc:CaseType/nc:CaseTrackingID"},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        create_props = [p for p in result["properties"] if p["propertyAction"] == "create-property"]
        assert len(create_props) == 1
        assert create_props[0]["newPropertyName"] == "proceedingCode"

    def test_niem_extend_no_augmentation_scaffolding(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:SpecialProceedingType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:foo", "targetProperty": None, "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert "augmentationType" not in result
        assert "augmentsType" not in result

    # --- NIEM: preserves orchestrator fields ---
    def test_niem_preserves_evaluation_fields(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:CaseType",
            "sourceDefinition": "A legal case.",
            "sourcePath": "court:Root/court:CaseType",
            "targetType": "nc:CaseType",
            "targetDefinition": "A data type for a case.",
            "targetPath": "nc:Root/nc:CaseType",
            "rationale": "Both represent legal cases.",
            "properties": [],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["sourceConcept"] == "court:CaseType"
        assert result["sourceDefinition"] == "A legal case."
        assert result["sourcePath"] == "court:Root/court:CaseType"
        assert result["rationale"] == "Both represent legal cases."

    # --- Deep copy: does not mutate input ---
    def test_niem_does_not_mutate_input(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:CaseType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:foo", "targetProperty": None, "targetPath": None},
            ],
        }
        resolve_alignment(evaluation, "niem", niem_catalog)
        assert "action" not in evaluation
        assert "actionRationale" not in evaluation
        assert "propertyAction" not in evaluation["properties"][0]

    # --- NIEM: no properties → reuse ---
    def test_niem_no_properties_returns_reuse(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:CaseType",
            "targetType": "nc:CaseType",
            "properties": [],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["action"] == "reuse"

    # --- NIEM: unknown target type ---
    def test_niem_unknown_target_type(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:FooType",
            "targetType": "nc:UnknownType",
            "properties": [
                {"sourceProperty": "court:bar", "targetProperty": "nc:SomeProp", "targetPath": "nc:Other/nc:SomeProp"},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["action"] == "augment"

    # --- NIEM: includes inherited properties as on-target ---
    def test_niem_inherited_properties_count_as_on_target(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:CaseType",
            "targetType": "nc:CaseType",
            "properties": [
                {"sourceProperty": "court:date", "targetProperty": "nc:ActivityDate", "targetPath": "nc:ActivityType/nc:ActivityDate"},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["action"] == "reuse"

    # --- OWL: reuse ---
    def test_owl_reuse_all_found(self, owl_catalog):
        evaluation = {
            "sourceConcept": "court:Matter",
            "targetType": "folio:LegalMatter",
            "properties": [
                {"sourceProperty": "court:name", "targetProperty": "folio:matterName", "targetPath": "folio:LegalMatter/folio:matterName"},
            ],
        }
        result = resolve_alignment(evaluation, "sali-folio", owl_catalog)
        assert result["action"] == "reuse"
        assert result["properties"][0]["propertyAction"] == "reuse-property"

    # --- OWL: extend ---
    def test_owl_extend_some_missing(self, owl_catalog):
        evaluation = {
            "sourceConcept": "court:Matter",
            "targetType": "folio:LegalMatter",
            "properties": [
                {"sourceProperty": "court:name", "targetProperty": "folio:matterName", "targetPath": "folio:LegalMatter/folio:matterName"},
                {"sourceProperty": "court:priority", "targetProperty": None, "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "sali-folio", owl_catalog)
        assert result["action"] == "extend"
        assert result["extensionType"] == "Matter"
        assert result["baseType"] == "folio:LegalMatter"

    def test_owl_extend_has_create_property(self, owl_catalog):
        evaluation = {
            "sourceConcept": "court:Matter",
            "targetType": "folio:LegalMatter",
            "properties": [
                {"sourceProperty": "court:priority", "targetProperty": None, "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "sali-folio", owl_catalog)
        assert result["properties"][0]["propertyAction"] == "create-property"
        assert result["properties"][0]["newPropertyName"] == "priority"

    # --- OWL: no augment action ---
    def test_owl_never_returns_augment(self, owl_catalog):
        evaluation = {
            "sourceConcept": "court:Matter",
            "targetType": "folio:LegalMatter",
            "properties": [
                {"sourceProperty": "court:a", "targetProperty": "folio:x", "targetPath": "folio:Other/folio:x"},
                {"sourceProperty": "court:b", "targetProperty": "folio:y", "targetPath": "folio:Other/folio:y"},
                {"sourceProperty": "court:c", "targetProperty": None, "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "sali-folio", owl_catalog)
        assert result["action"] != "augment"

    # --- OWL: undecided counts as missing ---
    def test_owl_undecided_counts_as_missing(self, owl_catalog):
        evaluation = {
            "sourceConcept": "court:Matter",
            "targetType": "folio:LegalMatter",
            "properties": [
                {"sourceProperty": "court:name", "targetProperty": "folio:matterName", "targetPath": "folio:LegalMatter/folio:matterName"},
                {"sourceProperty": "court:judge", "targetProperty": "[undecided]", "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "sali-folio", owl_catalog)
        assert result["action"] == "extend"
        assert result["properties"][1]["propertyAction"] == "human-must-decide"

    # --- OWL: no properties → reuse ---
    def test_owl_no_properties_returns_reuse(self, owl_catalog):
        evaluation = {
            "sourceConcept": "court:Matter",
            "targetType": "folio:LegalMatter",
            "properties": [],
        }
        result = resolve_alignment(evaluation, "sali-folio", owl_catalog)
        assert result["action"] == "reuse"

    # --- Null targetType → extend (no match found) ---
    def test_null_target_type_returns_extend(self, niem_catalog):
        evaluation = {
            "sourceConcept": "court:UniqueConceptType",
            "targetType": None,
            "properties": [
                {"sourceProperty": "court:foo", "targetProperty": None, "targetPath": None},
            ],
        }
        result = resolve_alignment(evaluation, "niem", niem_catalog)
        assert result["action"] == "extend"
        assert result["extensionType"] == "UniqueConceptType"
        assert result["baseType"] == "structures:ObjectType"
        assert result["properties"][0]["propertyAction"] == "create-property"

    def test_null_target_type_owl(self, owl_catalog):
        evaluation = {
            "sourceConcept": "court:NoMatchType",
            "targetType": None,
            "properties": [],
        }
        result = resolve_alignment(evaluation, "sali-folio", owl_catalog)
        assert result["action"] == "extend"
        assert result["extensionType"] == "NoMatchType"
        assert "baseType" not in result


class TestReclassifyForTargetTypeChange:
    """Tests for reclassify_for_target_type_change — type cascade logic."""

    @pytest.fixture
    def niem_catalog(self, type_lookup):
        return {
            "types": list(type_lookup.values()),
            "defaultBaseType": "structures:ObjectType",
            "actions": {
                "reuse": "Map directly to existing type.",
                "extend": "Create subclass.",
                "augment": "Contribute properties via augmentation.",
            },
        }

    @pytest.fixture
    def owl_catalog(self):
        return {
            "types": [],
            "actions": {
                "reuse": "Map directly to existing class.",
                "extend": "Create subclass.",
            },
        }

    def _make_entry(self, action, target_type, property_mappings,
                    scaffolding=None):
        """Build a mapping matrix entry for testing."""
        entry = {
            "sourceConcept": "court:CaseType",
            "sourceDefinition": "A court case.",
            "action": action,
            "targetType": target_type,
            "actionRationale": "original rationale",
            "reviewStatus": "accepted",
            "ruleId": "human-review",
            "propertyMappings": property_mappings,
        }
        if scaffolding:
            entry.update(scaffolding)
        return entry

    def _props_on_case_type(self):
        """Properties that land on nc:CaseType (on-target)."""
        return [
            {
                "sourceProperty": "court:caseId",
                "targetProperty": "nc:CaseTrackingID",
                "action": "reuse-property",
                "reviewStatus": "accepted",
            },
            {
                "sourceProperty": "court:caseTitle",
                "targetProperty": "nc:CaseTitleText",
                "action": "reuse-property",
                "reviewStatus": "accepted",
            },
        ]

    def _props_mixed(self):
        """Properties: one on nc:CaseType, one elsewhere, one not found."""
        return [
            {
                "sourceProperty": "court:caseId",
                "targetProperty": "nc:CaseTrackingID",
                "action": "reuse-property",
                "reviewStatus": "accepted",
            },
            {
                "sourceProperty": "court:judge",
                "targetProperty": "j:CaseJudge",
                "action": "reuse-property",
                "reviewStatus": "accepted",
            },
            {
                "sourceProperty": "court:notes",
                "targetProperty": None,
                "action": "create-property",
                "reviewStatus": "accepted",
            },
        ]

    # --- NIEM: reuse → augment on type change ---

    def test_niem_reuse_to_augment(self, niem_catalog):
        """All props on nc:CaseType → change to nc:PersonType → elsewhere → augment."""
        entry = self._make_entry(
            "reuse", "nc:CaseType", self._props_on_case_type(),
        )
        result = reclassify_for_target_type_change(
            entry, "nc:PersonType", "niem", niem_catalog,
        )
        assert result["action"] == "augment"
        assert result["targetType"] == "nc:PersonType"
        assert result["augmentsType"] == "nc:PersonType"
        assert "augmentationType" in result
        assert "extensionType" not in result
        assert "baseType" not in result

    # --- NIEM: augment → reuse on type change ---

    def test_niem_augment_to_reuse(self, niem_catalog):
        """Props elsewhere on nc:PersonType → change to nc:CaseType → on-target → reuse."""
        entry = self._make_entry(
            "augment", "nc:PersonType", self._props_on_case_type(),
            scaffolding={
                "augmentationType": "PersonAugmentationType",
                "augmentsType": "nc:PersonType",
            },
        )
        result = reclassify_for_target_type_change(
            entry, "nc:CaseType", "niem", niem_catalog,
        )
        assert result["action"] == "reuse"
        assert result["targetType"] == "nc:CaseType"
        assert "augmentationType" not in result
        assert "augmentsType" not in result
        assert "extensionType" not in result

    # --- NIEM: augment → extend on type change ---

    def test_niem_to_extend(self, niem_catalog):
        """Majority not-found on nc:PersonType → extend."""
        props = [
            {"sourceProperty": "court:caseId", "targetProperty": "nc:CaseTrackingID",
             "action": "reuse-property", "reviewStatus": "accepted"},
            {"sourceProperty": "court:notes", "targetProperty": None,
             "action": "create-property", "reviewStatus": "accepted"},
            {"sourceProperty": "court:ref", "targetProperty": None,
             "action": "create-property", "reviewStatus": "accepted"},
        ]
        entry = self._make_entry(
            "augment", "nc:CaseType", props,
            scaffolding={
                "augmentationType": "CaseAugmentationType",
                "augmentsType": "nc:CaseType",
            },
        )
        result = reclassify_for_target_type_change(
            entry, "nc:PersonType", "niem", niem_catalog,
        )
        assert result["action"] == "extend"
        assert result["extensionType"] == "CaseType"
        assert result["baseType"] == "nc:PersonType"
        assert "augmentationType" not in result
        assert "augmentsType" not in result

    # --- Non-NIEM: reuse → extend ---

    def test_non_niem_reuse_to_extend(self, owl_catalog):
        """Non-NIEM: some props missing → extend (no augment concept)."""
        entry = self._make_entry(
            "reuse", "owl:SomeType",
            [
                {"sourceProperty": "a", "targetProperty": "b",
                 "action": "reuse-property", "reviewStatus": "accepted"},
                {"sourceProperty": "c", "targetProperty": None,
                 "action": "create-property", "reviewStatus": "accepted"},
            ],
        )
        result = reclassify_for_target_type_change(
            entry, "owl:OtherType", "sali-folio", owl_catalog,
        )
        assert result["action"] == "extend"
        assert result["extensionType"] == "CaseType"
        assert result["baseType"] == "owl:OtherType"
        assert "augmentationType" not in result

    # --- Non-NIEM: extend → reuse ---

    def test_non_niem_extend_to_reuse(self, owl_catalog):
        """Non-NIEM: all props found → reuse."""
        entry = self._make_entry(
            "extend", "owl:SomeType",
            [
                {"sourceProperty": "a", "targetProperty": "b",
                 "action": "reuse-property", "reviewStatus": "accepted"},
            ],
            scaffolding={"extensionType": "CaseType", "baseType": "owl:SomeType"},
        )
        result = reclassify_for_target_type_change(
            entry, "owl:OtherType", "sali-folio", owl_catalog,
        )
        assert result["action"] == "reuse"
        assert result["targetType"] == "owl:OtherType"
        assert "extensionType" not in result
        assert "baseType" not in result

    # --- Null target type ---

    def test_null_target_niem(self, niem_catalog):
        """NIEM: null target → extend from structures:ObjectType."""
        entry = self._make_entry(
            "reuse", "nc:CaseType", self._props_on_case_type(),
        )
        result = reclassify_for_target_type_change(
            entry, None, "niem", niem_catalog,
        )
        assert result["action"] == "extend"
        assert result["extensionType"] == "CaseType"
        assert result["baseType"] == "structures:ObjectType"
        assert result["targetType"] is None

    def test_null_target_non_niem(self, owl_catalog):
        """Non-NIEM: null target → extend, no baseType."""
        entry = self._make_entry(
            "reuse", "owl:SomeType",
            [{"sourceProperty": "a", "targetProperty": "b",
              "action": "reuse-property", "reviewStatus": "accepted"}],
        )
        result = reclassify_for_target_type_change(
            entry, None, "sali-folio", owl_catalog,
        )
        assert result["action"] == "extend"
        assert result["extensionType"] == "CaseType"
        assert "baseType" not in result

    # --- Deep copy: input not mutated ---

    def test_does_not_mutate_input(self, niem_catalog):
        entry = self._make_entry(
            "reuse", "nc:CaseType", self._props_on_case_type(),
        )
        import copy
        original = copy.deepcopy(entry)
        reclassify_for_target_type_change(
            entry, "nc:PersonType", "niem", niem_catalog,
        )
        assert entry == original

    # --- Review status reset ---

    def test_review_status_reset(self, niem_catalog):
        entry = self._make_entry(
            "reuse", "nc:CaseType", self._props_on_case_type(),
        )
        result = reclassify_for_target_type_change(
            entry, "nc:PersonType", "niem", niem_catalog,
        )
        assert result["reviewStatus"] == "pending-review"
        for pm in result["propertyMappings"]:
            assert pm["reviewStatus"] == "pending-review"

    # --- Property targetProperty preserved ---

    def test_property_matches_unchanged(self, niem_catalog):
        """targetProperty values must not change — only class-level action changes."""
        props = self._props_mixed()
        entry = self._make_entry("augment", "nc:CaseType", props)
        result = reclassify_for_target_type_change(
            entry, "nc:PersonType", "niem", niem_catalog,
        )
        original_targets = [p["targetProperty"] for p in props]
        result_targets = [p["targetProperty"] for p in result["propertyMappings"]]
        assert result_targets == original_targets

    # --- human-must-decide preserved ---

    def test_human_must_decide_preserved(self, niem_catalog):
        props = [
            {"sourceProperty": "court:caseId", "targetProperty": "nc:CaseTrackingID",
             "action": "reuse-property", "reviewStatus": "accepted"},
            {"sourceProperty": "court:judge", "targetProperty": "[undecided]",
             "action": "human-must-decide", "reviewStatus": "pending-review"},
        ]
        entry = self._make_entry("reuse", "nc:CaseType", props)
        result = reclassify_for_target_type_change(
            entry, "nc:PersonType", "niem", niem_catalog,
        )
        undecided = [p for p in result["propertyMappings"]
                     if p["action"] == "human-must-decide"]
        assert len(undecided) == 1
        assert undecided[0]["targetProperty"] == "[undecided]"

    # --- ruleId set ---

    def test_rule_id_set(self, niem_catalog):
        entry = self._make_entry(
            "reuse", "nc:CaseType", self._props_on_case_type(),
        )
        result = reclassify_for_target_type_change(
            entry, "nc:PersonType", "niem", niem_catalog,
        )
        assert result["ruleId"] == "target-type-change-cascade"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
