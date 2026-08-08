"""Centralized pipeline context: resolved inputs and derived naming conventions.

Every stage that needs org/source/target identifiers or derived file names,
namespace URIs, or package names should use PipelineContext instead of
constructing f-strings locally.  This eliminates duplication and ensures
a single rename propagates everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ontology_mapper.run_dir_utils import load_state

_NCNAME_INVALID = re.compile(r"[^A-Za-z0-9_.-]+")
_NCNAME_BAD_START = re.compile(r"^[^A-Za-z_]+")


def slugify_ncname(value: str, fallback: str = "x") -> str:
    """Reduce an arbitrary label to a valid XML NCName.

    An NCName allows letters, digits, '.', '-' and '_', and may not begin
    with a digit, '.' or '-'.  Runs of anything else collapse to a single
    '-'.  Every generated identifier goes through this: Turtle prefixes,
    namespace IRI path segments, CMF xs:ID/xs:IDREF values, and artifact
    file names.  A source named "NIEM Hate" would otherwise emit
    ``@prefix NIEM Hate-edge:`` and fail both Turtle parsing and CMF
    schema validation.
    """
    slug = _NCNAME_INVALID.sub("-", (value or "").strip())
    slug = _NCNAME_BAD_START.sub("", slug).strip("-")
    return slug or fallback


@dataclass(frozen=True)
class PipelineContext:
    """Resolved pipeline inputs and all derived naming conventions."""

    run_dir: Path
    pkg_dir: Path
    organization: str
    source: str
    target_ontology: str
    target_version: str
    input_package_path: str = ""

    # ── Identifier-safe forms ────────────────────────────────────────
    # `organization` and `source` are user-supplied display strings and may
    # contain spaces or punctuation.  Anything that becomes a prefix, IRI,
    # xs:ID or file name uses the slug; labels and prose use the raw value.

    @property
    def organization_slug(self) -> str:
        """NCName-safe form of `organization`: e.g. 'Redvale PD' -> 'Redvale-PD'"""
        return slugify_ncname(self.organization, fallback="org")

    @property
    def source_slug(self) -> str:
        """NCName-safe form of `source`: e.g. 'NIEM Hate' -> 'NIEM-Hate'"""
        return slugify_ncname(self.source, fallback="source")

    # ── Package names ────────────────────────────────────────────────

    @property
    def edge_package_name(self) -> str:
        return f"{self.organization_slug}_{self.source_slug}_edge_package"

    @property
    def agency_package_name(self) -> str:
        # Not slugged: this names a directory that already exists on disk,
        # so it has to reproduce the raw name the user created.
        if self.input_package_path:
            return Path(self.input_package_path).name
        return f"{self.organization}_{self.source}_agency_package"

    @property
    def description(self) -> str:
        return f"{self.target_ontology}-aligned edge ontology for {self.source}"

    # ── Namespace URIs (slash-terminated, for JSON metadata) ─────────

    @property
    def extension_namespace(self) -> str:
        return f"https://data.{self.organization_slug}.gov/ontology/{self.source_slug}/ext/"

    @property
    def edge_namespace(self) -> str:
        return f"https://data.{self.organization_slug}.gov/ontology/{self.source_slug}/edge/"

    # ── Namespace URIs (hash-terminated, for OWL/TTL serialization) ──
    # TODO: Reconcile protocol/domain mismatch between slash and hash
    # namespace forms (https://data.{org}.gov vs http://{org}.gov).

    @property
    def edge_ns_hash(self) -> str:
        return f"http://{self.organization_slug}.gov/{self.source_slug}/edge#"

    @property
    def ext_ns_hash(self) -> str:
        return f"http://{self.organization_slug}.gov/{self.source_slug}/ext#"

    # ── File naming ──────────────────────────────────────────────────

    @property
    def file_prefix(self) -> str:
        """e.g. 'dbpi-edge'"""
        return f"{self.source_slug}-edge"

    def ontology_filename(self, suffix: str) -> str:
        """e.g. ontology_filename('core') -> 'dbpi-edge-core.ttl'"""
        return f"{self.file_prefix}-{suffix}.ttl"

    @property
    def cmf_model_stem(self) -> str:
        """e.g. 'dbpi-model'"""
        return f"{self.source_slug}-model"

    @property
    def trig_filename(self) -> str:
        """e.g. 'dbpi-edge.trig'"""
        return f"{self.source_slug}-edge.trig"

    # ── Display ──────────────────────────────────────────────────────

    @property
    def edge_prefix(self) -> str:
        """Turtle prefix for edge namespace: e.g. 'dbpi-edge:'"""
        return f"{self.source_slug}-edge:"

    @property
    def label_prefix(self) -> str:
        """Human-readable label: e.g. 'Redvale DBPI'"""
        return f"{self.organization.replace('_', ' ').title()} {self.source.upper()}"

    # ── Factory methods ──────────────────────────────────────────────

    @classmethod
    def from_inputs(
        cls,
        inputs: dict,
        run_dir: Path,
        pkg_dir: Optional[Path] = None,
    ) -> "PipelineContext":
        """Build from an in-memory inputs dict (used by pipeline.py)."""
        return cls(
            run_dir=Path(run_dir),
            pkg_dir=pkg_dir or Path(run_dir) / "edge-package",
            organization=inputs.get("organization", "org"),
            source=inputs.get("source", "source"),
            target_ontology=inputs.get("target_ontology", ""),
            target_version=inputs.get("target_version", ""),
            input_package_path=inputs.get("input_package_path", ""),
        )


def load_context(
    run_dir_arg: Optional[str] = None,
    pkg_arg: Optional[str] = None,
) -> PipelineContext:
    """Load PipelineContext from .mapper-state.json.

    Replaces per-file load_inputs() functions.  Validates that
    target_ontology and target_version are present.
    """
    if not run_dir_arg:
        raise ValueError("run_dir is required")
    run_dir = Path(run_dir_arg)
    state = load_state(run_dir)
    inputs = state.get("inputs", {})

    target_ontology = inputs.get("target_ontology")
    target_version = inputs.get("target_version")
    if not target_ontology or not target_version:
        raise ValueError(
            f"target_ontology/target_version not set in state for {run_dir}. "
            "Run 'om-pipeline' to start a new run and provide the target ontology."
        )

    pkg = Path(pkg_arg) if pkg_arg else run_dir / "edge-package"

    return PipelineContext(
        run_dir=run_dir,
        pkg_dir=pkg,
        organization=inputs.get("organization", "org"),
        source=inputs.get("source", "source"),
        target_ontology=target_ontology,
        target_version=target_version,
        input_package_path=inputs.get("input_package_path", ""),
    )
