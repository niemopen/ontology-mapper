#!/usr/bin/env python3
"""Cross-ontology semantic similarity search via vector indexes.

Queries a source ontology's entries against a target ontology's index
(or vice versa) and produces ranked candidate lists.

Usage:
    om-vector-search --source redvale-dbpi --target niem-6.0 --top-k 20
    om-vector-search --source redvale-dbpi --target niem-6.0 --kind types
    om-vector-search --source redvale-dbpi --target niem-6.0 --kind properties
    om-vector-search --source redvale-dbpi --target niem-6.0 --bidirectional
    om-vector-search --source redvale-dbpi --target niem-6.0 --output results.json
"""

import json
import sys


def run_search(source: str, target: str, kind: str, top_k: int,
               bidirectional: bool = False) -> dict:
    """Run a cross-ontology similarity search.

    Returns a results dict with forward matches (source -> target)
    and optionally reverse matches (target -> source).
    """
    from ontology_mapper.vector_index import cross_query, index_exists

    if not index_exists(source, kind):
        print(f"Error: No {kind} index for source '{source}'", file=sys.stderr)
        sys.exit(1)
    if not index_exists(target, kind):
        print(f"Error: No {kind} index for target '{target}'", file=sys.stderr)
        sys.exit(1)

    print(f"Searching: {source} -> {target} ({kind}, top-{top_k})")
    forward = cross_query(source, target, kind, top_k=top_k)
    print(f"  {len(forward)} source entries queried")

    results = {
        "source": source,
        "target": target,
        "kind": kind,
        "topK": top_k,
        "forward": forward,
    }

    if bidirectional:
        print(f"Searching: {target} -> {source} ({kind}, top-{top_k})")
        reverse = cross_query(target, source, kind, top_k=top_k)
        print(f"  {len(reverse)} target entries queried")
        results["reverse"] = reverse

        # Compute mutual nearest neighbors
        mutual = _find_mutual_matches(forward, reverse)
        results["mutualMatches"] = mutual
        print(f"  {len(mutual)} mutual nearest-neighbor pairs found")

    return results


def _find_mutual_matches(forward: list[dict], reverse: list[dict]) -> list[dict]:
    """Find mutual nearest neighbors between forward and reverse searches.

    A mutual match occurs when source A's top match is target B,
    AND target B's top match is source A.
    """
    # Build forward map: source_id -> top target_id
    fwd_top = {}
    for result in forward:
        source_id = result["query"]["id"]
        if result["matches"]:
            fwd_top[source_id] = result["matches"][0]["id"]

    # Build reverse map: target_id -> top source_id
    rev_top = {}
    for result in reverse:
        target_id = result["query"]["id"]
        if result["matches"]:
            rev_top[target_id] = result["matches"][0]["id"]

    # Find mutual pairs
    mutual = []
    for source_id, target_id in fwd_top.items():
        if rev_top.get(target_id) == source_id:
            # Get scores from both directions
            fwd_score = next(
                r["matches"][0]["score"]
                for r in forward
                if r["query"]["id"] == source_id
            )
            rev_score = next(
                r["matches"][0]["score"]
                for r in reverse
                if r["query"]["id"] == target_id
            )
            mutual.append({
                "sourceId": source_id,
                "targetId": target_id,
                "forwardScore": fwd_score,
                "reverseScore": rev_score,
                "combinedScore": (fwd_score + rev_score) / 2,
            })

    mutual.sort(key=lambda m: m["combinedScore"], reverse=True)
    return mutual


def print_summary(results: dict):
    """Print a human-readable summary of search results."""
    kind = results["kind"]
    forward = results["forward"]

    print(f"\n{'='*70}")
    print(f"  {results['source']} -> {results['target']}  ({kind})")
    print(f"{'='*70}")

    for result in forward:
        query_id = result["query"]["id"]
        query_def = result["query"]["definition"]
        print(f"\n  {query_id}")
        print(f"    \"{query_def}\"" if query_def else "    (no definition)")
        print(f"    {'─'*60}")
        for m in result["matches"][:5]:
            ns = f" ({m['namespace']})" if m.get("namespace") else ""
            print(f"    {m['rank']:>2}. [{m['score']:.3f}] {m['id']}{ns}")
            print(f"        \"{m['definition']}\"" if m["definition"] else "        (no definition)")

    if "mutualMatches" in results:
        mutual = results["mutualMatches"]
        print(f"\n{'='*70}")
        print(f"  Mutual nearest neighbors ({len(mutual)} pairs)")
        print(f"{'='*70}")
        for m in mutual:
            print(f"  {m['sourceId']:<40} <-> {m['targetId']}")
            print(f"    forward={m['forwardScore']:.3f}  reverse={m['reverseScore']:.3f}  combined={m['combinedScore']:.3f}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Cross-ontology semantic similarity search"
    )
    parser.add_argument("--source", required=True, help="Source ontology name")
    parser.add_argument("--target", required=True, help="Target ontology name")
    parser.add_argument("--kind", choices=["types", "properties"], default="types",
                        help="What to search (default: types)")
    parser.add_argument("--top-k", type=int, default=20,
                        help="Number of matches per entry (default: 20)")
    parser.add_argument("--bidirectional", action="store_true",
                        help="Also search target -> source and find mutual matches")
    parser.add_argument("--output", default=None,
                        help="Write full results to JSON file")
    parser.add_argument("--quiet", action="store_true",
                        help="Only write output file, no console summary")
    args = parser.parse_args()

    results = run_search(
        args.source, args.target, args.kind, args.top_k,
        bidirectional=args.bidirectional,
    )

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nResults written to: {args.output}")

    if not args.quiet:
        print_summary(results)


if __name__ == "__main__":
    main()
