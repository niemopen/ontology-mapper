"""Tests for pipeline_context: naming conventions and input resolution."""

import json
import pytest
from pathlib import Path

from ontology_mapper.pipeline_context import PipelineContext, load_context


# ── Fixtures ─────────────────────────────────────────────────────────

def _base_inputs():
    return {
        "organization": "redvale",
        "source": "dbpi",
        "target_ontology": "niem",
        "target_version": "6.0",
        "input_package_path": "sources/redvale_dbpi_agency_package",
    }


def _make_ctx(**overrides):
    inputs = _base_inputs()
    inputs.update(overrides)
    return PipelineContext.from_inputs(inputs, run_dir=Path("/tmp/run"))


# ── Package names ────────────────────────────────────────────────────

class TestPackageNames:
    def test_edge_package_name(self):
        ctx = _make_ctx()
        assert ctx.edge_package_name == "redvale_dbpi_edge_package"

    def test_agency_package_name_from_input_path(self):
        ctx = _make_ctx(input_package_path="sources/redvale_dbpi_agency_package")
        assert ctx.agency_package_name == "redvale_dbpi_agency_package"

    def test_agency_package_name_fallback(self):
        ctx = _make_ctx(input_package_path="")
        assert ctx.agency_package_name == "redvale_dbpi_agency_package"

    def test_description(self):
        ctx = _make_ctx()
        assert ctx.description == "niem-aligned edge ontology for dbpi"


# ── Namespace URIs ───────────────────────────────────────────────────

class TestNamespaces:
    def test_extension_namespace(self):
        ctx = _make_ctx()
        assert ctx.extension_namespace == "https://data.redvale.gov/ontology/dbpi/ext/"

    def test_edge_namespace(self):
        ctx = _make_ctx()
        assert ctx.edge_namespace == "https://data.redvale.gov/ontology/dbpi/edge/"

    def test_edge_ns_hash(self):
        ctx = _make_ctx()
        assert ctx.edge_ns_hash == "http://redvale.gov/dbpi/edge#"

    def test_ext_ns_hash(self):
        ctx = _make_ctx()
        assert ctx.ext_ns_hash == "http://redvale.gov/dbpi/ext#"


# ── File naming ──────────────────────────────────────────────────────

class TestFileNaming:
    def test_file_prefix(self):
        ctx = _make_ctx()
        assert ctx.file_prefix == "dbpi-edge"

    def test_ontology_filename(self):
        ctx = _make_ctx()
        assert ctx.ontology_filename("core") == "dbpi-edge-core.ttl"
        assert ctx.ontology_filename("extensions") == "dbpi-edge-extensions.ttl"
        assert ctx.ontology_filename("all") == "dbpi-edge-all.ttl"
        assert ctx.ontology_filename("combined") == "dbpi-edge-combined.ttl"
        assert ctx.ontology_filename("shapes") == "dbpi-edge-shapes.ttl"
        assert ctx.ontology_filename("codelists") == "dbpi-edge-codelists.ttl"

    def test_cmf_model_stem(self):
        ctx = _make_ctx()
        assert ctx.cmf_model_stem == "dbpi-model"

    def test_trig_filename(self):
        ctx = _make_ctx()
        assert ctx.trig_filename == "dbpi-edge.trig"


# ── Display ──────────────────────────────────────────────────────────

class TestDisplay:
    def test_edge_prefix(self):
        ctx = _make_ctx()
        assert ctx.edge_prefix == "dbpi-edge:"

    def test_label_prefix(self):
        ctx = _make_ctx()
        assert ctx.label_prefix == "Redvale DBPI"

    def test_label_prefix_underscore_org(self):
        ctx = _make_ctx(organization="my_org")
        assert ctx.label_prefix == "My Org DBPI"


# ── Factory: from_inputs ─────────────────────────────────────────────

class TestFromInputs:
    def test_defaults(self):
        ctx = PipelineContext.from_inputs({}, run_dir=Path("/tmp/run"))
        assert ctx.organization == "org"
        assert ctx.source == "source"
        assert ctx.target_ontology == ""
        assert ctx.target_version == ""
        assert ctx.input_package_path == ""
        assert ctx.pkg_dir == Path("/tmp/run/edge-package")

    def test_pkg_dir_override(self):
        ctx = PipelineContext.from_inputs(
            _base_inputs(),
            run_dir=Path("/tmp/run"),
            pkg_dir=Path("/tmp/custom-pkg"),
        )
        assert ctx.pkg_dir == Path("/tmp/custom-pkg")


# ── Factory: load_context ────────────────────────────────────────────

class TestLoadContext:
    def test_missing_target_ontology_raises(self, tmp_path):
        state = {"inputs": {"organization": "x", "source": "y"}}
        state_path = tmp_path / ".mapper-state.json"
        state_path.write_text(json.dumps(state))
        with pytest.raises(ValueError, match="target_ontology"):
            load_context(run_dir_arg=str(tmp_path))

    def test_valid_state(self, tmp_path):
        state = {"inputs": _base_inputs()}
        state_path = tmp_path / ".mapper-state.json"
        state_path.write_text(json.dumps(state))
        ctx = load_context(run_dir_arg=str(tmp_path))
        assert ctx.organization == "redvale"
        assert ctx.source == "dbpi"
        assert ctx.target_ontology == "niem"
        assert ctx.run_dir == tmp_path
        assert ctx.pkg_dir == tmp_path / "edge-package"

    def test_pkg_arg_override(self, tmp_path):
        state = {"inputs": _base_inputs()}
        (tmp_path / ".mapper-state.json").write_text(json.dumps(state))
        ctx = load_context(run_dir_arg=str(tmp_path), pkg_arg=str(tmp_path / "custom"))
        assert ctx.pkg_dir == tmp_path / "custom"


# ── Frozen ───────────────────────────────────────────────────────────

class TestFrozen:
    def test_immutable(self):
        ctx = _make_ctx()
        with pytest.raises(AttributeError):
            ctx.source = "changed"
