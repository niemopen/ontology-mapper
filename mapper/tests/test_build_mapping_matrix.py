#!/usr/bin/env python3
"""Tests for Stage 4: build_mapping_matrix.py

Covers schema transformation from alignment report to mapping matrix.
No reasoning — just verifies fields carry through correctly.
"""

import json
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


class TestReviewProtection:
    """Stage 4 preserves saved decisions independently of their provenance."""

    @staticmethod
    def _matrix(class_status="pending-review", prop_status="pending-review",
                reviewed_at=None):
        doc = {
            "stage": "4",
            "mappings": [{
                "sourceConcept": "dbpi:Person",
                "action": "reuse",
                "reviewStatus": class_status,
                "propertyMappings": [
                    {"sourceProperty": "dbpi:hasName",
                     "action": "reuse-property",
                     "reviewStatus": prop_status},
                ],
            }],
        }
        if reviewed_at:
            doc["humanReviewApplied"] = reviewed_at
        return doc

    def _write(self, tmp_path, matrix):
        path = tmp_path / "mapping-matrix.json"
        path.write_text(json.dumps(matrix), encoding="utf-8")
        return path

    def test_fresh_matrix_counts_no_decisions(self):
        from ontology_mapper.build_mapping_matrix import review_decisions_present

        assert review_decisions_present(self._matrix()) == (0, 0, None)

    def test_reviewed_matrix_counts_its_decisions(self):
        from ontology_mapper.build_mapping_matrix import review_decisions_present

        classes, props, at = review_decisions_present(
            self._matrix("accepted", "accepted"))
        assert (classes, props) == (1, 1)
        assert at is None

    def test_marker_is_reported_when_present(self):
        from ontology_mapper.build_mapping_matrix import review_decisions_present

        _, _, at = review_decisions_present(
            self._matrix("accepted", "accepted", reviewed_at="2026-05-14T19:52:37Z"))
        assert at == "2026-05-14T19:52:37Z"

    def test_a_review_without_the_marker_still_counts(self):
        """Decisions written outside save_matrix() may carry no marker."""
        from ontology_mapper.build_mapping_matrix import review_decisions_present

        classes, props, at = review_decisions_present(
            self._matrix("accepted", "accepted"))
        assert at is None and classes and props

    def test_rejected_and_modified_are_decisions_too(self):
        from ontology_mapper.build_mapping_matrix import review_decisions_present

        assert review_decisions_present(
            self._matrix("rejected", "modified"))[:2] == (1, 1)

    def test_rebuild_over_a_review_is_refused(self, tmp_path):
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        path = self._write(tmp_path, self._matrix("accepted", "accepted"))
        with pytest.raises(SystemExit) as exc:
            refuse_to_discard_review(path, force=False)
        message = str(exc.value)
        assert "1 class and 1 property decision" in message
        assert "--force" in message
        assert json.loads(path.read_text(encoding="utf-8"))["mappings"][0][
            "reviewStatus"] == "accepted", "the matrix must be left untouched"

    def test_rebuild_over_a_fresh_matrix_proceeds(self, tmp_path):
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        path = self._write(tmp_path, self._matrix())
        assert refuse_to_discard_review(path, force=False) is None

    def test_absent_matrix_proceeds(self, tmp_path):
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        assert refuse_to_discard_review(tmp_path / "nothing.json") is None

    def test_unreadable_matrix_proceeds(self, tmp_path):
        """A corrupt file holds no decisions to protect, so it must not
        wedge the stage that would replace it."""
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        path = tmp_path / "mapping-matrix.json"
        path.write_text("{not json", encoding="utf-8")
        assert refuse_to_discard_review(path, force=False) is None

    def test_force_copies_the_review_aside_before_rebuilding(self, tmp_path):
        from ontology_mapper.build_mapping_matrix import (
            refuse_to_discard_review, review_decisions_present)

        path = self._write(tmp_path, self._matrix("accepted", "accepted"))
        backup = refuse_to_discard_review(path, force=True)
        assert backup is not None and backup.exists()
        assert backup != path
        saved = json.loads(backup.read_text(encoding="utf-8"))
        assert review_decisions_present(saved)[:2] == (1, 1)

    def test_forced_backups_do_not_overwrite_an_earlier_backup(self, tmp_path, monkeypatch):
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        monkeypatch.setattr("ontology_mapper.build_mapping_matrix.utc_stamp",
                            lambda: "2026-09-10T12:00:00Z")
        path = self._write(tmp_path, self._matrix("accepted", "accepted"))
        first = refuse_to_discard_review(path, force=True)
        saved = first.read_bytes()
        self._write(tmp_path, self._matrix("accepted", "pending-review"))
        second = refuse_to_discard_review(path, force=True)
        assert first != second
        assert first.read_bytes() == saved
        assert second.read_bytes() == path.read_bytes()

    def test_pending_cascade_with_saved_target_is_protected(self, tmp_path):
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        matrix = self._matrix(reviewed_at="2026-09-10T12:00:00Z")
        matrix["mappings"][0]["targetType"] = "target:ChangedType"
        path = self._write(tmp_path, matrix)
        before = path.read_bytes()
        with pytest.raises(SystemExit, match="reviewed at"):
            refuse_to_discard_review(path)
        assert path.read_bytes() == before

    @pytest.mark.parametrize("matrix", [None, [], 1, "bad", {"mappings": None},
                                      {"mappings": {}}, {"mappings": [None, 1, {}]}])
    def test_malformed_json_shapes_can_be_rebuilt(self, tmp_path, matrix):
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        assert refuse_to_discard_review(self._write(tmp_path, matrix)) is None

    def test_malformed_neighbors_do_not_hide_valid_decisions(self, tmp_path):
        from ontology_mapper.build_mapping_matrix import refuse_to_discard_review

        matrix = {"mappings": [None, {"reviewStatus": []}, {
            "propertyMappings": [False, {"reviewStatus": "accepted"}]}]}
        with pytest.raises(SystemExit, match="1 property"):
            refuse_to_discard_review(self._write(tmp_path, matrix))


@pytest.mark.parametrize("force", [False, True])
def test_main_preserves_review_files_and_invalidates_snapshot_only_on_rebuild(
        tmp_path, monkeypatch, force):
    from ontology_mapper.build_mapping_matrix import main

    (tmp_path / ".mapper-state.json").write_text(json.dumps({"inputs": {
        "organization": "testorg", "source": "sample",
        "target_ontology": "example", "target_version": "1"}}), encoding="utf-8")
    (tmp_path / "alignment-report.json").write_text(json.dumps({
        "matchingMethod": "semantic", "entries": [REUSE_ENTRY]}), encoding="utf-8")
    matrix = tmp_path / "mapping-matrix.json"
    log = tmp_path / "decision-log.json"
    snapshot = tmp_path / "mapping-matrix.stage4.json"
    old_matrix = json.dumps(TestReviewProtection._matrix("accepted", "accepted"))
    old_log = '{"decisions": [{"rationale": "saved review"}]}'
    matrix.write_text(old_matrix, encoding="utf-8")
    log.write_text(old_log, encoding="utf-8")
    snapshot.write_text(old_matrix, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["om-build-matrix", "--run-dir", str(tmp_path)]
                        + (["--force"] if force else []))
    if force:
        main()
        assert json.loads(matrix.read_text())["mappings"][0]["reviewStatus"] == "pending-review"
        assert not snapshot.exists()
        assert [p.read_text() for p in tmp_path.glob("mapping-matrix.pre-rebuild-*.json")] == [old_matrix]
        assert [p.read_text() for p in tmp_path.glob("decision-log.pre-rebuild-*.json")] == [old_log]
    else:
        with pytest.raises(SystemExit):
            main()
        assert matrix.read_text() == old_matrix
        assert log.read_text() == old_log
        assert snapshot.read_text() == old_matrix
        assert not list(tmp_path.glob("*.pre-rebuild-*.json"))
