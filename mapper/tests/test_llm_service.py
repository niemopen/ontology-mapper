"""Codex invocation regressions with fake subprocesses and real temp files."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from ontology_mapper import llm_service


@pytest.fixture
def fake_codex(monkeypatch):
    monkeypatch.setattr(llm_service.shutil, "which", lambda name: "codex")

    async def no_sleep(delay):
        pass

    monkeypatch.setattr(llm_service.asyncio, "sleep", no_sleep)

    def install(outcomes):
        processes = []

        async def spawn(*args, **kwargs):
            outcome = outcomes[len(processes)]

            class Process:
                returncode = outcome.get("returncode", 0)
                killed = False
                waited = False

                async def communicate(self, input=None):
                    self.input = input
                    if outcome.get("timeout"):
                        raise asyncio.TimeoutError
                    if "final" in outcome:
                        Path(args[args.index("-o") + 1]).write_text(
                            outcome["final"], encoding="utf-8")
                    return outcome.get("stdout", b""), outcome.get("stderr", b"")

                def kill(self):
                    self.killed = True

                async def wait(self):
                    self.waited = True

            process = Process()
            process.args = args
            process.schema = json.loads(
                Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8"))
            processes.append(process)
            return process

        monkeypatch.setattr(llm_service, "_spawn", spawn)
        return processes

    return install


def call(schema=None, **kwargs):
    return asyncio.run(llm_service.call_structured_async(
        "Synthetic mapping prompt", schema or {"type": "object", "properties": {}},
        provider="codex", **kwargs))


@pytest.mark.parametrize("model", [None, "gpt-5.6-sol"])
def test_codex_uses_supported_effort_and_final_file(fake_codex, model):
    schema = {"type": "object", "properties": {"target": {"type": ["string", "null"]}}}
    original = copy.deepcopy(schema)
    processes = fake_codex([{
        "stdout": b'{"type":"turn.completed","usage":{"input_tokens":1}}\n',
        "final": '{"target":null}',
    }])
    assert call(schema, model=model) == {"target": None}
    process = processes[0]
    assert process.args[process.args.index("-m") + 1] == (model or "gpt-5.5")
    assert '--json' in process.args
    assert 'model_reasoning_effort="medium"' in process.args
    assert process.args[process.args.index("-s") + 1] == "read-only"
    assert "--ephemeral" in process.args
    assert process.input == b"Synthetic mapping prompt"
    assert schema == original
    assert process.schema["properties"]["target"]["type"] == ["string", "null"]
    assert process.schema["required"] == ["target"]
    assert process.schema["additionalProperties"] is False


@pytest.mark.parametrize("event", [
    {"type": "error", "message": "Unsupported reasoning effort: max"},
    {"type": "turn.failed", "error": {"message": "Unsupported reasoning effort: max"}},
])
def test_terminal_json_error_survives_echoed_prompt(fake_codex, event):
    failure = {
        "returncode": 1,
        "stdout": (json.dumps(event) + "\n").encode(),
        "stderr": b"Banner and prompt discussing capacity. " * 100,
    }
    processes = fake_codex([failure, failure])
    with pytest.raises(llm_service.LLMError, match="Unsupported reasoning effort: max") as error:
        call()
    assert not isinstance(error.value, llm_service.ModelUnavailableError)
    assert len(processes) == 2
    assert "Banner" not in str(error.value)


def test_final_failure_takes_precedence_over_earlier_retry_event(fake_codex):
    events = [
        {"type": "error", "message": "Temporary connection failure"},
        {"type": "turn.failed", "error": {"message": "Invalid output schema"}},
    ]
    failure = {"returncode": 1, "stdout": "\n".join(map(json.dumps, events)).encode()}
    fake_codex([failure, failure])
    with pytest.raises(llm_service.LLMError, match="Invalid output schema"):
        call()


def test_startup_failure_uses_stderr_tail(fake_codex):
    failure = {"returncode": 1, "stderr": b"Startup details. " * 200 + b"ERROR: could not start Codex"}
    fake_codex([failure, failure])
    with pytest.raises(llm_service.LLMError, match="ERROR: could not start Codex") as error:
        call()
    assert len(str(error.value)) < 2100


def test_non_error_or_malformed_events_do_not_hide_startup_failure(fake_codex):
    failure = {
        "returncode": 1,
        "stdout": b'not JSON\nnull\n{"type":"item.completed","message":"capacity"}\n'
                  b'{"type":"error","message":null}\n{"type":"turn.failed","error":"unknown"}',
        "stderr": b"ERROR: startup failed",
    }
    processes = fake_codex([failure, failure])
    with pytest.raises(llm_service.LLMError, match="ERROR: startup failed") as error:
        call()
    assert not isinstance(error.value, llm_service.ModelUnavailableError)
    assert len(processes) == 2


@pytest.mark.parametrize("diagnostic", ["rate_limit exceeded", "model_not_found", "insufficient_quota"])
def test_actual_unavailable_error_defers_without_retry(fake_codex, diagnostic):
    processes = fake_codex([{
        "returncode": 1,
        "stdout": json.dumps({"type": "turn.failed", "error": {"message": diagnostic}}).encode(),
    }])
    with pytest.raises(llm_service.ModelUnavailableError, match=diagnostic):
        call()
    assert len(processes) == 1


@pytest.mark.parametrize("initial", [
    {"returncode": 1, "stdout": b'{"type":"error","message":"Connection failed"}'},
    {"final": ""},
    {"final": "not JSON"},
])
def test_transient_or_invalid_output_can_retry_successfully(fake_codex, initial):
    processes = fake_codex([initial, {"final": '{"target":"nc:Thing"}'}])
    assert call() == {"target": "nc:Thing"}
    assert len(processes) == 2


def test_timeout_still_kills_and_waits(fake_codex):
    processes = fake_codex([{"timeout": True}, {"timeout": True}])
    with pytest.raises(llm_service.LLMError, match="timed out"):
        call(timeout=1)
    assert len(processes) == 2
    assert all(process.killed and process.waited for process in processes)
