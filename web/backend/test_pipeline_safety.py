"""Review preservation and validation stopping, using temporary runs only."""

import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import settings
from routes import review, runs


def _finalized_run(run_dir):
    """A run whose previous Stages 7 and 8 passed and stamped the package."""
    stamp = "2026-09-01T00:00:00Z"
    stages = {s: {"stage": s, "status": "completed", "started_at": stamp,
                  "completed_at": stamp, "error": None, "artifacts": [], "notes": None}
              for s in "12345678"}
    (run_dir / ".mapper-state.json").write_text(json.dumps({
        "run_id": "sample", "created_at": stamp, "updated_at": stamp,
        "inputs": {"target_ontology": "niem", "target_version": "6.0"},
        "stages": stages, "highest_completed": "8", "current_stage": "8"}), encoding="utf-8")
    gov = run_dir / "edge-package" / "governance"
    gov.mkdir(parents=True)
    (gov / "validation-report.json").write_text('{"allPassed": true}', encoding="utf-8")
    (gov / "change-impact.md").write_text("All validation checks passed.\n", encoding="utf-8")
    (gov / "decision-log.json").write_text("{}", encoding="utf-8")  # Stage 6b's
    (run_dir / "edge-package" / "package-manifest.json").write_text(
        json.dumps({"name": "sample", "finalizedAt": stamp}), encoding="utf-8")
    return run_dir / "edge-package"


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
    pkg = _finalized_run(tmp_path)
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
        # Nothing from the previous Stage 8 still reads as validated or final,
        # in the package or in the state a restarted backend reports from.
        assert not (pkg / "governance" / "validation-report.json").exists()
        assert not (pkg / "governance" / "change-impact.md").exists()
        assert (pkg / "governance" / "decision-log.json").exists()
        assert "finalizedAt" not in json.loads((pkg / "package-manifest.json").read_text(encoding="utf-8"))
        state = json.loads((tmp_path / ".mapper-state.json").read_text(encoding="utf-8"))
        assert state["stages"]["7"]["status"] == "failed"
        assert state["stages"]["8"]["status"] == "pending"
        assert state["highest_completed"] == "6"


def test_validator_crash_without_a_report_stops_before_the_feedback_report(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "_pipeline_status", {"sample": {}})
    _finalized_run(tmp_path)
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
    _finalized_run(tmp_path)
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


def test_review_state_offers_submit_only_when_the_gate_would_accept(run_context, monkeypatch):
    """Submit asks `stage_5_gate`; the state the UI renders asks it too. It
    counted pending items instead, so a policy-blocked run showed Submit
    enabled and the click came back 409 with no blocker shown."""
    from ontology_mapper.run_dir_utils import resolve_specs_dir

    run_dir, client, _ = run_context
    catalog = json.loads((resolve_specs_dir() / "niem_reference_catalog_6.0.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(review, "_get_cascade", lambda *args: ("niem", catalog))
    entry = {"sourceConcept": "src:A", "action": "extend", "targetType": "nc:PersonType",
             "baseType": "niem-xs:token", "reviewStatus": "accepted", "propertyMappings": []}
    (run_dir / "mapping-matrix.json").write_text(json.dumps({"mappings": [entry]}), encoding="utf-8")
    validation = client.get("/runs/sample/review").json()["validation"]
    assert validation["canSubmit"] is False
    assert any("src:A" in blocker for blocker in validation["blockers"])
    assert client.post("/runs/sample/review/submit").status_code == 409


def test_reset_counts_restored_decisions_as_the_execute_gate_does(run_context):
    """A snapshot carrying only a property decision still makes the execute
    gate refuse; the reset note must say so, counted by the same predicate."""
    run_dir, client, _ = run_context
    entry = {"sourceConcept": "src:A", "action": "reuse", "reviewStatus": "pending-review",
             "propertyMappings": [{"sourceProperty": "src:p", "reviewStatus": "accepted"}]}
    (run_dir / review.STAGE4_SNAPSHOT).write_text(json.dumps({"mappings": [entry]}), encoding="utf-8")
    result = client.post("/runs/sample/review/reset").json()
    assert result["restoredDecisions"] == 1
    assert result["note"]
    assert client.post("/runs/sample/execute").status_code == 409


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
    # The 404 carries the same next step the execute 409 gives, so
    # following the product's advice twice does not dead-end.
    assert "om-build-matrix --force" in response.json()["detail"]


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
