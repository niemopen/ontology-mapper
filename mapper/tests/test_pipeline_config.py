"""Tests for ontology_mapper.pipeline_config."""

import json

import pytest

from ontology_mapper.pipeline_config import DEFAULTS, load_config, resolve_csv_namespace


def test_defaults_returned_when_no_args(monkeypatch):
    """load_config() returns DEFAULTS when no run directory can be resolved."""
    # The import of resolve_run_dir happens lazily inside load_config,
    # so we patch it on the source module where it's defined.
    def _raise():
        raise FileNotFoundError("no runs")

    monkeypatch.setattr(
        "ontology_mapper.run_dir_utils.resolve_run_dir", _raise,
    )

    result = load_config()
    assert result == DEFAULTS
    assert result["property_composition_max_depth"] == 2


def test_state_file_overrides_default(tmp_path):
    """Thresholds in the state file override corresponding defaults."""
    state_file = tmp_path / ".mapper-state.json"
    state_file.write_text(json.dumps({
        "thresholds": {"property_composition_max_depth": 5},
    }))

    result = load_config(state_file=state_file)
    assert result["property_composition_max_depth"] == 5


def test_unknown_threshold_ignored(tmp_path):
    """Keys not present in DEFAULTS are silently dropped."""
    state_file = tmp_path / ".mapper-state.json"
    state_file.write_text(json.dumps({
        "thresholds": {"totally_unknown_key": 99},
    }))

    result = load_config(state_file=state_file)
    assert "totally_unknown_key" not in result
    assert result == DEFAULTS


def test_run_dir_resolves_state(tmp_path):
    """Passing run_dir locates the state file inside it."""
    state_file = tmp_path / ".mapper-state.json"
    state_file.write_text(json.dumps({
        "thresholds": {"property_composition_max_depth": 7},
    }))

    result = load_config(run_dir=tmp_path)
    assert result["property_composition_max_depth"] == 7


def test_missing_state_file_returns_defaults(tmp_path):
    """A nonexistent state_file path returns defaults without error."""
    result = load_config(state_file=tmp_path / "nonexistent.json")
    assert result == DEFAULTS


def test_malformed_json_returns_defaults(tmp_path):
    """Invalid JSON in the state file returns defaults gracefully."""
    state_file = tmp_path / ".mapper-state.json"
    state_file.write_text("{not valid json!!!")

    result = load_config(state_file=state_file)
    assert result == DEFAULTS


def test_empty_thresholds_returns_defaults(tmp_path):
    """An empty thresholds dict changes nothing."""
    state_file = tmp_path / ".mapper-state.json"
    state_file.write_text(json.dumps({"thresholds": {}}))

    result = load_config(state_file=state_file)
    assert result == DEFAULTS


class TestResolveCsvNamespace:
    """resolve_csv_namespace derives ONE (prefix, uri) for both CSV entry
    points (runner run_pipeline.py and web routes/runs.py), so a given source
    yields the same concept IRIs regardless of which one ran it."""

    def test_derived_from_source(self):
        assert resolve_csv_namespace({"source": "dbpi"}) == ("dbpi", "urn:dbpi-model")

    def test_source_is_slugified(self):
        # lowercased; spaces and underscores become hyphens
        assert resolve_csv_namespace({"source": "NIBRS Hate_Crime"}) == (
            "nibrs-hate-crime", "urn:nibrs-hate-crime-model")

    def test_explicit_namespace_and_uri_win(self):
        assert resolve_csv_namespace({
            "source": "dbpi", "namespace": "court", "namespace_uri": "urn:court",
        }) == ("court", "urn:court")

    def test_explicit_prefix_with_source_derived_uri(self):
        assert resolve_csv_namespace({"source": "dbpi", "namespace": "court"}) == (
            "court", "urn:dbpi-model")

    def test_no_source_falls_back(self):
        assert resolve_csv_namespace({}) == ("src", "urn:src-model")

    def test_blank_source_falls_back(self):
        assert resolve_csv_namespace({"source": "   "}) == ("src", "urn:src-model")
