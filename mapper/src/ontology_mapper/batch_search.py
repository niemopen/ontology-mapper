#!/usr/bin/env python3
"""Batch vector search for all source concepts in a pipeline run.

Pre-populates search results so the evaluation step works exclusively with
JSON files instead of calling Python functions inline.

Writes separate files for types and properties:

- ``{run_dir}/search-results/types/{sanitized_qname}.json``
- ``{run_dir}/search-results/properties/{sanitized_prop_qname}.json``

Each file contains the source item, ranked candidates (filtered by score),
and an evaluation slot.  The evaluator processes each file independently,
then ``om-collect-alignments`` reassembles per-concept evaluations and
resolves actions.

Usage:
    om-batch-search --run-dir {run_dir} [--top-k 12] [--min-score-ratio 0.80]
"""

import json
from pathlib import Path

from ontology_mapper.pipeline_context import load_context
from ontology_mapper.vector_index import OntologyEntry, query_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_filename(qname: str) -> str:
    """Convert a qualified name to a safe filename stem.

    ``"dbpi:AddressType"`` -> ``"dbpi_AddressType"``
    """
    return qname.replace(":", "_")


def load_source_concepts(run_dir: Path) -> list[dict]:
    """Load the concepts list from source-concepts.json."""
    path = run_dir / "source-concepts.json"
    if not path.exists():
        raise FileNotFoundError(
            f"source-concepts.json not found in {run_dir}. "
            "Run 'om-build-strategy' first."
        )
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["concepts"]


def filter_candidates(candidates: list[dict], min_score_ratio: float) -> list[dict]:
    """Drop candidates scoring below ``min_score_ratio`` of the top score.

    Returns a new list (may be shorter than the input).  If the input is
    empty, returns an empty list.
    """
    if not candidates:
        return []
    top_score = candidates[0]["score"]
    if top_score <= 0:
        return candidates
    floor = top_score * min_score_ratio
    return [c for c in candidates if c["score"] >= floor]


def strip_scores(candidates: list[dict]) -> list[dict]:
    """Remove rank and score from candidates before writing to files.

    The evaluator reasons from definitions, not scores.  Array
    position preserves the original ranking.
    """
    return [{k: v for k, v in c.items() if k not in ("rank", "score")}
            for c in candidates]


def disambiguate_ids(candidates: list[dict]) -> list[dict]:
    """Suffix duplicate display ids within a candidate set.

    SALI labels can collide (660 duplicates across 18K types). When two
    candidates in the same search result share an id, the LLM can't
    distinguish them. Appends ' [1]', ' [2]' etc. to duplicates.
    """
    from collections import Counter
    ids = [c["id"] for c in candidates]
    counts = Counter(ids)
    dupes = {k for k, v in counts.items() if v > 1}
    if not dupes:
        return candidates
    seen: dict[str, int] = {}
    result = []
    for c in candidates:
        cid = c["id"]
        if cid in dupes:
            n = seen.get(cid, 0) + 1
            seen[cid] = n
            c = {**c, "id": f"{cid} [{n}]"}
        result.append(c)
    return result


def _property_qname(concept_qname: str, prop_name: str) -> str:
    """Build a property qname from the parent concept's prefix.

    ``("dbpi:AddressType", "streetName")`` -> ``"dbpi:streetName"``
    """
    prefix = concept_qname.split(":")[0] if ":" in concept_qname else ""
    return f"{prefix}:{prop_name}" if prefix else prop_name


# ---------------------------------------------------------------------------
# Search — types
# ---------------------------------------------------------------------------

def search_all_types(
    concepts: list[dict],
    target_index: str,
    top_k: int = 12,
) -> dict[str, list[dict]]:
    """Query the target type index for every source concept in one batch.

    Returns ``{source_qname: [candidate_dicts]}`` where each candidate
    has rank, score, id, namespace, definition, kind, context, metadata.
    """
    entries = []
    qnames = []
    for c in concepts:
        qnames.append(c["qname"])
        entries.append(OntologyEntry(
            id=c["qname"],
            definition=c.get("definition", ""),
            kind="type",
            context="; ".join(c.get("superClasses", [])),
        ))

    results = query_index(entries, target_index, "types", top_k=top_k)

    return {qnames[i]: r["matches"] for i, r in enumerate(results)}


# ---------------------------------------------------------------------------
# Search — properties
# ---------------------------------------------------------------------------

def search_all_properties(
    concepts: list[dict],
    target_index: str,
    top_k: int = 12,
) -> dict[str, dict[str, list[dict]]]:
    """Query the target property index for every source property in one batch.

    Returns ``{source_qname: {prop_qname: [candidate_dicts]}}``.
    The parent concept's definition is included as context for each
    property's embedding, giving the model richer semantic signal.
    """
    entries = []
    # Track (concept_qname, prop_qname) for each entry so we can
    # reconstruct the nested dict from the flat results list.
    keys: list[tuple[str, str]] = []

    for c in concepts:
        concept_def = c.get("definition", "")
        for prop in c.get("properties", []):
            pq = _property_qname(c["qname"], prop["name"])
            keys.append((c["qname"], pq))
            entries.append(OntologyEntry(
                id=pq,
                definition=prop.get("definition", ""),
                kind="property",
                context=f"Property of {c['qname']}. {concept_def}",
            ))

    if not entries:
        return {}

    results = query_index(entries, target_index, "properties", top_k=top_k)

    out: dict[str, dict[str, list[dict]]] = {}
    for (cq, pq), r in zip(keys, results):
        out.setdefault(cq, {})[pq] = r["matches"]

    return out


# ---------------------------------------------------------------------------
# File assembly — types
# ---------------------------------------------------------------------------

def build_type_file(concept: dict, candidates: list[dict]) -> dict:
    """Assemble a per-type search result file."""
    return {
        "status": "pending",
        "kind": "type",
        "source": {
            "qname": concept["qname"],
            "localName": concept.get("localName", ""),
            "definition": concept.get("definition", ""),
            "superClasses": concept.get("superClasses", []),
        },
        "candidates": candidates,
        "evaluation": None,
    }


# ---------------------------------------------------------------------------
# File assembly — properties
# ---------------------------------------------------------------------------

def build_property_file(
    concept_qname: str,
    concept_definition: str,
    prop_name: str,
    prop_qname: str,
    prop_definition: str,
    prop_range: list,
    candidates: list[dict],
) -> dict:
    """Assemble a per-property search result file."""
    return {
        "status": "pending",
        "kind": "property",
        "source": {
            "qname": prop_qname,
            "name": prop_name,
            "definition": prop_definition,
            "range": prop_range,
            "parentType": concept_qname,
            "parentDefinition": concept_definition,
        },
        "candidates": candidates,
        "evaluation": None,
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _write_file(filepath: Path, doc: dict) -> bool:
    """Write a search-result file, skipping evaluated ones.

    Returns True if written, False if skipped.
    """
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
            if existing.get("status") == "evaluated":
                return False
        except (json.JSONDecodeError, KeyError):
            pass
    filepath.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def write_search_results(
    run_dir: Path,
    concepts: list[dict],
    type_results: dict[str, list[dict]],
    property_results: dict[str, dict[str, list[dict]]],
    min_score_ratio: float = 0.80,
) -> dict[str, int]:
    """Write type and property files to ``{run_dir}/search-results/``.

    Returns ``{"types_written", "types_skipped", "props_written",
    "props_skipped", "candidates_filtered"}`` counts.
    """
    types_dir = run_dir / "search-results" / "types"
    props_dir = run_dir / "search-results" / "properties"
    types_dir.mkdir(parents=True, exist_ok=True)
    props_dir.mkdir(parents=True, exist_ok=True)

    counts = {
        "types_written": 0, "types_skipped": 0,
        "props_written": 0, "props_skipped": 0,
        "candidates_filtered": 0,
    }

    for concept in concepts:
        qname = concept["qname"]
        prefix = qname.split(":")[0] if ":" in qname else ""

        # --- Type file ---
        raw_tc = type_results.get(qname, [])
        tc = filter_candidates(raw_tc, min_score_ratio)
        counts["candidates_filtered"] += len(raw_tc) - len(tc)
        doc = build_type_file(concept, disambiguate_ids(strip_scores(tc)))
        filepath = types_dir / (sanitize_filename(qname) + ".json")
        if _write_file(filepath, doc):
            counts["types_written"] += 1
        else:
            counts["types_skipped"] += 1

        # --- Property files ---
        concept_def = concept.get("definition", "")
        prop_cands = property_results.get(qname, {})
        for prop in concept.get("properties", []):
            pq = f"{prefix}:{prop['name']}" if prefix else prop["name"]
            raw_pc = prop_cands.get(pq, [])
            pc = filter_candidates(raw_pc, min_score_ratio)
            counts["candidates_filtered"] += len(raw_pc) - len(pc)

            doc = build_property_file(
                concept_qname=qname,
                concept_definition=concept_def,
                prop_name=prop["name"],
                prop_qname=pq,
                prop_definition=prop.get("definition", ""),
                prop_range=prop.get("range", []),
                candidates=disambiguate_ids(strip_scores(pc)),
            )
            filepath = props_dir / (sanitize_filename(pq) + ".json")
            if _write_file(filepath, doc):
                counts["props_written"] += 1
            else:
                counts["props_skipped"] += 1

    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Batch vector search for all source concepts in a run"
    )
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    parser.add_argument(
        "--top-k", type=int, default=25,
        help="Number of candidates per query (default: 25)",
    )
    parser.add_argument(
        "--min-score-ratio", type=float, default=0.75,
        help="Drop candidates below this fraction of rank 1's score (default: 0.75)",
    )
    args = parser.parse_args()

    ctx = load_context(args.run_dir)
    target_index = f"{ctx.target_ontology}-{ctx.target_version}"

    print(f"\nsc-batch-search")
    print(f"  Run:    {ctx.run_dir}")
    print(f"  Target: {target_index}")
    print(f"  Top-k:  {args.top_k}")
    print(f"  Score floor: {args.min_score_ratio:.0%} of rank 1")

    concepts = load_source_concepts(ctx.run_dir)
    print(f"  Source concepts: {len(concepts)}")

    total_props = sum(len(c.get("properties", [])) for c in concepts)
    print(f"  Source properties: {total_props}")

    print(f"\n  Searching type index...")
    type_results = search_all_types(concepts, target_index, top_k=args.top_k)

    print(f"  Searching property index...")
    property_results = search_all_properties(concepts, target_index, top_k=args.top_k)

    print(f"\n  Writing search result files...")
    counts = write_search_results(
        ctx.run_dir, concepts, type_results, property_results,
        min_score_ratio=args.min_score_ratio,
    )

    out_dir = ctx.run_dir / "search-results"
    print(f"\n  Output: {out_dir}")
    print(f"  Types:      {counts['types_written']} written, {counts['types_skipped']} skipped")
    print(f"  Properties: {counts['props_written']} written, {counts['props_skipped']} skipped")
    if counts["candidates_filtered"]:
        print(f"  Candidates filtered by score floor: {counts['candidates_filtered']}")
    print(f"  Done.")


if __name__ == "__main__":
    main()
