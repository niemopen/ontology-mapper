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
        "inputs": {}, "stages": {"5": {"status": "completed"}}}), encoding="utf-8")
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
