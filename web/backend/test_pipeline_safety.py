"""Review preservation and validation stopping, using temporary runs only."""

import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import settings
from routes import review, runs


@pytest.fixture
def run_context(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runs_dir", tmp_path)
    monkeypatch.setattr(runs, "_pipeline_status", {})
    run_dir = tmp_path / "demo" / "sample"
    run_dir.mkdir(parents=True)
    (run_dir / ".mapper-state.json").write_text(json.dumps({
        "inputs": {"target_ontology": "niem", "target_version": "6.0"},
        "stages": {"5": {"status": "completed"}}}), encoding="utf-8")
    thread = Mock()
    monkeypatch.setattr(runs.threading, "Thread", thread)
    app = FastAPI()
    app.include_router(runs.router)
    app.include_router(review.router)
    with TestClient(app) as client:
        yield run_dir, client, thread


@pytest.mark.parametrize("evidence", ["accepted", "property", "marker", "pending", "empty"])
def test_execute_protects_saved_review(run_context, evidence):
    run_dir, client, thread = run_context
    entry = {"sourceConcept": "src:A", "action": "reuse", "reviewStatus": "pending-review"}
    matrix = {"mappings": [] if evidence == "empty" else [entry]}
    if evidence == "accepted":
        entry["reviewStatus"] = "accepted"
    if evidence == "property":
        entry["propertyMappings"] = [{"reviewStatus": "accepted"}]
    if evidence == "marker":
        matrix["humanReviewApplied"] = "2026-09-14T12:00:00Z"
    path = run_dir / "mapping-matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")
    before = path.read_bytes()
    response = client.post("/runs/sample/execute")
    protected = evidence in {"accepted", "property", "marker"}
    assert response.status_code == (409 if protected else 200), response.text
    assert thread.called is (not protected)
    assert path.read_bytes() == before


@pytest.mark.parametrize("decision", ["accepted", "pending", "must-decide", "exclude"])
def test_continue_uses_current_matrix(run_context, decision):
    run_dir, client, thread = run_context
    entry = {"sourceConcept": "src:A", "action": "reuse", "reviewStatus": "accepted"}
    if decision == "pending":
        entry["reviewStatus"] = "pending-review"
    if decision == "must-decide":
        entry["propertyMappings"] = [{"sourceProperty": "src:p", "action": "human-must-decide", "reviewStatus": "pending-review"}]
    if decision == "exclude":
        entry.update(action="exclude", reviewStatus="pending-review")
    (run_dir / "mapping-matrix.json").write_text(json.dumps({"mappings": [entry]}), encoding="utf-8")
    response = client.post("/runs/sample/continue")
    ready = decision in {"accepted", "exclude"}
    assert response.status_code == (200 if ready else 409), response.text
    assert thread.called is ready


@pytest.mark.parametrize("valid", [False, True])
def test_validation_stops_before_finalization(tmp_path, monkeypatch, valid):
    monkeypatch.setattr(runs, "_pipeline_status", {"sample": {}})
    commands = []
    completed = []
    monkeypatch.setattr(runs, "_record_stage_start", lambda *args: None)
    monkeypatch.setattr(runs, "_mark_complete", lambda run_id, stage, *args: completed.append(stage) or True)

    def command(run_id, stage, cmd, cwd, env):
        commands.append(cmd[0])
        if not valid and cmd[0] == "om-validate":
            (tmp_path / "validation-report.json").write_text('{"checks": []}', encoding="utf-8")
            runs._pipeline_status[run_id] = {"status": "failed", "stage": "7", "error": "SOME CHECKS FAILED"}
            return False
        return True

    monkeypatch.setattr(runs, "_run_cmd", command)
    assert runs._run_pipeline_stages_6_8("sample", tmp_path, str(tmp_path), {}) is valid
    assert ("om-finalize" in commands) is valid
    assert ("7" in completed) is valid
    # The feedback report maps failures back to decisions, so it is produced
    # even when validation fails, and the validation failure stays the cause.
    assert "python" in commands
    assert commands.index("python") > commands.index("om-validate")
    if not valid:
        assert runs._pipeline_status["sample"]["error"] == "SOME CHECKS FAILED"


def test_validator_crash_without_a_report_stops_before_the_feedback_report(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "_pipeline_status", {"sample": {}})
    commands = []
    monkeypatch.setattr(runs, "_record_stage_start", lambda *args: None)
    monkeypatch.setattr(runs, "_mark_complete", lambda run_id, stage, *args: True)

    def command(run_id, stage, cmd, cwd, env):
        commands.append(cmd[0])
        if cmd[0] == "om-validate":
            runs._pipeline_status[run_id] = {"status": "failed", "stage": "7", "error": "Traceback ... KeyError"}
            return False
        return True

    monkeypatch.setattr(runs, "_run_cmd", command)
    assert runs._run_pipeline_stages_6_8("sample", tmp_path, str(tmp_path), {}) is False
    assert "python" not in commands  # no report to map back; feedback_report.py does not run
    assert runs._pipeline_status["sample"]["error"].startswith("Traceback")


def test_stage_7_discards_a_previous_runs_report_before_validating(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "_pipeline_status", {"sample": {}})
    (tmp_path / "validation-report.json").write_text('{"checks": [], "stale": true}', encoding="utf-8")
    (tmp_path / "feedback-report.json").write_text('{"stale": true}', encoding="utf-8")
    commands = []
    monkeypatch.setattr(runs, "_record_stage_start", lambda *args: None)
    monkeypatch.setattr(runs, "_mark_complete", lambda run_id, stage, *args: True)

    def command(run_id, stage, cmd, cwd, env):
        commands.append(cmd[0])
        if cmd[0] == "om-validate":
            assert not (tmp_path / "validation-report.json").exists()  # cleared before the run
            runs._pipeline_status[run_id] = {"status": "failed", "stage": "7", "error": "Traceback ... KeyError"}
            return False
        return True

    monkeypatch.setattr(runs, "_run_cmd", command)
    assert runs._run_pipeline_stages_6_8("sample", tmp_path, str(tmp_path), {}) is False
    assert "python" not in commands
    assert not (tmp_path / "feedback-report.json").exists()
    assert runs._pipeline_status["sample"]["error"].startswith("Traceback")


@pytest.mark.parametrize("target", ["scr:PersonRoleCategoryCodeType", "hs:PersonRoleCodeSimpleType", "nc:TextType"])
@pytest.mark.parametrize("same_target", [False, True])
def test_change_target_checks_native_class_before_saving(run_context, monkeypatch, target, same_target):
    from ontology_mapper.run_dir_utils import resolve_specs_dir

    run_dir, client, _ = run_context
    catalog = json.loads((resolve_specs_dir() / "niem_reference_catalog_6.0.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(review, "_get_cascade", lambda *args: ("niem", catalog))
    entry = {"sourceConcept": "source:Record", "targetType": target if same_target else "nc:PersonType",
             "action": "reuse", "reviewStatus": "accepted", "propertyMappings": []}
    (run_dir / "mapping-matrix.json").write_text(json.dumps({"mappings": [entry]}), encoding="utf-8")
    for name in ("decision-log.json", "human-review-decisions.json"):
        (run_dir / name).write_text(json.dumps({"decisions": []}), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in run_dir.glob("*.json")}
    response = client.post("/runs/sample/review/change-target", json={
        "concept": "source:Record", "new_target_type": target})
    if target == "nc:TextType":
        assert response.status_code == 200, response.text
        assert response.json()["newTargetType"] == target
    else:
        assert response.status_code == 400, response.text
        assert target in response.json()["detail"]
        assert "not a class" in response.json()["detail"]
        assert all((run_dir / name).read_bytes() == data for name, data in before.items())

@pytest.mark.parametrize("target,blocked", [("hs:PersonRoleCodeSimpleType", True), ("nc:PersonType", False)])
def test_continue_blocks_on_a_saved_target_the_policy_rejects(run_context, monkeypatch, target, blocked):
    from ontology_mapper.run_dir_utils import resolve_specs_dir

    run_dir, client, thread = run_context
    catalog = json.loads((resolve_specs_dir() / "niem_reference_catalog_6.0.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(review, "_get_cascade", lambda *args: ("niem", catalog))
    (run_dir / "mapping-matrix.json").write_text(json.dumps({"mappings": [
        {"sourceConcept": "src:A", "action": "reuse", "targetType": target,
         "reviewStatus": "accepted", "propertyMappings": []}]}), encoding="utf-8")

    response = client.post("/runs/sample/continue")

    assert response.status_code == (409 if blocked else 200), response.text
    assert thread.called is (not blocked)
    if blocked:
        # A string, like the review routes: the frontend renders `detail`
        # directly and JSON-stringifies anything else.
        detail = response.json()["detail"]
        assert isinstance(detail, str) and "src:A" in detail


def test_reset_without_a_stage_4_snapshot_does_not_claim_to_reset(run_context):
    """The snapshot is Stage 4's output, written when Stage 4 runs. Reading
    the review used to create it from whatever was on disk, so a run
    reviewed outside the web got its reviewed matrix snapshotted and
    `reset` restored it while answering "reset"."""
    run_dir, client, _ = run_context
    (run_dir / "mapping-matrix.json").write_text(json.dumps({"mappings": [
        {"sourceConcept": "src:A", "action": "reuse", "targetType": "nc:PersonType",
         "reviewStatus": "accepted", "propertyMappings": []}]}), encoding="utf-8")

    assert client.get("/runs/sample/review").status_code in (200, 409)
    assert not (run_dir / "mapping-matrix.stage4.json").exists()

    response = client.post("/runs/sample/review/reset")
    assert response.status_code == 404, response.text


def test_reset_reports_a_snapshot_that_itself_carries_decisions(run_context):
    """A snapshot written before this rule can carry decisions; saying only
    "reset" would tell the operator the execute gate is clear when it is not."""
    run_dir, client, _ = run_context
    reviewed = json.dumps({"mappings": [
        {"sourceConcept": "src:A", "action": "reuse", "targetType": "nc:PersonType",
         "reviewStatus": "accepted", "propertyMappings": []}]})
    (run_dir / "mapping-matrix.json").write_text(reviewed, encoding="utf-8")
    (run_dir / "mapping-matrix.stage4.json").write_text(reviewed, encoding="utf-8")

    body = client.post("/runs/sample/review/reset").json()

    assert body["status"] == "reset"
    assert body["restoredDecisions"] == 1
    assert "om-build-matrix --force" in body["note"]
