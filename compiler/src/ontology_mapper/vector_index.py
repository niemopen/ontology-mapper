#!/usr/bin/env python3
"""Ontology-agnostic vector index for semantic similarity matching.

Builds FAISS indexes from ontology entries (types or properties) and
supports cross-ontology querying.  No ontology-specific logic lives here;
adapters convert specific formats (NIEM catalog, concept inventory, etc.)
into the generic OntologyEntry format before indexing.

Each ontology gets its own pair of indexes (types + properties) stored
under specs/vector/indexes/{ontology_name}/.  Indexes are built once and
persisted until explicitly rebuilt or deleted.

Embedding model: BAAI/bge-large-en-v1.5 (1024-dim, local, no API key).
Vector store: FAISS (flat L2 index — exact search, fast at our scale).

Usage as library:
    from ontology_mapper.vector_index import (
        OntologyEntry, build_index, load_index, query_index,
        save_index, index_dir_for,
    )

Usage via CLI:
    om-build-vector-index --adapter catalog --ontology niem --version 6.0
    om-build-vector-index --adapter source --ontology redvale-dbpi --run-dir {path}
    om-build-vector-index --ontology niem-6.0 --delete
    om-vector-search --source redvale-dbpi --target niem-6.0 --top-k 20
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from ontology_mapper.run_dir_utils import resolve_specs_dir


# ---------------------------------------------------------------------------
# Data model — ontology-agnostic
# ---------------------------------------------------------------------------

@dataclass
class OntologyEntry:
    """A single type or property from any ontology.

    The embedding text is built from id + definition + context fields.
    Metadata carries ontology-specific structural info (base type,
    inheritance chain, augmentation, etc.) that is NOT embedded but is
    available for post-retrieval reasoning.
    """
    id: str                          # Qualified name (e.g., "j:ArrestType", "dbpi:Inspection")
    definition: str                  # Natural language definition
    kind: str                        # "type" or "property"
    context: str = ""                # Additional embedding text (base type, range, containing types)
    metadata: dict = field(default_factory=dict)  # Structural info, not embedded
    label: str = ""                  # Human-readable name (replaces id in embeddings when present)

    def embedding_text(self) -> str:
        """Build the text string that gets embedded as a vector."""
        parts = [self.label or self.id]
        if self.definition:
            parts.append(self.definition)
        if self.context:
            parts.append(self.context)
        return ". ".join(parts)


# ---------------------------------------------------------------------------
# Index storage paths
# ---------------------------------------------------------------------------

def _vector_dir() -> Path:
    """Return the root vector directory (specs/vector/)."""
    return resolve_specs_dir() / "vector"


def index_dir_for(ontology_name: str) -> Path:
    """Return the directory where indexes for an ontology are stored."""
    return _vector_dir() / "indexes" / ontology_name


def _index_path(ontology_name: str, kind: str) -> Path:
    """Return path to a specific FAISS index file."""
    return index_dir_for(ontology_name) / f"{kind}.faiss"


def _metadata_path(ontology_name: str, kind: str) -> Path:
    """Return path to the metadata sidecar for an index."""
    return index_dir_for(ontology_name) / f"{kind}.meta.json"


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

_model = None


def _model_cache_dir() -> Path:
    """Return the directory for cached embedding models (specs/vector/model/)."""
    return _vector_dir() / "model"


def _get_model(allow_download: bool = False):
    """Lazy-load the sentence-transformers embedding model from the local cache.

    By default, the model must already be cached in specs/vector/model/.
    Pass allow_download=True (used by om-build-vector-index) to permit
    downloading from Hugging Face on first use.
    """
    global _model
    if _model is None:
        model_name = os.environ.get(
            "SC_EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5"
        )
        cache_dir = _model_cache_dir()
        if not allow_download:
            # Model must already be cached — fail fast if not present
            model_subdir = cache_dir / f"models--{model_name.replace('/', '--')}"
            if not model_subdir.exists():
                raise FileNotFoundError(
                    f"Embedding model not cached at {cache_dir}. "
                    f"Run 'om-build-vector-index' to download and cache the model."
                )
            # Prevent HF hub checks and suppress verbose loading output.
            # Must be set before importing sentence_transformers.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        else:
            cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for vector indexing. "
                "Install with: pip install ontology-mapper[vector]"
            )
        if allow_download:
            _model = SentenceTransformer(model_name, cache_folder=str(cache_dir))
        else:
            # Suppress safetensors LOAD REPORT and progress bars.
            # safetensors writes directly to C file descriptors, so we
            # redirect at the OS level, not just Python sys.stdout.
            _old_out_fd = os.dup(1)
            _old_err_fd = os.dup(2)
            _devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(_devnull, 1)
            os.dup2(_devnull, 2)
            try:
                _model = SentenceTransformer(model_name, cache_folder=str(cache_dir))
            finally:
                os.dup2(_old_out_fd, 1)
                os.dup2(_old_err_fd, 2)
                os.close(_old_out_fd)
                os.close(_old_err_fd)
                os.close(_devnull)
    return _model


def embed_texts(texts: list[str], batch_size: int = 64, allow_download: bool = False) -> "numpy.ndarray":
    """Embed a list of text strings into vectors.

    Returns a numpy array of shape (len(texts), embedding_dim).
    """
    import numpy as np
    model = _get_model(allow_download=allow_download)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=len(texts) > 100,
        normalize_embeddings=True,  # unit vectors for cosine similarity via dot product
    )
    return np.array(embeddings, dtype=np.float32)


# ---------------------------------------------------------------------------
# Index operations
# ---------------------------------------------------------------------------

def build_index(entries: list[OntologyEntry]) -> tuple:
    """Build a FAISS index from ontology entries.

    Returns (faiss_index, metadata_list) where metadata_list[i]
    corresponds to the i-th vector in the index.
    """
    import faiss
    import numpy as np

    if not entries:
        raise ValueError("Cannot build index from empty entry list")

    texts = [e.embedding_text() for e in entries]
    vectors = embed_texts(texts, allow_download=True)

    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)  # Inner product = cosine similarity (vectors are normalized)
    index.add(vectors)

    metadata_list = [asdict(e) for e in entries]

    return index, metadata_list


def save_index(ontology_name: str, kind: str, index, metadata_list: list):
    """Save a FAISS index and its metadata sidecar to disk."""
    import faiss

    out_dir = index_dir_for(ontology_name)
    out_dir.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(_index_path(ontology_name, kind)))

    meta_path = _metadata_path(ontology_name, kind)
    meta_path.write_text(
        json.dumps(metadata_list, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_index(ontology_name: str, kind: str) -> tuple:
    """Load a FAISS index and its metadata from disk.

    Returns (faiss_index, metadata_list).
    Raises FileNotFoundError if the index doesn't exist.
    """
    import faiss

    idx_path = _index_path(ontology_name, kind)
    meta_path = _metadata_path(ontology_name, kind)

    if not idx_path.exists():
        raise FileNotFoundError(f"No {kind} index for '{ontology_name}': {idx_path}")
    if not meta_path.exists():
        raise FileNotFoundError(f"No {kind} metadata for '{ontology_name}': {meta_path}")

    index = faiss.read_index(str(idx_path))
    metadata_list = json.loads(meta_path.read_text(encoding="utf-8"))

    return index, metadata_list


def index_exists(ontology_name: str, kind: str) -> bool:
    """Check whether an index exists on disk."""
    return _index_path(ontology_name, kind).exists()


def delete_index(ontology_name: str):
    """Delete all indexes for an ontology."""
    import shutil
    d = index_dir_for(ontology_name)
    if d.exists():
        shutil.rmtree(d)
        return True
    return False


def list_indexes() -> list[dict]:
    """List all ontology indexes that exist on disk."""
    indexes_root = _vector_dir() / "indexes"
    if not indexes_root.is_dir():
        return []
    results = []
    for d in sorted(indexes_root.iterdir()):
        if not d.is_dir():
            continue
        entry = {"ontology": d.name, "indexes": []}
        for f in sorted(d.glob("*.faiss")):
            kind = f.stem
            meta_path = d / f"{kind}.meta.json"
            count = 0
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                count = len(meta)
            entry["indexes"].append({"kind": kind, "vectors": count})
        if entry["indexes"]:
            results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def query_index(
    query_entries: list[OntologyEntry],
    target_ontology: str,
    target_kind: str,
    top_k: int = 20,
) -> list[dict]:
    """Query a target index with source entries.

    Returns a list of result dicts, one per query entry:
    {
        "query": {id, definition, kind, ...},
        "matches": [
            {"rank": 1, "score": 0.87, "id": "...", "definition": "...", ...},
            ...
        ]
    }
    """
    index, metadata_list = load_index(target_ontology, target_kind)

    texts = [e.embedding_text() for e in query_entries]
    query_vectors = embed_texts(texts)

    k = min(top_k, index.ntotal)
    scores, indices = index.search(query_vectors, k)

    results = []
    for i, entry in enumerate(query_entries):
        matches = []
        for rank, (score, idx) in enumerate(zip(scores[i], indices[i])):
            if idx == -1:
                continue
            meta = metadata_list[idx]
            meta_dict = meta.get("metadata", {})
            label = meta.get("label", "")
            matches.append({
                "rank": rank + 1,
                "score": float(score),
                "id": label or meta["id"],
                "qname": meta["id"],
                "label": label,
                "namespace": meta_dict.get("namespace", ""),
                "definition": meta["definition"],
                "kind": meta["kind"],
                "context": meta.get("context", ""),
                "metadata": meta_dict,
            })
        results.append({
            "query": asdict(entry),
            "matches": matches,
        })

    return results


def cross_query(
    source_ontology: str,
    target_ontology: str,
    kind: str = "types",
    top_k: int = 20,
) -> list[dict]:
    """Cross-query: load source entries and query against target index.

    Convenience wrapper that loads the source metadata (as entries),
    then queries the target index.
    """
    _, source_meta = load_index(source_ontology, kind)

    source_entries = [
        OntologyEntry(
            id=m["id"],
            definition=m["definition"],
            kind=m["kind"],
            context=m.get("context", ""),
        )
        for m in source_meta
    ]

    return query_index(source_entries, target_ontology, kind, top_k=top_k)
