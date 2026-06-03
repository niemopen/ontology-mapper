#!/usr/bin/env python3
"""Tests for Stage 5 human review functions in _present_and_apply_human_review.py."""

import json
import pytest
from pathlib import Path

from runner_tools._present_and_apply_human_review import (
    ACTION_GROUPS,
    DECISIONS_FILENAME,
    PROPERTY_ACTION_LABELS,
    format_review_item,
    group_by_action,
    get_pending_items,
    get_pending_property_items,
    format_property_review,
    apply_property_decision,
    apply_all_property_accepts,
    apply_decision,
    apply_decision_with_cascade,
    apply_accept,
    validate_class_decision,
    validate_property_decision,
    recompute_summary,
    save_decisions,
    save_matrix,
    _snapshot_property_decisions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_run_dir(tmp_path):
    """Create a temporary run directory with minimal artifacts."""
    return tmp_path


@pytest.fixture
def sample_pending_items():
    """Mapping entries with pending-review status."""
    return [
        {"sourceConcept": "dbpi:Property", "action": "reuse", "targetType": "nc:IntellectualPropertyType",
         "reviewStatus": "pending-review",
         "rationale": "Both represent property concepts."},
        {"sourceConcept": "dbpi:Person", "action": "reuse", "targetType": "nc:PersonType",
         "reviewStatus": "pending-review",
         "rationale": "Exact match: both represent a human being."},
        {"sourceConcept": "dbpi:Inspection", "action": "extend", "targetType": None,
         "reviewStatus": "pending-review",
         "rationale": "No target type covers building inspections."},
        {"sourceConcept": "dbpi:Fee", "action": "extend", "targetType": None,
         "reviewStatus": "pending-review",
         "rationale": "No suitable target match."},
        {"sourceConcept": "dbpi:Zone", "action": "augment", "targetType": "nc:LocationType",
         "reviewStatus": "pending-review",
         "rationale": "Reuse target type, add zone-specific properties."},
    ]


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_action_groups_has_three_entries(self):
        assert len(ACTION_GROUPS) == 3

    def test_action_groups_order(self):
        keys = [k for k, _ in ACTION_GROUPS]
        assert keys == ["reuse", "augment", "extend"]

    def test_property_action_labels(self):
        assert "reuse-property" in PROPERTY_ACTION_LABELS
        assert "create-property" in PROPERTY_ACTION_LABELS
        assert "human-must-decide" in PROPERTY_ACTION_LABELS
        assert len(PROPERTY_ACTION_LABELS) == 3


# ---------------------------------------------------------------------------
# TestGetPendingItems
# ---------------------------------------------------------------------------
class TestGetPendingItems:
    def test_excludes_exclude_action(self):
        matrix = {"mappings": [
            {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"},
            {"sourceConcept": "a:Bar", "action": "exclude", "reviewStatus": "pending-review"},
            {"sourceConcept": "a:Baz", "action": "extend", "reviewStatus": "pending-review"},
        ]}
        pending = get_pending_items(matrix)
        concepts = [m["sourceConcept"] for m in pending]
        assert "a:Bar" not in concepts
        assert len(pending) == 2

    def test_excludes_already_decided(self):
        matrix = {"mappings": [
            {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "accepted"},
            {"sourceConcept": "a:Bar", "action": "extend", "reviewStatus": "pending-review"},
        ]}
        pending = get_pending_items(matrix)
        assert len(pending) == 1
        assert pending[0]["sourceConcept"] == "a:Bar"

    def test_returns_pending_review_items(self):
        matrix = {"mappings": [
            {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"},
            {"sourceConcept": "a:Bar", "action": "extend", "reviewStatus": "accepted"},
            {"sourceConcept": "a:Baz", "action": "augment", "reviewStatus": "pending-review"},
        ]}
        pending = get_pending_items(matrix)
        concepts = [m["sourceConcept"] for m in pending]
        assert concepts == ["a:Baz", "a:Foo"]
        assert all(m["reviewStatus"] == "pending-review" for m in pending)

    def test_sorted_by_concept(self):
        matrix = {"mappings": [
            {"sourceConcept": "z:Last", "action": "reuse", "reviewStatus": "pending-review"},
            {"sourceConcept": "a:First", "action": "reuse", "reviewStatus": "pending-review"},
        ]}
        pending = get_pending_items(matrix)
        assert pending[0]["sourceConcept"] == "a:First"

    def test_empty_mappings(self):
        matrix = {"mappings": []}
        assert get_pending_items(matrix) == []


# ---------------------------------------------------------------------------
# TestGroupByAction
# ---------------------------------------------------------------------------
class TestGroupByAction:
    def test_groups_in_action_order(self, sample_pending_items):
        groups = group_by_action(sample_pending_items)
        keys = [g[0] for g in groups]
        assert keys == ["reuse", "augment", "extend"]

    def test_correct_group_sizes(self, sample_pending_items):
        groups = group_by_action(sample_pending_items)
        by_key = {k: items for k, _, items in groups}
        assert len(by_key["reuse"]) == 2
        assert len(by_key["augment"]) == 1
        assert len(by_key["extend"]) == 2

    def test_all_items_accounted_for(self, sample_pending_items):
        groups = group_by_action(sample_pending_items)
        total = sum(len(g[2]) for g in groups)
        assert total == len(sample_pending_items)

    def test_items_sorted_within_groups(self, sample_pending_items):
        groups = group_by_action(sample_pending_items)
        for _, _, items in groups:
            concepts = [m["sourceConcept"] for m in items]
            assert concepts == sorted(concepts)

    def test_unrecognized_action_not_lost(self):
        items = [
            {"sourceConcept": "a:Foo", "action": "custom-action"},
            {"sourceConcept": "a:Bar", "action": "reuse"},
        ]
        groups = group_by_action(items)
        keys = [g[0] for g in groups]
        assert "custom-action" in keys
        total = sum(len(g[2]) for g in groups)
        assert total == 2

    def test_unknown_action_appended_after_known(self):
        items = [
            {"sourceConcept": "a:Foo", "action": "custom-action"},
            {"sourceConcept": "a:Bar", "action": "reuse"},
            {"sourceConcept": "a:Baz", "action": "augment"},
        ]
        groups = group_by_action(items)
        keys = [g[0] for g in groups]
        # Known groups come first in ACTION_GROUPS order, unknown appended
        assert keys == ["reuse", "augment", "custom-action"]

    def test_empty_input(self):
        groups = group_by_action([])
        assert groups == []


# ---------------------------------------------------------------------------
# TestFormatReviewItem
# ---------------------------------------------------------------------------
class TestFormatReviewItem:
    def test_includes_concept_action_target(self):
        entry = {"sourceConcept": "dbpi:Person", "action": "reuse",
                 "targetType": "nc:PersonType", "rationale": "Both represent people."}
        result = format_review_item(entry)
        assert "dbpi:Person" in result
        assert "reuse" in result
        assert "nc:PersonType" in result
        assert "Both represent people" in result

    def test_truncates_long_rationale(self):
        long_rationale = "a" * 200
        entry = {"sourceConcept": "dbpi:LongOne", "action": "reuse",
                 "targetType": "nc:SomeType", "rationale": long_rationale}
        result = format_review_item(entry)
        assert "..." in result
        # Full rationale should NOT appear
        assert long_rationale not in result

    def test_no_target_shows_none(self):
        entry = {"sourceConcept": "dbpi:Inspection", "action": "extend", "targetType": None}
        result = format_review_item(entry)
        assert "(none)" in result


# ---------------------------------------------------------------------------
# Property-level review fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def entry_with_properties():
    """A class mapping entry with mixed property mappings."""
    return {
        "sourceConcept": "court:Case",
        "action": "reuse",
        "targetType": "nc:CaseType",
        "propertyMappings": [
            {"sourceProperty": "CaseNumber", "action": "reuse-property", "targetProperty": "CaseDocketID",
             "reviewStatus": "pending-review",
             "sourceDefinition": "Unique case identifier.", "targetDefinition": "An ID for a case docket.",
             "rationale": "Both identify a case."},
            {"sourceProperty": "FilingDate", "action": "reuse-property", "targetProperty": "ActivityDate",
             "reviewStatus": "pending-review",
             "sourceDefinition": "Date the case was filed."},
            {"sourceProperty": "SpecialConditions", "action": "create-property", "targetProperty": None,
             "reviewStatus": "pending-review",
             "sourceDefinition": "Special conditions on the case."},
            {"sourceProperty": "JudgeName", "action": "create-property", "targetProperty": None,
             "reviewStatus": "pending-review"},
            {"sourceProperty": "AlreadyDone", "action": "reuse-property", "targetProperty": "SomeProp",
             "reviewStatus": "accepted"},
        ],
    }


# ---------------------------------------------------------------------------
# TestGetPendingPropertyItems
# ---------------------------------------------------------------------------
class TestGetPendingPropertyItems:
    def test_splits_by_action(self, entry_with_properties):
        reuse, create, must_decide = get_pending_property_items(entry_with_properties)
        # CaseNumber and FilingDate are reuse-property
        assert len(reuse) == 2
        reuse_names = {p["sourceProperty"] for p in reuse}
        assert reuse_names == {"CaseNumber", "FilingDate"}
        # SpecialConditions and JudgeName are create-property
        assert len(create) == 2
        create_names = {p["sourceProperty"] for p in create}
        assert create_names == {"SpecialConditions", "JudgeName"}
        # No human-must-decide in this fixture
        assert must_decide == []

    def test_excludes_already_decided(self, entry_with_properties):
        reuse, create, must_decide = get_pending_property_items(entry_with_properties)
        all_pending = [p["sourceProperty"] for p in reuse + create + must_decide]
        assert "AlreadyDone" not in all_pending

    def test_empty_property_mappings(self):
        entry = {"sourceConcept": "x:Foo", "propertyMappings": []}
        reuse, create, must_decide = get_pending_property_items(entry)
        assert reuse == []
        assert create == []
        assert must_decide == []

    def test_missing_property_mappings(self):
        entry = {"sourceConcept": "x:Foo"}
        reuse, create, must_decide = get_pending_property_items(entry)
        assert reuse == []
        assert create == []
        assert must_decide == []

    def test_only_pending_review_included(self):
        entry = {"sourceConcept": "x:Foo", "propertyMappings": [
            {"sourceProperty": "PropA", "action": "reuse-property", "reviewStatus": "pending-review"},
            {"sourceProperty": "PropB", "action": "create-property", "reviewStatus": "pending-review"},
            {"sourceProperty": "PropC", "action": "reuse-property", "reviewStatus": "accepted"},
        ]}
        reuse, create, must_decide = get_pending_property_items(entry)
        assert len(reuse) == 1
        assert reuse[0]["sourceProperty"] == "PropA"
        assert len(create) == 1
        assert create[0]["sourceProperty"] == "PropB"
        assert must_decide == []

    def test_human_must_decide_separated(self):
        entry = {"sourceConcept": "x:Foo", "propertyMappings": [
            {"sourceProperty": "PropA", "action": "reuse-property", "reviewStatus": "pending-review"},
            {"sourceProperty": "PropB", "action": "human-must-decide", "reviewStatus": "pending-review",
             "targetProperty": "[undecided]"},
            {"sourceProperty": "PropC", "action": "create-property", "reviewStatus": "pending-review"},
        ]}
        reuse, create, must_decide = get_pending_property_items(entry)
        assert len(reuse) == 1
        assert len(create) == 1
        assert len(must_decide) == 1
        assert must_decide[0]["sourceProperty"] == "PropB"


# ---------------------------------------------------------------------------
# TestFormatPropertyReview
# ---------------------------------------------------------------------------
class TestFormatPropertyReview:
    def test_returns_empty_for_no_properties(self):
        entry = {"sourceConcept": "x:Foo"}
        assert format_property_review(entry) == ""

    def test_returns_empty_for_empty_list(self):
        entry = {"sourceConcept": "x:Foo", "propertyMappings": []}
        assert format_property_review(entry) == ""

    def test_includes_concept_name_and_count(self, entry_with_properties):
        result = format_property_review(entry_with_properties)
        assert "court:Case" in result
        assert "5 total" in result

    def test_reuse_section(self, entry_with_properties):
        result = format_property_review(entry_with_properties)
        assert "Reuse target property" in result
        assert "CaseNumber -> CaseDocketID" in result
        assert "FilingDate -> ActivityDate" in result

    def test_create_section(self, entry_with_properties):
        result = format_property_review(entry_with_properties)
        assert "Create new property" in result
        assert "SpecialConditions" in result

    def test_already_decided_section(self, entry_with_properties):
        result = format_property_review(entry_with_properties)
        assert "Already decided" in result
        assert "AlreadyDone" in result

    def test_includes_definitions_in_create_section(self, entry_with_properties):
        result = format_property_review(entry_with_properties)
        assert "Special conditions on the case" in result

    def test_undecided_section_shown_first(self):
        entry = {"sourceConcept": "court:Case", "propertyMappings": [
            {"sourceProperty": "CaseNumber", "action": "reuse-property", "targetProperty": "CaseDocketID",
             "reviewStatus": "pending-review"},
            {"sourceProperty": "Judge", "action": "human-must-decide", "targetProperty": "[undecided]",
             "reviewStatus": "pending-review", "sourceDefinition": "The judge assigned."},
        ]}
        result = format_property_review(entry)
        assert "UNDECIDED" in result
        assert "Judge" in result
        # UNDECIDED section should appear before Reuse section
        undecided_pos = result.index("UNDECIDED")
        reuse_pos = result.index("Reuse")
        assert undecided_pos < reuse_pos


# ---------------------------------------------------------------------------
# TestApplyPropertyDecision
# ---------------------------------------------------------------------------
class TestApplyPropertyDecision:
    def test_overrides_action_and_status(self, entry_with_properties):
        result = apply_property_decision(entry_with_properties, "SpecialConditions", {
            "action": "reuse-property",
            "targetProperty": "nc:CaseDispositionText",
            "notes": "Found a match manually",
        })
        assert result is True
        prop = next(p for p in entry_with_properties["propertyMappings"] if p["sourceProperty"] == "SpecialConditions")
        assert prop["action"] == "reuse-property"
        assert prop["reviewStatus"] == "accepted"
        assert prop["targetProperty"] == "nc:CaseDispositionText"
        assert prop["notes"] == "Found a match manually"

    def test_returns_false_for_missing_property(self, entry_with_properties):
        result = apply_property_decision(entry_with_properties, "NonExistent", {"action": "reuse-property"})
        assert result is False

    def test_sets_optional_fields(self, entry_with_properties):
        apply_property_decision(entry_with_properties, "JudgeName", {
            "action": "reuse-property",
            "targetProperty": "nc:PersonName",
            "targetDefinition": "A name of a person.",
            "targetType": "nc:PersonNameType",
        })
        prop = next(p for p in entry_with_properties["propertyMappings"] if p["sourceProperty"] == "JudgeName")
        assert prop["targetDefinition"] == "A name of a person."
        assert prop["targetType"] == "nc:PersonNameType"

    def test_no_property_mappings_returns_false(self):
        entry = {"sourceConcept": "x:Foo"}
        assert apply_property_decision(entry, "bar", {"action": "reuse-property"}) is False


# ---------------------------------------------------------------------------
# TestApplyAllPropertyAccepts
# ---------------------------------------------------------------------------
class TestApplyAllPropertyAccepts:
    def test_accepts_all_pending(self, entry_with_properties):
        accepted, skipped = apply_all_property_accepts(entry_with_properties)
        assert accepted == 4  # 4 pending, 1 already decided
        assert skipped == 0
        for p in entry_with_properties["propertyMappings"]:
            assert p["reviewStatus"] == "accepted"

    def test_skips_already_decided(self, entry_with_properties):
        # Pre-decide one by setting status directly
        prop = next(p for p in entry_with_properties["propertyMappings"] if p["sourceProperty"] == "CaseNumber")
        prop["reviewStatus"] = "accepted"
        prop["confidence"] = "confident"
        accepted, skipped = apply_all_property_accepts(entry_with_properties)
        assert accepted == 3  # Only 3 remaining pending
        assert skipped == 0

    def test_returns_zero_when_none_pending(self):
        entry = {"sourceConcept": "x:Foo", "propertyMappings": [
            {"sourceProperty": "a", "action": "reuse-property", "reviewStatus": "accepted"},
        ]}
        accepted, skipped = apply_all_property_accepts(entry)
        assert accepted == 0
        assert skipped == 0

    def test_empty_property_mappings(self):
        accepted, skipped = apply_all_property_accepts({"sourceConcept": "x:Foo", "propertyMappings": []})
        assert accepted == 0
        assert skipped == 0

    def test_missing_property_mappings(self):
        accepted, skipped = apply_all_property_accepts({"sourceConcept": "x:Foo"})
        assert accepted == 0
        assert skipped == 0

    def test_skips_human_must_decide(self):
        entry = {"sourceConcept": "x:Foo", "propertyMappings": [
            {"sourceProperty": "PropA", "action": "reuse-property", "reviewStatus": "pending-review"},
            {"sourceProperty": "PropB", "action": "human-must-decide", "reviewStatus": "pending-review",
             "targetProperty": "[undecided]"},
            {"sourceProperty": "PropC", "action": "create-property", "reviewStatus": "pending-review"},
        ]}
        accepted, skipped = apply_all_property_accepts(entry)
        assert accepted == 2
        assert skipped == 1
        # human-must-decide stays pending
        prop_b = next(p for p in entry["propertyMappings"] if p["sourceProperty"] == "PropB")
        assert prop_b["reviewStatus"] == "pending-review"
        # Others are accepted
        prop_a = next(p for p in entry["propertyMappings"] if p["sourceProperty"] == "PropA")
        assert prop_a["reviewStatus"] == "accepted"


# ---------------------------------------------------------------------------
# TestApplyDecision
# ---------------------------------------------------------------------------
class TestApplyDecision:
    def test_sets_action_and_status(self):
        entry = {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"}
        apply_decision(entry, {"action": "extend", "notes": "Changed to extend"})
        assert entry["action"] == "extend"
        assert entry["reviewStatus"] == "accepted"
        assert entry["ruleId"] == "human-review"
        assert entry["notes"] == "Changed to extend"

    def test_optional_target_type(self):
        entry = {"sourceConcept": "a:Foo", "action": "extend", "reviewStatus": "pending-review"}
        apply_decision(entry, {"action": "reuse", "targetType": "nc:SomeType"})
        assert entry["targetType"] == "nc:SomeType"

    def test_optional_notes(self):
        entry = {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"}
        apply_decision(entry, {"action": "reuse", "notes": "Reviewer override"})
        assert entry["notes"] == "Reviewer override"


# ---------------------------------------------------------------------------
# TestApplyAccept
# ---------------------------------------------------------------------------
class TestApplyAccept:
    def test_marks_decided(self):
        entry = {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"}
        apply_accept(entry)
        assert entry["reviewStatus"] == "accepted"
        assert entry["action"] == "reuse"  # unchanged


# ---------------------------------------------------------------------------
# TestSnapshotPropertyDecisions
# ---------------------------------------------------------------------------
class TestSnapshotPropertyDecisions:
    def test_captures_decided_properties(self):
        matrix = {"mappings": [
            {"sourceConcept": "court:Case", "propertyMappings": [
                {"sourceProperty": "CaseNumber", "action": "reuse-property", "targetProperty": "CaseDocketID",
                 "reviewStatus": "accepted", "notes": "Manual match"},
                {"sourceProperty": "FilingDate", "action": "create-property", "targetProperty": None,
                 "reviewStatus": "accepted"},
                {"sourceProperty": "Pending", "action": "create-property", "targetProperty": None,
                 "reviewStatus": "pending-review"},
            ]},
        ]}
        result = _snapshot_property_decisions(matrix, "court:Case")
        assert len(result) == 2
        assert result[0]["sourceProperty"] == "CaseNumber"
        assert result[0]["targetProperty"] == "CaseDocketID"
        assert result[0]["notes"] == "Manual match"
        assert result[1]["sourceProperty"] == "FilingDate"

    def test_returns_none_for_no_decided(self):
        matrix = {"mappings": [
            {"sourceConcept": "court:Case", "propertyMappings": [
                {"sourceProperty": "A", "action": "reuse-property", "reviewStatus": "pending-review"},
            ]},
        ]}
        assert _snapshot_property_decisions(matrix, "court:Case") is None

    def test_returns_none_for_empty_property_mappings_list(self):
        matrix = {"mappings": [
            {"sourceConcept": "court:Case", "propertyMappings": []},
        ]}
        assert _snapshot_property_decisions(matrix, "court:Case") is None

    def test_returns_none_for_no_property_mappings(self):
        matrix = {"mappings": [
            {"sourceConcept": "court:Case"},
        ]}
        assert _snapshot_property_decisions(matrix, "court:Case") is None

    def test_returns_none_for_missing_concept(self):
        matrix = {"mappings": []}
        assert _snapshot_property_decisions(matrix, "court:Case") is None


# ---------------------------------------------------------------------------
# TestSaveMatrixPropertyDecisions
# ---------------------------------------------------------------------------
class TestSaveMatrixPropertyDecisions:
    def test_decision_log_includes_property_decisions(self, tmp_path):
        matrix = {
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType",
                 "reviewStatus": "accepted",
                 "propertyMappings": [
                     {"sourceProperty": "CaseNumber", "action": "reuse-property",
                      "targetProperty": "CaseDocketID", "reviewStatus": "accepted", "notes": "Exact match"},
                     {"sourceProperty": "FilingDate", "action": "create-property",
                      "targetProperty": None, "reviewStatus": "accepted"},
                 ]},
            ],
        }
        dec_log = {"decisions": []}
        applied = [{"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType"}]

        save_matrix(tmp_path, matrix, dec_log, applied)

        # Check decision log
        log = json.loads((tmp_path / "decision-log.json").read_text(encoding="utf-8"))
        assert len(log["decisions"]) == 1
        entry = log["decisions"][0]
        assert "propertyDecisions" in entry
        assert len(entry["propertyDecisions"]) == 2
        assert entry["propertyDecisions"][0]["sourceProperty"] == "CaseNumber"
        assert entry["propertyDecisions"][0]["targetProperty"] == "CaseDocketID"

    def test_decisions_file_includes_property_decisions(self, tmp_path):
        matrix = {
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType",
                 "reviewStatus": "accepted",
                 "propertyMappings": [
                     {"sourceProperty": "CaseNumber", "action": "reuse-property",
                      "targetProperty": "CaseDocketID", "reviewStatus": "accepted"},
                 ]},
            ],
        }
        dec_log = {"decisions": []}
        applied = [{"sourceConcept": "court:Case", "action": "reuse"}]

        save_matrix(tmp_path, matrix, dec_log, applied)

        # Check replay file
        decisions = json.loads((tmp_path / "human-review-decisions.json").read_text(encoding="utf-8"))
        dec = decisions["decisions"][0]
        assert "propertyDecisions" in dec
        assert dec["propertyDecisions"][0]["sourceProperty"] == "CaseNumber"

    def test_snapshot_empty_property_mappings_list(self, tmp_path):
        matrix = {
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType",
                 "reviewStatus": "accepted",
                 "propertyMappings": []},
            ],
        }
        dec_log = {"decisions": []}
        applied = [{"sourceConcept": "court:Case", "action": "reuse"}]

        save_matrix(tmp_path, matrix, dec_log, applied)

        log = json.loads((tmp_path / "decision-log.json").read_text(encoding="utf-8"))
        assert "propertyDecisions" not in log["decisions"][0]

    def test_no_property_decisions_when_none_decided(self, tmp_path):
        matrix = {
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "reviewStatus": "accepted"},
            ],
        }
        dec_log = {"decisions": []}
        applied = [{"sourceConcept": "court:Case", "action": "reuse"}]

        save_matrix(tmp_path, matrix, dec_log, applied)

        log = json.loads((tmp_path / "decision-log.json").read_text(encoding="utf-8"))
        assert "propertyDecisions" not in log["decisions"][0]


# ---------------------------------------------------------------------------
# TestValidateClassDecision
# ---------------------------------------------------------------------------
class TestValidateClassDecision:
    def test_valid_reuse(self):
        entry = {"action": "reuse", "targetType": "nc:PersonType"}
        assert validate_class_decision(entry) == []

    def test_reuse_missing_target(self):
        entry = {"action": "reuse", "targetType": None}
        issues = validate_class_decision(entry)
        assert any("targetType" in i for i in issues)

    def test_reuse_with_scaffolding(self):
        entry = {"action": "reuse", "targetType": "nc:PersonType",
                 "extensionType": "ext:MyPersonType"}
        issues = validate_class_decision(entry)
        assert any("extensionType" in i for i in issues)

    def test_valid_extend(self):
        entry = {"action": "extend", "extensionType": "ext:InspectionType",
                 "baseType": "nc:ActivityType"}
        assert validate_class_decision(entry) == []

    def test_extend_missing_extension_type(self):
        entry = {"action": "extend", "baseType": "nc:ActivityType"}
        issues = validate_class_decision(entry)
        assert any("extensionType" in i for i in issues)

    def test_extend_missing_base_type(self):
        entry = {"action": "extend", "extensionType": "ext:InspectionType"}
        issues = validate_class_decision(entry)
        assert any("baseType" in i for i in issues)

    def test_extend_with_augment_scaffolding(self):
        entry = {"action": "extend", "extensionType": "ext:X", "baseType": "nc:Y",
                 "augmentationType": "ext:XAug"}
        issues = validate_class_decision(entry)
        assert any("augmentationType" in i for i in issues)

    def test_valid_augment(self):
        entry = {"action": "augment", "targetType": "nc:PersonType",
                 "augmentationType": "ext:PersonAugmentation",
                 "augmentsType": "nc:PersonType"}
        assert validate_class_decision(entry) == []

    def test_augment_missing_target(self):
        entry = {"action": "augment",
                 "augmentationType": "ext:PersonAugmentation",
                 "augmentsType": "nc:PersonType"}
        issues = validate_class_decision(entry)
        assert any("targetType" in i for i in issues)

    def test_augment_missing_augmentation_type(self):
        entry = {"action": "augment", "targetType": "nc:PersonType",
                 "augmentsType": "nc:PersonType"}
        issues = validate_class_decision(entry)
        assert any("augmentationType" in i for i in issues)

    def test_augment_with_extend_scaffolding(self):
        entry = {"action": "augment", "targetType": "nc:PersonType",
                 "augmentationType": "ext:PAug", "augmentsType": "nc:PersonType",
                 "extensionType": "ext:ShouldNotBeHere"}
        issues = validate_class_decision(entry)
        assert any("extensionType" in i for i in issues)


# ---------------------------------------------------------------------------
# TestValidatePropertyDecision
# ---------------------------------------------------------------------------
class TestValidatePropertyDecision:
    def test_valid_reuse_property(self):
        prop = {"action": "reuse-property", "targetProperty": "nc:ActivityDate"}
        assert validate_property_decision(prop) == []

    def test_reuse_property_missing_target(self):
        prop = {"action": "reuse-property"}
        issues = validate_property_decision(prop)
        assert any("targetProperty" in i for i in issues)

    def test_valid_create_property(self):
        prop = {"action": "create-property"}
        assert validate_property_decision(prop) == []

    def test_unknown_action(self):
        prop = {"action": "extend-property"}
        issues = validate_property_decision(prop)
        assert any("unknown" in i for i in issues)

    def test_human_must_decide_flags_issue(self):
        prop = {"action": "human-must-decide", "targetProperty": "[undecided]"}
        issues = validate_property_decision(prop)
        assert len(issues) == 1
        assert "human-must-decide" in issues[0]
        assert "resolved" in issues[0]


# ---------------------------------------------------------------------------
# TestRecomputeSummary
# ---------------------------------------------------------------------------
class TestRecomputeSummary:
    def test_class_level_counts(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted"},
            {"action": "reuse", "reviewStatus": "accepted"},
            {"action": "extend", "reviewStatus": "pending-review"},
            {"action": "extend", "reviewStatus": "accepted"},
            {"action": "augment", "reviewStatus": "accepted"},
        ]}
        summary = recompute_summary(matrix)
        assert summary["totalConcepts"] == 5
        assert summary["actionCounts"] == {"reuse": 2, "extend": 2, "augment": 1}
        assert summary["pendingReview"] == 1
        assert summary["accepted"] == 4

    def test_property_stats_with_decided(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "propertyMappings": [
                {"action": "reuse-property", "reviewStatus": "accepted"},
                {"action": "reuse-property", "reviewStatus": "pending-review"},
                {"action": "create-property", "reviewStatus": "accepted"},
            ]},
            {"action": "extend", "reviewStatus": "accepted", "propertyMappings": [
                {"action": "create-property", "reviewStatus": "pending-review"},
            ]},
        ]}
        summary = recompute_summary(matrix)
        ps = summary["propertyStats"]
        assert ps["total"] == 4
        assert ps["reuseProperty"] == 2
        assert ps["createProperty"] == 2
        assert ps["pendingPropertyReview"] == 2
        assert ps["acceptedProperty"] == 2

    def test_counts_actions(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted"},
            {"action": "reuse", "reviewStatus": "accepted"},
            {"action": "augment", "reviewStatus": "accepted"},
        ]}
        summary = recompute_summary(matrix)
        assert summary["actionCounts"]["reuse"] == 2
        assert summary["actionCounts"]["augment"] == 1

    def test_counts_review_status(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "pending-review"},
            {"action": "reuse", "reviewStatus": "pending-review"},
            {"action": "extend", "reviewStatus": "accepted"},
        ]}
        summary = recompute_summary(matrix)
        assert summary["pendingReview"] == 2
        assert summary["accepted"] == 1

    def test_includes_property_stats(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "propertyMappings": [
                {"action": "reuse-property", "reviewStatus": "accepted"},
                {"action": "create-property", "reviewStatus": "pending-review"},
            ]},
        ]}
        summary = recompute_summary(matrix)
        assert "propertyStats" in summary
        assert summary["propertyStats"]["total"] == 2

    def test_no_property_stats_when_no_properties(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted"},
        ]}
        summary = recompute_summary(matrix)
        assert "propertyStats" not in summary

    def test_no_property_stats_when_all_empty_lists(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "propertyMappings": []},
        ]}
        summary = recompute_summary(matrix)
        assert "propertyStats" not in summary

    def test_counts_human_must_decide(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "propertyMappings": [
                {"action": "reuse-property", "reviewStatus": "accepted"},
                {"action": "human-must-decide", "reviewStatus": "pending-review"},
                {"action": "create-property", "reviewStatus": "accepted"},
            ]},
        ]}
        summary = recompute_summary(matrix)
        ps = summary["propertyStats"]
        assert ps["total"] == 3
        assert ps["humanMustDecide"] == 1
        assert ps["reuseProperty"] == 1
        assert ps["createProperty"] == 1


# ---------------------------------------------------------------------------
# TestCmdAcceptWithHumanMustDecide
# ---------------------------------------------------------------------------
class TestCmdAcceptWithHumanMustDecide:
    """Integration test: _cmd_accept warns about human-must-decide properties."""

    def _write_run_dir(self, tmp_path):
        matrix = {
            "summary": {"totalConcepts": 1, "actionCounts": {"reuse": 1}},
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType",
                 "reviewStatus": "pending-review",
                 "propertyMappings": [
                     {"sourceProperty": "CaseNumber", "action": "reuse-property",
                      "targetProperty": "CaseDocketID", "reviewStatus": "pending-review"},
                     {"sourceProperty": "Judge", "action": "human-must-decide",
                      "targetProperty": "[undecided]", "reviewStatus": "pending-review"},
                 ]},
            ],
        }
        dec_log = {"totalDecisions": 0, "decisions": []}
        (tmp_path / "mapping-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        (tmp_path / "decision-log.json").write_text(json.dumps(dec_log), encoding="utf-8")
        return matrix

    def test_accept_single_warns_about_skipped(self, tmp_path, capsys):
        from types import SimpleNamespace
        from runner_tools._present_and_apply_human_review import _cmd_accept
        self._write_run_dir(tmp_path)

        args = SimpleNamespace(run_dir=str(tmp_path), concept="court:Case")
        _cmd_accept(args)

        out = capsys.readouterr().out
        assert "human-must-decide" in out
        assert "1" in out  # 1 skipped

        # Verify the human-must-decide property stayed pending
        matrix = json.loads((tmp_path / "mapping-matrix.json").read_text(encoding="utf-8"))
        entry = matrix["mappings"][0]
        judge = next(p for p in entry["propertyMappings"] if p["sourceProperty"] == "Judge")
        assert judge["reviewStatus"] == "pending-review"
        assert judge["action"] == "human-must-decide"

    def test_accept_all_blocked_by_human_must_decide(self, tmp_path, capsys):
        from types import SimpleNamespace
        from runner_tools._present_and_apply_human_review import _cmd_accept_all
        self._write_run_dir(tmp_path)

        args = SimpleNamespace(run_dir=str(tmp_path))
        _cmd_accept_all(args)

        out = capsys.readouterr().out
        assert "Cannot approve-all" in out
        assert "1" in out  # 1 human-must-decide

        # Verify nothing was accepted — matrix unchanged
        matrix = json.loads((tmp_path / "mapping-matrix.json").read_text(encoding="utf-8"))
        assert matrix["mappings"][0]["reviewStatus"] == "pending-review"

    def test_accept_all_works_without_human_must_decide(self, tmp_path, capsys):
        from types import SimpleNamespace
        from runner_tools._present_and_apply_human_review import _cmd_accept_all
        matrix = {
            "summary": {"totalConcepts": 1, "actionCounts": {"reuse": 1}},
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType",
                 "reviewStatus": "pending-review",
                 "propertyMappings": [
                     {"sourceProperty": "CaseNumber", "action": "reuse-property",
                      "targetProperty": "CaseDocketID", "reviewStatus": "pending-review"},
                 ]},
            ],
        }
        dec_log = {"totalDecisions": 0, "decisions": []}
        (tmp_path / "mapping-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        (tmp_path / "decision-log.json").write_text(json.dumps(dec_log), encoding="utf-8")

        args = SimpleNamespace(run_dir=str(tmp_path))
        _cmd_accept_all(args)

        out = capsys.readouterr().out
        assert "Approved 1 concepts" in out
        assert "Cannot" not in out

    def test_accept_single_no_warning_without_undecided(self, tmp_path, capsys):
        from types import SimpleNamespace
        from runner_tools._present_and_apply_human_review import _cmd_accept
        # Write a matrix with no human-must-decide properties
        matrix = {
            "summary": {"totalConcepts": 1, "actionCounts": {"reuse": 1}},
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType",
                 "reviewStatus": "pending-review",
                 "propertyMappings": [
                     {"sourceProperty": "CaseNumber", "action": "reuse-property",
                      "targetProperty": "CaseDocketID", "reviewStatus": "pending-review"},
                 ]},
            ],
        }
        dec_log = {"totalDecisions": 0, "decisions": []}
        (tmp_path / "mapping-matrix.json").write_text(json.dumps(matrix), encoding="utf-8")
        (tmp_path / "decision-log.json").write_text(json.dumps(dec_log), encoding="utf-8")

        args = SimpleNamespace(run_dir=str(tmp_path), concept="court:Case")
        _cmd_accept(args)

        out = capsys.readouterr().out
        assert "human-must-decide" not in out


# ---------------------------------------------------------------------------
# TestApplyDecisionWithCascade
# ---------------------------------------------------------------------------
class TestApplyDecisionWithCascade:
    """Tests for apply_decision_with_cascade — type change detection."""

    @pytest.fixture
    def niem_catalog(self):
        return {
            "types": [
                {
                    "qname": "nc:CaseType",
                    "pattern": "object",
                    "baseType": "structures:ObjectType",
                    "inheritanceChain": ["structures:ObjectType"],
                    "properties": ["CaseTrackingID"],
                    "propertyDefinitions": {
                        "CaseTrackingID": {
                            "qualifiedProperty": "nc:CaseTrackingID",
                            "definition": "An identifier.",
                            "qualifiedType": "nc:IdentificationType",
                        },
                    },
                },
                {
                    "qname": "nc:PersonType",
                    "pattern": "object",
                    "baseType": "structures:ObjectType",
                    "inheritanceChain": ["structures:ObjectType"],
                    "properties": ["PersonName"],
                    "propertyDefinitions": {},
                },
                {
                    "qname": "structures:ObjectType",
                    "pattern": "object",
                    "baseType": None,
                    "inheritanceChain": [],
                    "properties": [],
                    "propertyDefinitions": {},
                },
            ],
            "actions": {"reuse": "", "extend": "", "augment": ""},
        }

    def _entry(self):
        return {
            "sourceConcept": "court:CaseType",
            "action": "reuse",
            "targetType": "nc:CaseType",
            "actionRationale": "original",
            "reviewStatus": "accepted",
            "ruleId": "human-review",
            "propertyMappings": [
                {
                    "sourceProperty": "court:caseId",
                    "targetProperty": "nc:CaseTrackingID",
                    "action": "reuse-property",
                    "reviewStatus": "accepted",
                },
            ],
        }

    def test_cascade_on_type_change(self, niem_catalog):
        """Type change triggers reclassification — action and scaffolding update."""
        entry = self._entry()
        decision = {"action": "reuse", "targetType": "nc:PersonType"}
        apply_decision_with_cascade(entry, decision, "niem", niem_catalog)
        assert entry["targetType"] == "nc:PersonType"
        assert entry["action"] == "augment"
        assert entry["ruleId"] == "target-type-change-cascade"
        assert entry["reviewStatus"] == "pending-review"

    def test_no_cascade_same_type(self, niem_catalog):
        """Same targetType → simple apply_decision, no cascade."""
        entry = self._entry()
        decision = {"action": "extend", "targetType": "nc:CaseType"}
        apply_decision_with_cascade(entry, decision, "niem", niem_catalog)
        assert entry["action"] == "extend"
        assert entry["ruleId"] == "human-review"
        assert entry["reviewStatus"] == "accepted"

    def test_no_cascade_no_target_in_decision(self, niem_catalog):
        """No targetType in decision → simple apply_decision."""
        entry = self._entry()
        decision = {"action": "extend"}
        apply_decision_with_cascade(entry, decision, "niem", niem_catalog)
        assert entry["action"] == "extend"
        assert entry["ruleId"] == "human-review"

    def test_cascade_preserves_notes(self, niem_catalog):
        """Notes from decision carry through cascade."""
        entry = self._entry()
        decision = {"action": "reuse", "targetType": "nc:PersonType",
                    "notes": "Changed per review"}
        apply_decision_with_cascade(entry, decision, "niem", niem_catalog)
        assert entry["notes"] == "Changed per review"

    def test_cascade_resets_property_review_status(self, niem_catalog):
        """All property reviewStatus reset to pending-review after cascade."""
        entry = self._entry()
        decision = {"action": "reuse", "targetType": "nc:PersonType"}
        apply_decision_with_cascade(entry, decision, "niem", niem_catalog)
        for pm in entry["propertyMappings"]:
            assert pm["reviewStatus"] == "pending-review"


# ---------------------------------------------------------------------------
# Tests: append-only decision saving
# ---------------------------------------------------------------------------

class TestSaveDecisions:
    def test_creates_new_file(self, tmp_path):
        decisions = [{"sourceConcept": "test:Foo", "action": "reuse"}]
        path = save_decisions(tmp_path, decisions)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["sourceConcept"] == "test:Foo"

    def test_adds_reviewed_at(self, tmp_path):
        decisions = [{"sourceConcept": "test:Foo", "action": "reuse"}]
        save_decisions(tmp_path, decisions)
        data = json.loads((tmp_path / DECISIONS_FILENAME).read_text(encoding="utf-8"))
        assert "reviewedAt" in data["decisions"][0]
        # Should be a valid ISO timestamp
        from datetime import datetime
        datetime.fromisoformat(data["decisions"][0]["reviewedAt"])

    def test_preserves_existing_reviewed_at(self, tmp_path):
        """If reviewedAt is already set, don't overwrite it."""
        decisions = [{
            "sourceConcept": "test:Foo",
            "action": "reuse",
            "reviewedAt": "2026-01-01T00:00:00+00:00",
        }]
        save_decisions(tmp_path, decisions)
        data = json.loads((tmp_path / DECISIONS_FILENAME).read_text(encoding="utf-8"))
        assert data["decisions"][0]["reviewedAt"] == "2026-01-01T00:00:00+00:00"

    def test_appends_to_existing(self, tmp_path):
        """Second save appends, doesn't overwrite."""
        save_decisions(tmp_path, [
            {"sourceConcept": "test:Foo", "action": "reuse"},
        ])
        save_decisions(tmp_path, [
            {"sourceConcept": "test:Bar", "action": "extend"},
        ])
        data = json.loads((tmp_path / DECISIONS_FILENAME).read_text(encoding="utf-8"))
        assert len(data["decisions"]) == 2
        concepts = [d["sourceConcept"] for d in data["decisions"]]
        assert concepts == ["test:Foo", "test:Bar"]

    def test_multiple_changes_same_concept(self, tmp_path):
        """Changing the same concept twice produces two entries."""
        save_decisions(tmp_path, [
            {"sourceConcept": "test:Foo", "action": "reuse",
             "targetType": "nc:PersonType"},
        ])
        save_decisions(tmp_path, [
            {"sourceConcept": "test:Foo", "action": "extend",
             "targetType": "nc:ThingType"},
        ])
        data = json.loads((tmp_path / DECISIONS_FILENAME).read_text(encoding="utf-8"))
        assert len(data["decisions"]) == 2
        assert data["decisions"][0]["action"] == "reuse"
        assert data["decisions"][1]["action"] == "extend"
        # Both have timestamps
        assert "reviewedAt" in data["decisions"][0]
        assert "reviewedAt" in data["decisions"][1]

    def test_replay_order_last_wins(self, tmp_path):
        """When replaying, later entries for the same concept should win."""
        save_decisions(tmp_path, [
            {"sourceConcept": "test:Foo", "action": "reuse",
             "targetType": "nc:PersonType"},
        ])
        save_decisions(tmp_path, [
            {"sourceConcept": "test:Foo", "action": "extend",
             "targetType": "nc:ThingType"},
        ])
        data = json.loads((tmp_path / DECISIONS_FILENAME).read_text(encoding="utf-8"))
        # Simulate replay: process in order, last one wins
        state = {}
        for d in data["decisions"]:
            state[d["sourceConcept"]] = d
        assert state["test:Foo"]["action"] == "extend"
        assert state["test:Foo"]["targetType"] == "nc:ThingType"

    def test_corrupt_existing_file(self, tmp_path):
        """If existing file is corrupt, start fresh."""
        path = tmp_path / DECISIONS_FILENAME
        path.write_text("not valid json", encoding="utf-8")
        save_decisions(tmp_path, [
            {"sourceConcept": "test:Foo", "action": "reuse"},
        ])
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["decisions"]) == 1


# ---------------------------------------------------------------------------
# TestConfidence — Item 5: Residual Entropy Measurement
# ---------------------------------------------------------------------------
class TestConfidenceOnApplyDecision:
    """Confidence field on class-level decisions."""

    def test_defaults_to_confident(self):
        entry = {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"}
        apply_decision(entry, {"action": "extend"})
        assert entry["confidence"] == "confident"

    def test_explicit_confident(self):
        entry = {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"}
        apply_decision(entry, {"action": "extend", "confidence": "confident"})
        assert entry["confidence"] == "confident"

    def test_explicit_best_guess(self):
        entry = {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"}
        apply_decision(entry, {"action": "extend", "confidence": "best-guess"})
        assert entry["confidence"] == "best-guess"


class TestConfidenceOnApplyAccept:
    """Confidence field when accepting a recommendation as-is."""

    def test_accept_sets_confident(self):
        entry = {"sourceConcept": "a:Foo", "action": "reuse", "reviewStatus": "pending-review"}
        apply_accept(entry)
        assert entry["confidence"] == "confident"


class TestConfidenceOnPropertyDecision:
    """Confidence field on property-level decisions."""

    def test_property_decision_defaults_confident(self, entry_with_properties):
        apply_property_decision(entry_with_properties, "SpecialConditions", {
            "action": "reuse-property", "targetProperty": "nc:Something",
        })
        prop = next(p for p in entry_with_properties["propertyMappings"]
                    if p["sourceProperty"] == "SpecialConditions")
        assert prop["confidence"] == "confident"

    def test_property_decision_explicit_best_guess(self, entry_with_properties):
        apply_property_decision(entry_with_properties, "SpecialConditions", {
            "action": "reuse-property", "targetProperty": "nc:Something",
            "confidence": "best-guess",
        })
        prop = next(p for p in entry_with_properties["propertyMappings"]
                    if p["sourceProperty"] == "SpecialConditions")
        assert prop["confidence"] == "best-guess"


class TestConfidenceOnBulkAccept:
    """Confidence field on bulk property accepts."""

    def test_bulk_accept_sets_confident_on_all(self, entry_with_properties):
        apply_all_property_accepts(entry_with_properties)
        for p in entry_with_properties["propertyMappings"]:
            if p["reviewStatus"] == "accepted" and p["sourceProperty"] != "AlreadyDone":
                assert p["confidence"] == "confident"

    def test_bulk_accept_skips_human_must_decide(self):
        entry = {"sourceConcept": "x:Foo", "propertyMappings": [
            {"sourceProperty": "PropA", "action": "reuse-property", "reviewStatus": "pending-review"},
            {"sourceProperty": "PropB", "action": "human-must-decide", "reviewStatus": "pending-review",
             "targetProperty": "[undecided]"},
        ]}
        apply_all_property_accepts(entry)
        prop_a = next(p for p in entry["propertyMappings"] if p["sourceProperty"] == "PropA")
        assert prop_a["confidence"] == "confident"
        prop_b = next(p for p in entry["propertyMappings"] if p["sourceProperty"] == "PropB")
        assert "confidence" not in prop_b  # not touched


class TestConfidenceInSnapshot:
    """Confidence field in _snapshot_property_decisions."""

    def test_snapshot_includes_confidence(self):
        matrix = {"mappings": [
            {"sourceConcept": "court:Case", "propertyMappings": [
                {"sourceProperty": "CaseNumber", "action": "reuse-property",
                 "targetProperty": "CaseDocketID", "reviewStatus": "accepted",
                 "confidence": "confident"},
                {"sourceProperty": "Judge", "action": "reuse-property",
                 "targetProperty": "nc:JudgeName", "reviewStatus": "accepted",
                 "confidence": "best-guess"},
            ]},
        ]}
        result = _snapshot_property_decisions(matrix, "court:Case")
        assert result[0]["confidence"] == "confident"
        assert result[1]["confidence"] == "best-guess"

    def test_snapshot_defaults_confident_if_missing(self):
        matrix = {"mappings": [
            {"sourceConcept": "court:Case", "propertyMappings": [
                {"sourceProperty": "CaseNumber", "action": "reuse-property",
                 "targetProperty": "CaseDocketID", "reviewStatus": "accepted"},
            ]},
        ]}
        result = _snapshot_property_decisions(matrix, "court:Case")
        assert result[0]["confidence"] == "confident"


class TestConfidenceInSummary:
    """Confidence stats in recompute_summary."""

    def test_best_guess_count_class_level(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "confidence": "confident"},
            {"action": "reuse", "reviewStatus": "accepted", "confidence": "best-guess"},
            {"action": "extend", "reviewStatus": "accepted", "confidence": "best-guess"},
            {"action": "augment", "reviewStatus": "pending-review"},
        ]}
        summary = recompute_summary(matrix)
        assert summary["bestGuess"] == 2
        assert summary["accepted"] == 3

    def test_best_guess_zero_when_all_confident(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "confidence": "confident"},
            {"action": "reuse", "reviewStatus": "accepted", "confidence": "confident"},
        ]}
        summary = recompute_summary(matrix)
        assert summary["bestGuess"] == 0

    def test_best_guess_property_level(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "propertyMappings": [
                {"action": "reuse-property", "reviewStatus": "accepted", "confidence": "confident"},
                {"action": "reuse-property", "reviewStatus": "accepted", "confidence": "best-guess"},
                {"action": "create-property", "reviewStatus": "accepted", "confidence": "best-guess"},
                {"action": "create-property", "reviewStatus": "pending-review"},
            ]},
        ]}
        summary = recompute_summary(matrix)
        ps = summary["propertyStats"]
        assert ps["bestGuessProperty"] == 2
        assert ps["acceptedProperty"] == 3

    def test_best_guess_property_zero(self):
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted", "propertyMappings": [
                {"action": "reuse-property", "reviewStatus": "accepted", "confidence": "confident"},
            ]},
        ]}
        summary = recompute_summary(matrix)
        assert summary["propertyStats"]["bestGuessProperty"] == 0

    def test_no_confidence_field_counts_as_zero(self):
        """Entries without confidence field don't count as best-guess."""
        matrix = {"mappings": [
            {"action": "reuse", "reviewStatus": "accepted"},
            {"action": "reuse", "reviewStatus": "accepted"},
        ]}
        summary = recompute_summary(matrix)
        assert summary["bestGuess"] == 0


class TestConfidenceInDecisionLog:
    """Confidence flows through save_matrix to decision log."""

    def test_decision_log_includes_confidence(self, tmp_path):
        matrix = {
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse", "targetType": "nc:CaseType",
                 "reviewStatus": "accepted", "confidence": "best-guess"},
            ],
        }
        dec_log = {"decisions": []}
        applied = [{"sourceConcept": "court:Case", "action": "reuse",
                     "confidence": "best-guess"}]

        save_matrix(tmp_path, matrix, dec_log, applied)

        log = json.loads((tmp_path / "decision-log.json").read_text(encoding="utf-8"))
        assert log["decisions"][0]["confidence"] == "best-guess"

    def test_decision_log_defaults_confident(self, tmp_path):
        matrix = {
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse",
                 "reviewStatus": "accepted"},
            ],
        }
        dec_log = {"decisions": []}
        applied = [{"sourceConcept": "court:Case", "action": "reuse"}]

        save_matrix(tmp_path, matrix, dec_log, applied)

        log = json.loads((tmp_path / "decision-log.json").read_text(encoding="utf-8"))
        assert log["decisions"][0]["confidence"] == "confident"

    def test_decisions_file_includes_confidence(self, tmp_path):
        matrix = {
            "mappings": [
                {"sourceConcept": "court:Case", "action": "reuse",
                 "reviewStatus": "accepted", "confidence": "best-guess"},
            ],
        }
        dec_log = {"decisions": []}
        applied = [{"sourceConcept": "court:Case", "action": "reuse",
                     "confidence": "best-guess"}]

        save_matrix(tmp_path, matrix, dec_log, applied)

        decisions = json.loads(
            (tmp_path / DECISIONS_FILENAME).read_text(encoding="utf-8")
        )
        assert decisions["decisions"][0]["confidence"] == "best-guess"


# ---------------------------------------------------------------------------
# Catalog Search Integration (Item 7)
# ---------------------------------------------------------------------------
class TestCmdSearch:
    """Tests for the search subcommand in the human review CLI."""

    @pytest.fixture
    def catalog_run_dir(self, tmp_path):
        """Create a run dir with .mapper-state.json and a catalog."""
        # Write a minimal catalog
        catalog = {
            "types": [
                {
                    "qname": "nc:PersonType",
                    "definition": "A data type for a person.",
                    "pattern": "object",
                    "properties": ["PersonName", "PersonBirthDate"],
                },
                {
                    "qname": "j:CourtEventType",
                    "definition": "A data type for a court event.",
                    "pattern": "object",
                    "properties": ["CourtEventJudge"],
                },
            ],
            "propertyIndex": {
                "nc": {
                    "properties": [
                        {
                            "name": "PersonName",
                            "qualifiedProperty": "nc:PersonName",
                            "definition": "A combination of names.",
                            "containingTypes": ["nc:PersonType"],
                        },
                    ],
                    "propertyCount": 1,
                },
            },
        }
        catalog_path = tmp_path / "test_catalog.json"
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        return tmp_path, catalog

    def test_search_types(self, catalog_run_dir):
        """search_catalog finds types by name."""
        from ontology_mapper.catalog_search import search_catalog
        _, catalog = catalog_run_dir
        results = search_catalog(catalog, "Person", kind="type")
        assert len(results["types"]) == 1
        assert results["types"][0]["qname"] == "nc:PersonType"

    def test_search_properties(self, catalog_run_dir):
        """search_catalog finds properties by name."""
        from ontology_mapper.catalog_search import search_catalog
        _, catalog = catalog_run_dir
        results = search_catalog(catalog, "PersonName", kind="property")
        assert len(results["properties"]) == 1
        assert results["properties"][0]["qualifiedProperty"] == "nc:PersonName"

    def test_search_both_kinds(self, catalog_run_dir):
        """search_catalog returns both types and properties."""
        from ontology_mapper.catalog_search import search_catalog
        _, catalog = catalog_run_dir
        results = search_catalog(catalog, "Person")
        assert len(results["types"]) >= 1
        assert len(results["properties"]) >= 1

    def test_search_namespace_filter(self, catalog_run_dir):
        """search_catalog filters by namespace."""
        from ontology_mapper.catalog_search import search_catalog
        _, catalog = catalog_run_dir
        results = search_catalog(catalog, "Type", kind="type", namespace="j")
        assert all(t["qname"].startswith("j:") for t in results["types"])

    def test_search_no_results(self, catalog_run_dir):
        """search_catalog returns empty when nothing matches."""
        from ontology_mapper.catalog_search import search_catalog
        _, catalog = catalog_run_dir
        results = search_catalog(catalog, "zzzzz")
        assert results["types"] == []
        assert results["properties"] == []
