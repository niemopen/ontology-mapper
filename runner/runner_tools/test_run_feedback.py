"""Tests for runner_tools.run_feedback."""

import json
import sys
from unittest.mock import patch

import pytest

from runner_tools.run_feedback import log_observation, main


# --- log_observation tests ---


def test_creates_new_feedback_file(tmp_path):
    """Empty run dir creates run-feedback.json with one observation."""
    log_observation(tmp_path, "3", "bug", "some_tool()", "Something broke")

    feedback_path = tmp_path / "run-feedback.json"
    assert feedback_path.exists()
    data = json.loads(feedback_path.read_text())
    assert len(data["observations"]) == 1
    assert data["observations"][0]["description"] == "Something broke"


def test_appends_to_existing(tmp_path):
    """Two calls produce two observations in the file."""
    log_observation(tmp_path, "1", "bug", "tool_a()", "First issue")
    log_observation(tmp_path, "2", "gap", "tool_b()", "Second issue")

    data = json.loads((tmp_path / "run-feedback.json").read_text())
    assert len(data["observations"]) == 2
    assert data["observations"][0]["description"] == "First issue"
    assert data["observations"][1]["description"] == "Second issue"


def test_observation_has_required_fields(tmp_path):
    """Verify all required fields are present in the observation."""
    log_observation(tmp_path, "5", "gap", "resolver()", "Missing mapping",
                    impact="high", target="orchestrator")

    data = json.loads((tmp_path / "run-feedback.json").read_text())
    obs = data["observations"][0]
    assert "timestamp" in obs
    assert obs["stage"] == "5"
    assert obs["type"] == "gap"
    assert obs["component"] == "resolver()"
    assert obs["description"] == "Missing mapping"
    assert obs["impact"] == "high"
    assert obs["target"] == "orchestrator"


def test_invalid_target_raises(tmp_path):
    """target='invalid' raises ValueError."""
    with pytest.raises(ValueError, match="target must be"):
        log_observation(tmp_path, "1", "bug", "tool()", "desc", target="invalid")


def test_workaround_optional(tmp_path):
    """Omitting workaround stores None."""
    log_observation(tmp_path, "1", "bug", "tool()", "desc")

    data = json.loads((tmp_path / "run-feedback.json").read_text())
    assert data["observations"][0]["workaround"] is None


def test_workaround_recorded(tmp_path):
    """Providing workaround stores it in the observation."""
    log_observation(tmp_path, "1", "bug", "tool()", "desc",
                    workaround="Used fallback path")

    data = json.loads((tmp_path / "run-feedback.json").read_text())
    assert data["observations"][0]["workaround"] == "Used fallback path"


# --- main (CLI) tests ---


def test_log_command(tmp_path):
    """Mock sys.argv with log args, call main(), verify file written."""
    argv = [
        "run_feedback.py", "log",
        "--run-dir", str(tmp_path),
        "--stage", "3",
        "--type", "bug",
        "--component", "resolve_run_dir()",
        "--description", "Picks wrong directory",
        "--workaround", "Used explicit path",
        "--impact", "low",
        "--target", "pipeline",
    ]
    with patch.object(sys, "argv", argv):
        main()

    data = json.loads((tmp_path / "run-feedback.json").read_text())
    assert len(data["observations"]) == 1
    obs = data["observations"][0]
    assert obs["component"] == "resolve_run_dir()"
    assert obs["target"] == "pipeline"


def test_show_command(tmp_path, capsys):
    """Pre-create feedback file, run show, verify stdout."""
    feedback = {
        "observations": [
            {
                "timestamp": "2026-04-05T00:00:00+00:00",
                "stage": "3",
                "type": "bug",
                "component": "resolve_run_dir()",
                "description": "Picks wrong directory",
                "workaround": "Used explicit path",
                "impact": "low",
                "target": "pipeline",
            }
        ]
    }
    (tmp_path / "run-feedback.json").write_text(json.dumps(feedback))

    argv = ["run_feedback.py", "show", "--run-dir", str(tmp_path)]
    with patch.object(sys, "argv", argv):
        main()

    captured = capsys.readouterr().out
    assert "resolve_run_dir()" in captured
    assert "Picks wrong directory" in captured
    assert "pipeline" in captured
    assert "Workaround: Used explicit path" in captured
