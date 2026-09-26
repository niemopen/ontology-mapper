"""Integration tests for ontology_mapper.semantic_search.

These tests build a small FAISS index in a temp directory, then verify
that search_type and search_property return correctly structured results.
Skipped automatically when faiss or sentence-transformers are not installed.
"""

import pytest

try:
    import faiss  # noqa: F401
    from sentence_transformers import SentenceTransformer  # noqa: F401

    HAS_VECTOR_DEPS = True
except ImportError:
    HAS_VECTOR_DEPS = False

pytestmark = pytest.mark.skipif(
    not HAS_VECTOR_DEPS, reason="faiss/sentence-transformers not installed"
)

import ontology_mapper.vector_index as vi
from ontology_mapper.vector_index import OntologyEntry, build_index, save_index
from ontology_mapper.semantic_search import search_property, search_type


def test_per_concept_search_fills_top_k_with_classes_ranked_below_datatypes(
        native_class_catalog, fake_type_retrieval):
    """Datatypes ahead in the ranking must not consume the class budget."""
    fake_type_retrieval(["alias:Restricted", "alias:Values", "alias:Choice",
                         "alias:Record", "alias:Literal", "alias:InheritedLiteral"])
    assert [c["id"] for c in search_type("source:Record", "", "example-1.0", top_k=2)] == [
        "alias:Record", "alias:Literal"]
    assert [c["id"] for c in search_property("source:value", "", "example-1.0", top_k=2)] == [
        "alias:Restricted", "alias:Values"]


def test_search_type_passes_no_predicate_without_a_native_policy(
        native_class_catalog, tmp_path, monkeypatch):
    """Only a native class policy justifies ranking the whole index."""
    import json
    (tmp_path / "plain_reference_catalog_1.0.json").write_text(
        json.dumps({"version": "1.0", "namespaces": {}, "types": []}), encoding="utf-8")
    calls = []
    monkeypatch.setattr("ontology_mapper.semantic_search.query_index",
                        lambda *args, **kwargs: calls.append(kwargs) or [{"matches": []}])
    search_type("source:Record", "", "example-1.0")
    search_type("source:Record", "", "plain-1.0")
    search_type("source:Record", "", "no-catalog-1.0")
    assert callable(calls[0]["eligible"])
    assert calls[1]["eligible"] is None and calls[2]["eligible"] is None

_original_resolve = vi.resolve_specs_dir


@pytest.fixture(scope="module")
def vector_index_dir(tmp_path_factory):
    """Build small FAISS indexes for types and properties in a temp dir."""
    specs = tmp_path_factory.mktemp("specs")
    vi.resolve_specs_dir = lambda: specs

    # -- type entries --
    type_entries = [
        OntologyEntry(
            id="target:PersonType",
            definition="A human individual",
            kind="type",
        ),
        OntologyEntry(
            id="target:OrganizationType",
            definition="A structured group or institution",
            kind="type",
        ),
        OntologyEntry(
            id="target:AddressType",
            definition="A physical location or mailing address",
            kind="type",
        ),
    ]
    idx, meta = build_index(type_entries)
    save_index("test-target", "types", idx, meta)

    # -- property entries --
    property_entries = [
        OntologyEntry(
            id="target:personName",
            definition="The full name of a person",
            kind="property",
        ),
        OntologyEntry(
            id="target:birthDate",
            definition="The date on which a person was born",
            kind="property",
        ),
        OntologyEntry(
            id="target:streetAddress",
            definition="The street portion of an address",
            kind="property",
        ),
    ]
    idx_p, meta_p = build_index(property_entries)
    save_index("test-target", "properties", idx_p, meta_p)

    yield specs

    vi.resolve_specs_dir = _original_resolve


# ---- search_type tests ----


def test_search_type_returns_matches(vector_index_dir):
    """Querying for a person-like concept should return matches."""
    matches = search_type(
        source_concept="source:IndividualType",
        source_definition="A single human being",
        target_ontology="test-target",
    )
    assert len(matches) > 0


def test_search_type_result_structure(vector_index_dir):
    """Each match must have the expected keys."""
    matches = search_type(
        source_concept="source:IndividualType",
        source_definition="A single human being",
        target_ontology="test-target",
    )
    required_keys = {"rank", "score", "id", "definition", "kind"}
    for match in matches:
        assert required_keys.issubset(match.keys()), (
            f"Missing keys: {required_keys - match.keys()}"
        )
        assert isinstance(match["rank"], int)
        assert isinstance(match["score"], float)
        assert isinstance(match["id"], str)
        assert match["kind"] == "type"


def test_search_type_nonexistent_index_raises(vector_index_dir):
    """Querying a nonexistent ontology should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        search_type(
            source_concept="source:FooType",
            source_definition="Something",
            target_ontology="does-not-exist",
        )


# ---- search_property tests ----


def test_search_property_returns_matches(vector_index_dir):
    """Querying for a name-like property should return matches."""
    matches = search_property(
        source_property="source:fullName",
        source_definition="The complete name of an individual",
        target_ontology="test-target",
    )
    assert len(matches) > 0
    assert all(m["kind"] == "property" for m in matches)


# ---- top_k tests ----


def test_top_k_limits_results(vector_index_dir):
    """Setting top_k=1 should return at most one match."""
    matches = search_type(
        source_concept="source:IndividualType",
        source_definition="A single human being",
        target_ontology="test-target",
        top_k=1,
    )
    assert len(matches) == 1
