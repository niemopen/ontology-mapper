"""Tests for orchestrator_service.prompts."""

from orchestrator_service.prompts import (
    build_type_prompt,
    build_property_prompt,
    SEMANTIC_SEARCH_GUIDANCE,
)


ACTIONS = {"reuse": "Use as-is.", "extend": "Create extension."}
TYPE_PATTERNS = {"object": "Container types.", "association": "Relationships."}


class TestTypePrompt:
    def test_includes_source(self):
        source = {"qname": "dbpi:Address", "definition": "A location."}
        prompt = build_type_prompt(source, [], ACTIONS, TYPE_PATTERNS)
        assert "dbpi:Address" in prompt
        assert "A location." in prompt

    def test_includes_candidates(self):
        source = {"qname": "dbpi:Address"}
        candidates = [{"id": "nc:AddressType", "definition": "Postal."}]
        prompt = build_type_prompt(source, candidates, ACTIONS, TYPE_PATTERNS)
        assert "nc:AddressType" in prompt
        assert "Postal." in prompt

    def test_includes_actions(self):
        prompt = build_type_prompt({"qname": "x"}, [], ACTIONS, TYPE_PATTERNS)
        assert "reuse" in prompt
        assert "extend" in prompt

    def test_includes_type_patterns(self):
        prompt = build_type_prompt({"qname": "x"}, [], ACTIONS, TYPE_PATTERNS)
        assert "object" in prompt
        assert "association" in prompt

    def test_includes_guidance(self):
        prompt = build_type_prompt({"qname": "x"}, [], ACTIONS, TYPE_PATTERNS)
        assert "element" in prompt.lower()

    def test_no_hardcoded_ontology_names(self):
        prompt = build_type_prompt({"qname": "x"}, [], {}, {})
        # Should not mention specific ontology names
        assert "NIEM" not in prompt
        assert "SALI" not in prompt


    def test_includes_undecided_instruction(self):
        prompt = build_type_prompt({"qname": "x"}, [], ACTIONS, TYPE_PATTERNS)
        assert "[undecided]" in prompt


class TestPropertyPrompt:
    def test_includes_source(self):
        source = {
            "qname": "dbpi:streetName",
            "parentType": "dbpi:Address",
            "parentDefinition": "A location.",
        }
        prompt = build_property_prompt(source, [], ACTIONS, TYPE_PATTERNS)
        assert "dbpi:streetName" in prompt
        assert "dbpi:Address" in prompt

    def test_includes_candidates(self):
        source = {"qname": "dbpi:streetName"}
        candidates = [{"id": "nc:StreetFullText", "definition": "Street."}]
        prompt = build_property_prompt(source, candidates, ACTIONS, TYPE_PATTERNS)
        assert "nc:StreetFullText" in prompt

    def test_includes_undecided_instruction(self):
        source = {"qname": "dbpi:streetName"}
        prompt = build_property_prompt(source, [], ACTIONS, TYPE_PATTERNS)
        assert "[undecided]" in prompt

    def test_mentions_range_and_parent(self):
        prompt = build_property_prompt(
            {"qname": "x"}, [], ACTIONS, TYPE_PATTERNS,
        )
        assert "range" in prompt.lower() or "parent" in prompt.lower()


class TestGuidance:
    def test_guidance_not_empty(self):
        assert len(SEMANTIC_SEARCH_GUIDANCE) > 100

    def test_guidance_mentions_element_first(self):
        assert "element" in SEMANTIC_SEARCH_GUIDANCE.lower()

    def test_guidance_mentions_property_path(self):
        assert "property" in SEMANTIC_SEARCH_GUIDANCE.lower()
