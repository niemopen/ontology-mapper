"""Shared pytest configuration and markers for OntologyMapper tests."""

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that exercise generated artifacts end-to-end "
        "(e.g. loading TriG into rdflib, parsing Cypher scripts). "
        "Deselect with: pytest -m 'not integration'",
    )
    config.addinivalue_line(
        "markers",
        "docker: marks tests that require Docker (e.g. testcontainers Neo4j). "
        "Deselect with: pytest -m 'not docker'",
    )
