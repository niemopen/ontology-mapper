"""Pytest fixtures for orchestrator_service tests.

The test suite mocks `asyncio.create_subprocess_exec` to fake LLM
responses. Those mocks were written against the claude provider's
response envelope ({"structured_output": {...}, ...}), so the test
suite pins OM_LLM_PROVIDER=claude regardless of the user's shell
environment. The codex provider path is exercised via integration
tests run out-of-band when needed.
"""

import pytest


@pytest.fixture(autouse=True)
def _force_claude_provider(monkeypatch):
    """Pin the LLM provider to claude for every test in this directory."""
    monkeypatch.setenv("OM_LLM_PROVIDER", "claude")
