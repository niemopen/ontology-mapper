#!/usr/bin/env python3
"""Catalog search — filter reference catalog types and properties by query.

This is a catalog lookup, not a vector search. The user types characters and
the catalog filters by qualified name, local name, and namespace. Designed
for Stage 5 review when the reviewer needs to find types or properties in
the target ontology that the LLM may not have presented as candidates.

The core function ``search_catalog()`` is a pure function (no I/O) that
both CLI and web UI can call.
"""

import argparse
import io
import json
import sys
from pathlib import Path


def search_catalog(catalog, query, kind=None, namespace=None, max_results=20):
    """Search the reference catalog for types and/or properties matching a query.

    Matching is case-insensitive substring against qualified name, local name,
    and definition. Results are ranked: exact local-name match first, then
    prefix match on local name, then substring match on qname, then definition
    match.

    Args:
        catalog: Reference catalog dict (as loaded from JSON).
        query: Search string (case-insensitive).
        kind: ``"type"``, ``"property"``, or ``None`` for both.
        namespace: Optional namespace prefix filter (e.g., ``"nc"``).
        max_results: Maximum number of results to return (default 20).

    Returns:
        Dict with ``types`` and ``properties`` lists. Each type result has
        ``qname``, ``definition``, ``pattern``, ``propertyCount``. Each
        property result has ``qualifiedProperty``, ``definition``,
        ``containingTypes``.
    """
    q = query.lower()
    type_results = []
    prop_results = []

    if kind in (None, "type"):
        type_results = _search_types(catalog, q, namespace, max_results)

    if kind in (None, "property"):
        prop_results = _search_properties(catalog, q, namespace, max_results)

    return {"types": type_results, "properties": prop_results}


def _search_types(catalog, query, namespace, max_results):
    """Search catalog types by query string."""
    results = []
    for t in catalog.get("types", []):
        qname = t.get("qname", "")
        if namespace and not qname.startswith(namespace + ":"):
            continue

        local = qname.split(":")[-1] if ":" in qname else qname
        definition = t.get("definition", "")
        rank = _rank_match(query, qname, local, definition)
        if rank is None:
            continue

        results.append((rank, {
            "qname": qname,
            "definition": definition,
            "pattern": t.get("pattern", ""),
            "propertyCount": len(t.get("properties", [])),
        }))

    results.sort(key=lambda x: x[0])
    return [r[1] for r in results[:max_results]]


def _search_properties(catalog, query, namespace, max_results):
    """Search catalog properties by query string."""
    results = []
    prop_index = catalog.get("propertyIndex", {})
    for ns, ns_data in prop_index.items():
        if namespace and ns != namespace:
            continue
        for p in ns_data.get("properties", []):
            qp = p.get("qualifiedProperty", "")
            local = p.get("name", "")
            definition = p.get("definition", "")
            rank = _rank_match(query, qp, local, definition)
            if rank is None:
                continue

            results.append((rank, {
                "qualifiedProperty": qp,
                "definition": definition,
                "containingTypes": p.get("containingTypes", []),
            }))

    results.sort(key=lambda x: x[0])
    return [r[1] for r in results[:max_results]]


def _rank_match(query, qname, local, definition):
    """Rank a match by relevance. Returns None if no match.

    Ranking (lower is better):
      0 — exact local name match
      1 — local name starts with query
      2 — qname contains query
      3 — definition contains query
    """
    q = query.lower()
    local_lower = local.lower()
    qname_lower = qname.lower()
    def_lower = definition.lower()

    if local_lower == q:
        return 0
    if local_lower.startswith(q):
        return 1
    if q in qname_lower:
        return 2
    if q in def_lower:
        return 3
    return None


def format_type_results(results):
    """Format type search results for CLI display.

    Args:
        results: List of type result dicts from search_catalog().

    Returns:
        Multi-line string.
    """
    if not results:
        return "  No matching types."

    lines = [f"  Types ({len(results)} results):"]
    for t in results:
        qname = t["qname"]
        defn = t["definition"][:80] if t["definition"] else ""
        props = t["propertyCount"]
        pattern = t["pattern"]
        lines.append(f"    {qname}  [{pattern}, {props} props]")
        if defn:
            lines.append(f"      {defn}{'...' if len(t['definition']) > 80 else ''}")
    return "\n".join(lines)


def format_property_results(results):
    """Format property search results for CLI display.

    Args:
        results: List of property result dicts from search_catalog().

    Returns:
        Multi-line string.
    """
    if not results:
        return "  No matching properties."

    lines = [f"  Properties ({len(results)} results):"]
    for p in results:
        qp = p["qualifiedProperty"]
        defn = p["definition"][:80] if p["definition"] else ""
        types = p.get("containingTypes", [])
        type_str = ", ".join(types[:3])
        if len(types) > 3:
            type_str += f", ... (+{len(types) - 3})"
        lines.append(f"    {qp}")
        if defn:
            lines.append(f"      {defn}{'...' if len(p['definition']) > 80 else ''}")
        if type_str:
            lines.append(f"      On: {type_str}")
    return "\n".join(lines)


def main():
    """CLI entry point for catalog search."""
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    parser = argparse.ArgumentParser(
        description="Search a reference catalog for types and properties"
    )
    parser.add_argument("query", help="Search string (case-insensitive)")
    parser.add_argument(
        "--catalog", required=True,
        help="Path to reference catalog JSON file",
    )
    parser.add_argument(
        "--kind", choices=["type", "property"],
        help="Search only types or only properties (default: both)",
    )
    parser.add_argument(
        "--namespace", help="Filter by namespace prefix (e.g., 'nc')",
    )
    parser.add_argument(
        "--max-results", type=int, default=20,
        help="Maximum results per category (default: 20)",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    catalog_path = Path(args.catalog)
    if not catalog_path.exists():
        print(f"Error: catalog not found: {catalog_path}", file=sys.stderr)
        raise SystemExit(1)

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    results = search_catalog(
        catalog, args.query,
        kind=args.kind,
        namespace=args.namespace,
        max_results=args.max_results,
    )

    if args.json_output:
        print(json.dumps(results, indent=2))
    else:
        if results["types"]:
            print(format_type_results(results["types"]))
        if results["properties"]:
            if results["types"]:
                print()
            print(format_property_results(results["properties"]))
        if not results["types"] and not results["properties"]:
            print(f"  No results for '{args.query}'.")
