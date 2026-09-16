#!/usr/bin/env python3
"""Per-concept semantic search for the evaluation step.

The evaluator calls these functions one source concept at a time.
Each function queries the FAISS vector index and returns ranked candidates
for the evaluator to assess semantically.

The evaluator is responsible for:
  - Assessing candidates by comparing definitions and available data
  - Selecting target types and properties (never relying on search scores)
  - Passing its evaluation to resolve_alignment() for action determination

Usage:
    from ontology_mapper.semantic_search import search_type, search_property

    type_results = search_type(
        source_concept="court:HearingType",
        source_definition="A scheduled court proceeding.",
        target_ontology="niem-6.0",
        top_k=20,
    )

    property_results = search_property(
        source_property="court:hearingDate",
        source_definition="The date of the hearing.",
        target_ontology="niem-6.0",
        top_k=20,
    )
"""

from ontology_mapper.vector_index import OntologyEntry, query_index


def class_filter_for_index(index_name):
    """The native class predicate for an index, or None when no policy applies.

    None means the search keeps its bounded top-k retrieval; only a native
    policy justifies ranking the whole index before filtering.
    """
    import json
    from ontology_mapper.adapters.catalog_adapter import _find_catalog
    from ontology_mapper.ontology_specific import _any_class_target, class_target_filter

    name, separator, version = index_name.rpartition("-")
    if not separator:
        return None
    try:
        catalog_path = _find_catalog(name, version)
    except FileNotFoundError:
        return None  # Source/custom indexes may have no catalog.
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    predicate = class_target_filter(name, catalog, version)
    return None if predicate is _any_class_target else predicate


def match_predicate(eligible):
    """Lift a target-name predicate to the match dicts ``query_index`` ranks."""
    if eligible is None:
        return None
    return lambda match: eligible(match["qname"])


def search_type(
    source_concept: str,
    source_definition: str,
    target_ontology: str,
    top_k: int = 20,
    source_context: str = "",
) -> list[dict]:
    """Search the target ontology's type index for a single source concept.

    Args:
        source_concept: qualified name (e.g., "court:HearingType")
        source_definition: natural language definition
        target_ontology: target index name (e.g., "niem-6.0")
        top_k: number of candidates to return
        source_context: optional additional context for embedding

    Returns:
        List of candidate dicts, each with:
            rank, score, id, definition, namespace, kind, context, metadata
        Sorted by score descending (rank 1 = most similar).
    """
    entry = OntologyEntry(
        id=source_concept,
        definition=source_definition,
        kind="type",
        context=source_context,
    )
    results = query_index([entry], target_ontology, "types", top_k=top_k,
                          eligible=match_predicate(class_filter_for_index(target_ontology)))
    return results[0]["matches"] if results else []


def search_property(
    source_property: str,
    source_definition: str,
    target_ontology: str,
    top_k: int = 20,
    source_context: str = "",
) -> list[dict]:
    """Search the target ontology's property index for a single source property.

    Args:
        source_property: qualified name (e.g., "court:hearingDate")
        source_definition: natural language definition
        target_ontology: target index name (e.g., "niem-6.0")
        top_k: number of candidates to return
        source_context: optional additional context for embedding

    Returns:
        List of candidate dicts, each with:
            rank, score, id, definition, namespace, kind, context, metadata
        Sorted by score descending (rank 1 = most similar).
    """
    entry = OntologyEntry(
        id=source_property,
        definition=source_definition,
        kind="property",
        context=source_context,
    )
    results = query_index([entry], target_ontology, "properties", top_k=top_k)
    return results[0]["matches"] if results else []
