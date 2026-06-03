"""Tests for ontology_mapper.vector_index module.

Two categories:
1. Pure logic tests (always run) - OntologyEntry, path helpers
2. FAISS + sentence-transformers integration (skipped if deps missing)
"""

import json
from pathlib import Path

import pytest

from ontology_mapper.vector_index import (
    OntologyEntry,
    _index_path,
    _metadata_path,
    index_dir_for,
)

try:
    import faiss
    from sentence_transformers import SentenceTransformer

    HAS_VECTOR_DEPS = True
except ImportError:
    HAS_VECTOR_DEPS = False

vector_deps = pytest.mark.skipif(
    not HAS_VECTOR_DEPS, reason="faiss/sentence-transformers not installed"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_specs_dir(tmp_path, monkeypatch):
    """Redirect specs dir to a temp directory for isolation."""
    specs = tmp_path / "specs"
    specs.mkdir()
    monkeypatch.setattr(
        "ontology_mapper.vector_index.resolve_specs_dir", lambda: specs
    )
    return specs


@pytest.fixture
def sample_entries():
    """A small set of OntologyEntry objects for testing."""
    return [
        OntologyEntry(
            id="ex:PersonType",
            definition="A data type for a human being",
            kind="type",
            context="Base type: structures:ObjectType",
            metadata={"namespace": "http://example.com/person"},
        ),
        OntologyEntry(
            id="ex:VehicleType",
            definition="A data type for a conveyance used to carry people or cargo",
            kind="type",
            context="Base type: structures:ObjectType",
            metadata={"namespace": "http://example.com/vehicle"},
        ),
        OntologyEntry(
            id="ex:personName",
            definition="A name of a person",
            kind="property",
            metadata={"namespace": "http://example.com/person"},
        ),
        OntologyEntry(
            id="ex:vehicleMake",
            definition="A manufacturer of a vehicle",
            kind="property",
            context="Containing type: ex:VehicleType",
        ),
    ]


# ===========================================================================
# Pure logic tests — always run
# ===========================================================================


class TestOntologyEntry:
    """Tests for the OntologyEntry dataclass."""

    def test_embedding_text_all_fields(self):
        entry = OntologyEntry(
            id="j:ArrestType",
            definition="A data type for an arrest",
            kind="type",
            context="Base type: structures:ObjectType",
        )
        assert entry.embedding_text() == (
            "j:ArrestType. A data type for an arrest. Base type: structures:ObjectType"
        )

    def test_embedding_text_no_context(self):
        entry = OntologyEntry(
            id="j:ArrestType",
            definition="A data type for an arrest",
            kind="type",
        )
        assert entry.embedding_text() == "j:ArrestType. A data type for an arrest"

    def test_embedding_text_empty_definition(self):
        entry = OntologyEntry(id="j:ArrestType", definition="", kind="type")
        assert entry.embedding_text() == "j:ArrestType"

    def test_embedding_text_empty_definition_and_context(self):
        entry = OntologyEntry(
            id="j:ArrestType", definition="", kind="type", context=""
        )
        assert entry.embedding_text() == "j:ArrestType"

    def test_embedding_text_empty_definition_with_context(self):
        entry = OntologyEntry(
            id="j:ArrestType",
            definition="",
            kind="type",
            context="Base type: structures:ObjectType",
        )
        # definition is empty so only id + context
        assert entry.embedding_text() == (
            "j:ArrestType. Base type: structures:ObjectType"
        )

    def test_default_context_is_empty(self):
        entry = OntologyEntry(id="x:Foo", definition="A foo", kind="type")
        assert entry.context == ""

    def test_default_metadata_is_empty_dict(self):
        entry = OntologyEntry(id="x:Foo", definition="A foo", kind="type")
        assert entry.metadata == {}

    def test_metadata_default_not_shared(self):
        """Ensure default metadata dict is not shared across instances."""
        a = OntologyEntry(id="a", definition="", kind="type")
        b = OntologyEntry(id="b", definition="", kind="type")
        a.metadata["key"] = "value"
        assert "key" not in b.metadata


class TestPathHelpers:
    """Tests for index path helper functions."""

    def test_index_dir_for(self, mock_specs_dir):
        result = index_dir_for("niem-6.0")
        assert result == mock_specs_dir / "vector" / "indexes" / "niem-6.0"

    def test_index_path(self, mock_specs_dir):
        result = _index_path("niem-6.0", "types")
        assert result == mock_specs_dir / "vector" / "indexes" / "niem-6.0" / "types.faiss"

    def test_metadata_path(self, mock_specs_dir):
        result = _metadata_path("niem-6.0", "types")
        assert result == mock_specs_dir / "vector" / "indexes" / "niem-6.0" / "types.meta.json"

    def test_index_path_property_kind(self, mock_specs_dir):
        result = _index_path("niem-6.0", "properties")
        assert result == mock_specs_dir / "vector" / "indexes" / "niem-6.0" / "properties.faiss"

    def test_metadata_path_property_kind(self, mock_specs_dir):
        result = _metadata_path("niem-6.0", "properties")
        assert result == (
            mock_specs_dir / "vector" / "indexes" / "niem-6.0" / "properties.meta.json"
        )


# ===========================================================================
# Integration tests — require FAISS + sentence-transformers
# ===========================================================================


@vector_deps
class TestEmbedTexts:
    """Tests for the embed_texts function."""

    def test_returns_correct_shape(self):
        from ontology_mapper.vector_index import embed_texts

        texts = ["A person", "A vehicle", "An organization"]
        result = embed_texts(texts)
        assert result.shape[0] == 3
        assert result.shape[1] > 0

    def test_single_text(self):
        from ontology_mapper.vector_index import embed_texts

        result = embed_texts(["hello world"])
        assert result.shape[0] == 1
        assert result.shape[1] > 0


@vector_deps
class TestBuildIndex:
    """Tests for the build_index function."""

    def test_build_returns_index_and_metadata(self, sample_entries):
        from ontology_mapper.vector_index import build_index

        index, metadata_list = build_index(sample_entries)
        assert index.ntotal == len(sample_entries)
        assert len(metadata_list) == len(sample_entries)

    def test_metadata_has_required_keys(self, sample_entries):
        from ontology_mapper.vector_index import build_index

        _, metadata_list = build_index(sample_entries)
        for meta in metadata_list:
            assert "id" in meta
            assert "definition" in meta
            assert "kind" in meta

    def test_empty_entries_raises(self):
        from ontology_mapper.vector_index import build_index

        with pytest.raises(ValueError, match="empty"):
            build_index([])


@vector_deps
class TestSaveLoadRoundtrip:
    """Tests for save_index and load_index roundtrip."""

    def test_save_and_load(self, mock_specs_dir, sample_entries):
        from ontology_mapper.vector_index import (
            build_index,
            load_index,
            save_index,
        )

        index, metadata_list = build_index(sample_entries)
        save_index("test-ontology", "types", index, metadata_list)

        loaded_index, loaded_meta = load_index("test-ontology", "types")
        assert loaded_index.ntotal == index.ntotal
        assert len(loaded_meta) == len(metadata_list)
        assert loaded_meta[0]["id"] == metadata_list[0]["id"]

    def test_load_nonexistent_raises(self, mock_specs_dir):
        from ontology_mapper.vector_index import load_index

        with pytest.raises(FileNotFoundError):
            load_index("nonexistent-ontology", "types")


@vector_deps
class TestIndexExists:
    """Tests for index_exists function."""

    def test_exists_after_save(self, mock_specs_dir, sample_entries):
        from ontology_mapper.vector_index import (
            build_index,
            index_exists,
            save_index,
        )

        index, metadata_list = build_index(sample_entries)
        save_index("test-ontology", "types", index, metadata_list)
        assert index_exists("test-ontology", "types") is True

    def test_not_exists_for_nonexistent(self, mock_specs_dir):
        from ontology_mapper.vector_index import index_exists

        assert index_exists("nonexistent", "types") is False


@vector_deps
class TestDeleteIndex:
    """Tests for delete_index function."""

    def test_delete_removes_directory(self, mock_specs_dir, sample_entries):
        from ontology_mapper.vector_index import (
            build_index,
            delete_index,
            index_exists,
            save_index,
        )

        index, metadata_list = build_index(sample_entries)
        save_index("test-ontology", "types", index, metadata_list)
        assert index_exists("test-ontology", "types") is True

        result = delete_index("test-ontology")
        assert result is True
        assert index_exists("test-ontology", "types") is False

    def test_delete_nonexistent_returns_false(self, mock_specs_dir):
        from ontology_mapper.vector_index import delete_index

        result = delete_index("nonexistent")
        assert result is False


@vector_deps
class TestListIndexes:
    """Tests for list_indexes function."""

    def test_list_after_save(self, mock_specs_dir, sample_entries):
        from ontology_mapper.vector_index import (
            build_index,
            list_indexes,
            save_index,
        )

        index, metadata_list = build_index(sample_entries)
        save_index("test-ontology", "types", index, metadata_list)

        results = list_indexes()
        assert len(results) >= 1
        ontology_names = [r["ontology"] for r in results]
        assert "test-ontology" in ontology_names

        entry = next(r for r in results if r["ontology"] == "test-ontology")
        assert len(entry["indexes"]) == 1
        assert entry["indexes"][0]["kind"] == "types"
        assert entry["indexes"][0]["vectors"] == len(sample_entries)

    def test_list_empty(self, mock_specs_dir):
        from ontology_mapper.vector_index import list_indexes

        results = list_indexes()
        assert results == []


@vector_deps
class TestQueryIndex:
    """Tests for query_index function."""

    def test_query_returns_correct_structure(self, mock_specs_dir, sample_entries):
        from ontology_mapper.vector_index import (
            build_index,
            query_index,
            save_index,
        )

        # Build and save a target index from sample entries
        index, metadata_list = build_index(sample_entries)
        save_index("target-ontology", "types", index, metadata_list)

        # Query with a couple of entries
        query_entries = [
            OntologyEntry(
                id="q:Human",
                definition="A human being",
                kind="type",
            ),
        ]
        results = query_index(query_entries, "target-ontology", "types", top_k=3)

        assert len(results) == 1
        result = results[0]

        # Check top-level structure
        assert "query" in result
        assert "matches" in result
        assert result["query"]["id"] == "q:Human"

        # Check matches structure
        assert len(result["matches"]) > 0
        match = result["matches"][0]
        assert "rank" in match
        assert "score" in match
        assert "id" in match
        assert "definition" in match
        assert match["rank"] == 1
        assert isinstance(match["score"], float)
