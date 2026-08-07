"""Tests for pipeline_context: naming conventions and input resolution."""

import json
import pytest
from pathlib import Path

from ontology_mapper.pipeline_context import (
    PipelineContext,
    load_context,
    slugify_ncname,
)


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


# ── NCName slugging ──────────────────────────────────────────────────

class TestSlugifyNCName:
    @pytest.mark.parametrize("raw,expected", [
        ("dbpi", "dbpi"),                    # already valid — unchanged
        ("my_org", "my_org"),                # underscore is a legal NCName char
        ("NIEM Hate", "NIEM-Hate"),          # space
        ("NIEM  Hate", "NIEM-Hate"),         # runs collapse to one '-'
        ("  NIEM Hate  ", "NIEM-Hate"),      # surrounding whitespace
        ("hate/crime", "hate-crime"),        # path separator
        ("v1.2-data", "v1.2-data"),          # '.' and '-' are legal
        ("2026 crime", "crime"),             # NCName may not start with a digit
        ("-lead", "lead"),                   # nor with '-'
        ("_lead", "_lead"),                  # but '_' is a legal start
        ("trail!", "trail"),                 # no trailing separator left behind
    ])
    def test_slugs(self, raw, expected):
        assert slugify_ncname(raw) == expected

    def test_fallback_when_nothing_survives(self):
        assert slugify_ncname("2026", fallback="source") == "source"
        assert slugify_ncname("", fallback="source") == "source"
        assert slugify_ncname("!!!", fallback="source") == "source"


class TestSpaceBearingSource:
    """A source name with a space must not leak into any identifier.

    Regression: source "NIEM Hate" produced the Turtle prefix
    "NIEM Hate-edge:" and CMF ids like "NIEM Hate-edge.IdentificationID",
    failing turtle-syntax, shacl-conformance and cmf-consistency.
    """

    def _ctx(self):
        return _make_ctx(organization="demo", source="NIEM Hate")

    def test_edge_prefix_is_valid_ncname(self):
        assert self._ctx().edge_prefix == "NIEM-Hate-edge:"

    def test_namespaces_have_no_spaces(self):
        ctx = self._ctx()
        for uri in (ctx.edge_ns_hash, ctx.ext_ns_hash,
                    ctx.edge_namespace, ctx.extension_namespace):
            assert " " not in uri
        assert ctx.edge_ns_hash == "http://demo.gov/NIEM-Hate/edge#"

    def test_file_names_have_no_spaces(self):
        ctx = self._ctx()
        assert ctx.file_prefix == "NIEM-Hate-edge"
        assert ctx.ontology_filename("core") == "NIEM-Hate-edge-core.ttl"
        assert ctx.cmf_model_stem == "NIEM-Hate-model"
        assert ctx.trig_filename == "NIEM-Hate-edge.trig"

    def test_edge_package_name_slugged(self):
        assert self._ctx().edge_package_name == "demo_NIEM-Hate_edge_package"

    def test_agency_package_name_keeps_on_disk_name(self):
        ctx = _make_ctx(
            organization="demo",
            source="NIEM Hate",
            input_package_path="sources/demo/NIEM Hate_agency_package",
        )
        assert ctx.agency_package_name == "NIEM Hate_agency_package"

    def test_display_strings_keep_raw_source(self):
        ctx = self._ctx()
        assert ctx.description == "niem-aligned edge ontology for NIEM Hate"
        assert ctx.label_prefix == "Demo NIEM HATE"

    def test_organization_with_space(self):
        ctx = _make_ctx(organization="Redvale PD", source="dbpi")
        assert ctx.organization_slug == "Redvale-PD"
        assert ctx.edge_ns_hash == "http://Redvale-PD.gov/dbpi/edge#"


# ── Frozen ───────────────────────────────────────────────────────────

class TestFrozen:
    def test_immutable(self):
        ctx = _make_ctx()
        with pytest.raises(AttributeError):
            ctx.source = "changed"
