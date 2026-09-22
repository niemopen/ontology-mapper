"""Tests for run_dir_utils — run directory resolution and org detection."""

import pathlib
import json
import pytest
from datetime import datetime


def test_timestamp_writer_and_legacy_parser(monkeypatch):
    import ontology_mapper.run_dir_utils as utils

    stamp = utils.utc_stamp()
    assert stamp.endswith("Z") and "+00:00" not in stamp
    expected = utils.parse_stamp("2026-09-14T12:00:00Z")
    for value in ("2026-09-14T12:00:00+00:00", "2026-09-14T05:00:00-07:00", "2026-09-14T12:00:00"):
        assert utils.parse_stamp(value) == expected
    for value in (None, "", "invalid", 1):
        assert utils.parse_stamp(value) is None

    class LegacyDatetime:
        @staticmethod
        def fromisoformat(value):
            # Python 3.10's parser does not accept Z.
            assert not value.endswith("Z")
            return datetime.fromisoformat(value)

    monkeypatch.setattr(utils, "datetime", LegacyDatetime)
    assert utils.parse_stamp("2026-09-14T12:00:00Z") == expected
from pathlib import Path

from ontology_mapper.run_dir_utils import (
    resolve_run_dir,
    load_state,
    state_path_for,
    list_orgs,
    _org_from_dirname,
    _list_run_dirs,
    STATE_FILENAME,
    RUNS_ROOT,
)


# ---------------------------------------------------------------------------
# _org_from_dirname
# ---------------------------------------------------------------------------

class TestOrgFromDirname:
    def test_standard_org_prefix(self):
        assert _org_from_dirname("redvale_20260329-045647") == "redvale"

    def test_different_org(self):
        assert _org_from_dirname("nods_20260329-025224") == "nods"

    def test_bare_timestamp_no_org(self):
        assert _org_from_dirname("20260329-045647") == ""

    def test_multi_underscore_org(self):
        # org name contains underscores: "my_agency_20260329-045647"
        # rsplit("_", 1) gives ["my_agency", "20260329-045647"]
        assert _org_from_dirname("my_agency_20260329-045647") == "my_agency"

    def test_non_timestamp_suffix(self):
        # If the suffix after the last underscore is not a timestamp-like string
        assert _org_from_dirname("redvale_notes") == ""

    def test_empty_string(self):
        assert _org_from_dirname("") == ""


# ---------------------------------------------------------------------------
# list_orgs
# ---------------------------------------------------------------------------

class TestListOrgs:
    def test_no_runs_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ontology_mapper.run_dir_utils.RUNS_ROOT", tmp_path / "nonexistent")
        assert list_orgs() == []

    def test_empty_runs_dir(self, tmp_path, monkeypatch):
        runs = tmp_path / ".mapper-runs"
        runs.mkdir()
        monkeypatch.setattr("ontology_mapper.run_dir_utils.RUNS_ROOT", runs)
        assert list_orgs() == []

    def test_single_org(self, tmp_path, monkeypatch):
        runs = tmp_path / ".mapper-runs"
        runs.mkdir()
        (runs / "redvale_20260329-045647").mkdir()
        monkeypatch.setattr("ontology_mapper.run_dir_utils.RUNS_ROOT", runs)
        assert list_orgs() == ["redvale"]

    def test_multiple_orgs_sorted(self, tmp_path, monkeypatch):
        runs = tmp_path / ".mapper-runs"
        runs.mkdir()
        (runs / "redvale_20260329-045647").mkdir()
        (runs / "nods_20260329-025224").mkdir()
        (runs / "redvale_20260329-025151").mkdir()
        monkeypatch.setattr("ontology_mapper.run_dir_utils.RUNS_ROOT", runs)
        assert list_orgs() == ["nods", "redvale"]

    def test_bare_timestamp_dirs_excluded(self, tmp_path, monkeypatch):
        runs = tmp_path / ".mapper-runs"
        runs.mkdir()
        (runs / "20260329-045647").mkdir()
        (runs / "redvale_20260329-025151").mkdir()
        monkeypatch.setattr("ontology_mapper.run_dir_utils.RUNS_ROOT", runs)
        assert list_orgs() == ["redvale"]


# ---------------------------------------------------------------------------
# resolve_run_dir
# ---------------------------------------------------------------------------

class TestResolveRunDir:
    def test_explicit_cli_arg(self, tmp_path):
        run = tmp_path / "my_run"
        run.mkdir()
        assert resolve_run_dir(cli_arg=str(run)) == run

    def test_explicit_cli_arg_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Run directory not found"):
            resolve_run_dir(cli_arg=str(tmp_path / "nonexistent"))

    def test_no_arg_raises(self):
        with pytest.raises(FileNotFoundError, match="--run-dir is required"):
            resolve_run_dir()

    def test_none_arg_raises(self):
        with pytest.raises(FileNotFoundError, match="--run-dir is required"):
            resolve_run_dir(cli_arg=None)

    def test_cli_arg_takes_precedence_over_org(self, tmp_path, monkeypatch):
        runs = tmp_path / ".mapper-runs"
        runs.mkdir()
        specific = runs / "nods_20260329-025224"
        specific.mkdir()
        (runs / "redvale_20260329-045647").mkdir()
        monkeypatch.setattr("ontology_mapper.run_dir_utils.RUNS_ROOT", runs)

        # cli_arg wins even if org is also specified
        result = resolve_run_dir(cli_arg=str(specific), org="redvale")
        assert result.name == "nods_20260329-025224"


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------

class TestLoadState:
    def test_loads_valid_state(self, tmp_path):
        state = {"run_id": "test_123", "inputs": {"target_ontology": "niem", "target_version": "6.0"}}
        (tmp_path / STATE_FILENAME).write_text(json.dumps(state), encoding="utf-8")
        result = load_state(tmp_path)
        assert result["run_id"] == "test_123"
        assert result["inputs"]["target_ontology"] == "niem"

    def test_missing_state_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No state file found"):
            load_state(tmp_path)


# ---------------------------------------------------------------------------
# state_path_for
# ---------------------------------------------------------------------------

class TestStatePathFor:
    def test_returns_correct_path(self, tmp_path):
        result = state_path_for(tmp_path)
        assert result == tmp_path / STATE_FILENAME

def test_no_module_parses_a_shared_timestamp_with_the_stdlib_parser():
    """`utc_stamp` writes a trailing Z, which `datetime.fromisoformat` rejects
    before Python 3.11 — and both pyproject files declare `requires-python =
    ">=3.10"`. Every reader goes through `parse_stamp`, which is proven
    Z-tolerant above; a direct call would pass on this interpreter and fail
    on the oldest supported one, where no suite here runs."""
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    allowed = {
        root / "mapper" / "src" / "ontology_mapper" / "run_dir_utils.py",   # parse_stamp itself
        root / "mapper" / "tests" / "test_run_dir_utils.py",                # and its own test
    }
    offenders = []
    for folder in ("mapper/src", "mapper/tests", "runner", "web/backend"):
        for path in (root / folder).rglob("*.py"):
            # A virtualenv under either tree is a developer's, not this
            # repo's: pydantic and pytest both call `fromisoformat`.
            skipped = {"build", "node_modules", "site-packages", ".venv", "venv"}
            if path in allowed or skipped & set(path.parts):
                continue
            if re.search(r"\bfromisoformat\s*\(", path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"use run_dir_utils.parse_stamp instead: {offenders}"

