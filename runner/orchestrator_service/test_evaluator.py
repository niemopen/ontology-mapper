"""Tests for orchestrator_service.evaluator.

Tests monkeypatch ontology_mapper.llm_service._spawn (the local alias
for the async subprocess factory) to avoid invoking the real CLI. The
mock simulates the subprocess response envelope that `claude -p
--output-format json` returns; conftest.py pins OM_LLM_PROVIDER=claude
for the whole directory so the mocked envelope matches the parser path.

Uses asyncio.run() directly — no pytest-asyncio dependency needed.
"""

import asyncio
import json
import pytest

from orchestrator_service.evaluator import (
    EvaluationContext,
    EvaluationError,
    evaluate_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_doc(qname="dbpi:Address"):
    return {
        "kind": "type",
        "source": {"qname": qname},
        "candidates": [
            {"id": "nc:AddressType", "definition": "A postal address."},
        ],
    }


def _prop_doc(qname="dbpi:streetName"):
    return {
        "kind": "property",
        "source": {"qname": qname},
        "candidates": [
            {"id": "nc:StreetFullText", "definition": "A street address."},
        ],
    }


def _context():
    return EvaluationContext(
        actions={"reuse": "Use as-is."},
        type_patterns={"object": "Container types."},
    )


def _valid_type_response():
    return {
        "sourceConcept": "dbpi:Address",
        "sourceDefinition": "",
        "sourcePath": "dbpi:Address",
        "targetType": "nc:AddressType",
        "targetDefinition": "A postal address.",
        "targetPath": "nc:AddressType",
        "rationale": "Both represent physical postal addresses with street components.",
    }


def _valid_prop_response():
    return {
        "sourceProperty": "dbpi:streetName",
        "sourceDefinition": "",
        "sourcePath": "dbpi:Address/dbpi:streetName",
        "targetProperty": "nc:StreetFullText",
        "targetDefinition": "A street address.",
        "targetPath": "nc:AddressType/nc:StreetFullText",
        "rationale": "Both represent the street portion of a physical address.",
    }


def _response_envelope(evaluation):
    """Build the JSON envelope that claude -p --output-format json returns."""
    return json.dumps({
        "result": "",
        "is_error": False,
        "structured_output": evaluation,
    }).encode("utf-8")


# ---------------------------------------------------------------------------
# Mock subprocess
# ---------------------------------------------------------------------------

class MockProcess:
    """Simulates an asyncio subprocess for testing."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0, hang=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang

    async def communicate(self, input=None):
        if self._hang:
            await asyncio.sleep(9999)
        return self._stdout, self._stderr

    def kill(self):
        pass

    async def wait(self):
        pass


def _make_mock(stdout=b"", stderr=b"", returncode=0, hang=False):
    """Create a monkeypatch-ready mock for the subprocess factory."""
    proc = MockProcess(stdout=stdout, stderr=stderr,
                       returncode=returncode, hang=hang)

    async def mock_spawn(*args, **kwargs):
        return proc

    return mock_spawn


# ---------------------------------------------------------------------------
# Tests: successful evaluation
# ---------------------------------------------------------------------------

class TestSuccessfulEvaluation:
    def test_type_evaluation(self, monkeypatch):
        mock = _make_mock(stdout=_response_envelope(_valid_type_response()))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_type_doc(), _context(), model="sonnet"))
        assert result["sourceConcept"] == "dbpi:Address"
        assert result["targetType"] == "nc:AddressType"

    def test_property_evaluation(self, monkeypatch):
        mock = _make_mock(stdout=_response_envelope(_valid_prop_response()))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_prop_doc(), _context(), model="sonnet"))
        assert result["sourceProperty"] == "dbpi:streetName"
        assert result["targetProperty"] == "nc:StreetFullText"

    def test_null_target_is_valid(self, monkeypatch):
        resp = _valid_type_response()
        resp["targetType"] = None
        resp["targetDefinition"] = None
        resp["targetPath"] = None
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_type_doc(), _context()))
        assert result["targetType"] is None


# ---------------------------------------------------------------------------
# Tests: provenance metadata
# ---------------------------------------------------------------------------

class TestProvenanceMetadata:
    """Provenance fields are added post-validation, not by the LLM."""

    def test_type_provenance_fields_present(self, monkeypatch):
        mock = _make_mock(stdout=_response_envelope(_valid_type_response()))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_type_doc(), _context(), model="sonnet"))
        assert "evaluatedAt" in result
        assert result["evaluatedBy"] == "claude:sonnet"
        assert result["candidateCount"] == 1  # _type_doc has 1 candidate

    def test_property_provenance_fields_present(self, monkeypatch):
        mock = _make_mock(stdout=_response_envelope(_valid_prop_response()))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_prop_doc(), _context(), model="opus"))
        assert "evaluatedAt" in result
        assert result["evaluatedBy"] == "claude:opus"
        assert result["candidateCount"] == 1  # _prop_doc has 1 candidate

    def test_model_name_recorded(self, monkeypatch):
        mock = _make_mock(stdout=_response_envelope(_valid_type_response()))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_type_doc(), _context(), model="haiku"))
        assert result["evaluatedBy"] == "claude:haiku"

    def test_candidate_count_matches_input(self, monkeypatch):
        """candidateCount reflects the file's candidate list, not LLM output."""
        doc = {
            "kind": "type",
            "source": {"qname": "dbpi:Address"},
            "candidates": [
                {"id": "nc:AddressType", "definition": "A postal address."},
                {"id": "nc:LocationType", "definition": "A location."},
                {"id": "nc:StreetType", "definition": "A street."},
            ],
        }
        mock = _make_mock(stdout=_response_envelope(_valid_type_response()))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(doc, _context()))
        assert result["candidateCount"] == 3

    def test_candidate_count_zero(self, monkeypatch):
        """Degenerate case: file has no candidates."""
        doc = {
            "kind": "type",
            "source": {"qname": "dbpi:Address"},
            "candidates": [],
        }
        resp = _valid_type_response()
        resp["targetType"] = None
        resp["targetDefinition"] = None
        resp["targetPath"] = None
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(doc, _context()))
        assert result["candidateCount"] == 0

    def test_null_target_has_provenance(self, monkeypatch):
        """Provenance is added even when target is null (no match)."""
        resp = _valid_type_response()
        resp["targetType"] = None
        resp["targetDefinition"] = None
        resp["targetPath"] = None
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_type_doc(), _context(), model="sonnet"))
        assert result["evaluatedBy"] == "claude:sonnet"
        assert result["candidateCount"] == 1
        assert "evaluatedAt" in result

    def test_undecided_target_has_provenance(self, monkeypatch):
        """Provenance is added when target is [undecided] sentinel."""
        resp = _valid_prop_response()
        resp["targetProperty"] = "[undecided]"
        resp["targetDefinition"] = None
        resp["targetPath"] = None
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_prop_doc(), _context(), model="sonnet"))
        assert result["evaluatedBy"] == "claude:sonnet"
        assert result["candidateCount"] == 1
        assert "evaluatedAt" in result

    def test_evaluated_at_is_iso_format(self, monkeypatch):
        from datetime import datetime
        mock = _make_mock(stdout=_response_envelope(_valid_type_response()))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_type_doc(), _context()))
        # Should parse without error
        datetime.fromisoformat(result["evaluatedAt"])


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_timeout(self, monkeypatch):
        mock = _make_mock(hang=True)
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="timed out"):
            asyncio.run(evaluate_file(_type_doc(), _context(), timeout=1))

    def test_nonzero_exit_code(self, monkeypatch):
        mock = _make_mock(stderr=b"Some error occurred", returncode=1)
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="rc=1"):
            asyncio.run(evaluate_file(_type_doc(), _context()))

    def test_malformed_json(self, monkeypatch):
        mock = _make_mock(stdout=b"not valid json")
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="invalid JSON"):
            asyncio.run(evaluate_file(_type_doc(), _context()))

    def test_is_error_flag(self, monkeypatch):
        envelope = json.dumps({
            "result": "Something went wrong",
            "is_error": True,
            "structured_output": None,
        }).encode("utf-8")
        mock = _make_mock(stdout=envelope)
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="reported error"):
            asyncio.run(evaluate_file(_type_doc(), _context()))

    def test_missing_structured_output(self, monkeypatch):
        envelope = json.dumps({
            "result": "Some text response",
            "is_error": False,
        }).encode("utf-8")
        mock = _make_mock(stdout=envelope)
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="no structured_output"):
            asyncio.run(evaluate_file(_type_doc(), _context()))

    def test_unknown_file_kind(self):
        doc = {"kind": "unknown", "source": {}, "candidates": []}
        with pytest.raises(EvaluationError, match="Unknown file kind"):
            asyncio.run(evaluate_file(doc, _context()))


# ---------------------------------------------------------------------------
# Tests: validation failures
# ---------------------------------------------------------------------------

class TestValidationFailures:
    def test_source_mismatch_raises(self, monkeypatch):
        resp = _valid_type_response()
        resp["sourceConcept"] = "wrong:Name"
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="Validation failed"):
            asyncio.run(evaluate_file(_type_doc(), _context()))

    def test_target_not_in_candidates_raises(self, monkeypatch):
        resp = _valid_type_response()
        resp["targetType"] = "nc:NotACandidate"
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="Validation failed"):
            asyncio.run(evaluate_file(_type_doc(), _context()))

    def test_short_rationale_raises(self, monkeypatch):
        resp = _valid_type_response()
        resp["rationale"] = "ok"
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        with pytest.raises(EvaluationError, match="Validation failed"):
            asyncio.run(evaluate_file(_type_doc(), _context()))

    def test_prefix_auto_correction(self, monkeypatch):
        resp = _valid_type_response()
        resp["sourceConcept"] = "Address"  # missing prefix
        mock = _make_mock(stdout=_response_envelope(resp))
        monkeypatch.setattr("ontology_mapper.llm_service._spawn", mock)

        result = asyncio.run(evaluate_file(_type_doc(), _context()))
        assert result["sourceConcept"] == "dbpi:Address"


# ---------------------------------------------------------------------------
# Tests: subprocess invocation details
# ---------------------------------------------------------------------------

class TestSubprocessArgs:
    def test_passes_correct_cli_args(self, monkeypatch):
        captured = {}

        async def capture(*args, **kwargs):
            captured["args"] = args
            return MockProcess(
                stdout=_response_envelope(_valid_type_response()),
            )

        monkeypatch.setattr("ontology_mapper.llm_service._spawn", capture)
        asyncio.run(evaluate_file(_type_doc(), _context(), model="sonnet"))

        args = captured["args"]
        assert args[0] == "claude"
        assert args[1] == "-p"
        assert "--tools" in args
        assert "--output-format" in args
        assert "--json-schema" in args
        assert "--model" in args
        assert "sonnet" in args
        assert "--no-session-persistence" in args

    def test_prompt_sent_via_stdin(self, monkeypatch):
        captured = {}

        class CapturingProcess(MockProcess):
            async def communicate(self, input=None):
                captured["stdin"] = input
                return self._stdout, self._stderr

        async def capture(*args, **kwargs):
            return CapturingProcess(
                stdout=_response_envelope(_valid_type_response()),
            )

        monkeypatch.setattr("ontology_mapper.llm_service._spawn", capture)
        asyncio.run(evaluate_file(_type_doc(), _context()))

        assert captured["stdin"] is not None
        prompt_text = captured["stdin"].decode("utf-8")
        assert "dbpi:Address" in prompt_text

    def test_model_flag_passed_through(self, monkeypatch):
        captured = {}

        async def capture(*args, **kwargs):
            captured["args"] = args
            return MockProcess(
                stdout=_response_envelope(_valid_type_response()),
            )

        monkeypatch.setattr("ontology_mapper.llm_service._spawn", capture)
        asyncio.run(evaluate_file(_type_doc(), _context(), model="opus"))

        assert "opus" in captured["args"]
