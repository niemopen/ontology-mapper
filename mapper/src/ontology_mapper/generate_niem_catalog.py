#!/usr/bin/env python3
"""Generate niem_reference_catalog.json from the NIEM API + GitHub CSVs.

Fetches all NIEM type patterns (object, augmentation, association,
complex_value, simple_value, simple_list, simple_union, metadata) from
core/domain namespaces and their property memberships,
then enriches with GitHub CSV data (facets, cardinalities, parent types,
type metadata). Builds an augmentation map linking augmentation types to the
base types they extend. Writes a versioned JSON catalog, a namespace-grouped
summary, and a compact one-line-per-type directory for efficient semantic
scanning during alignment.

Data sources and what each provides:

  NIEM API (structural skeleton):
    - Types, properties, namespaces, type hierarchy
    - Which properties belong to each type
    - Base type relationships (partial)

  GitHub CSVs (enrichment — data the API does not expose):
    - Facet.csv:                 Enumeration values for code-type types
    - Type.csv:                  ParentQualifiedType (more complete than API),
                                 ContentStyle, IsAugmentation, IsAdapter,
                                 IsMetadata flags
    - Property.csv:              Property definitions, property types,
                                 IsAbstract, SubstitutionGroupQualifiedProperty
    - TypeContainsProperty.csv:  MinOccurs/MaxOccurs cardinalities per property

Usage:
    om-generate-catalog --version 6.0 [--output specs/niem_reference_catalog_6.0.json]
    om-generate-catalog --version 6.0 --no-github-csv

The catalog is a deterministic snapshot: same NIEM version always
produces the same output. Regenerate when adopting a new NIEM version.

Requires network access to:
  - https://api.niemopen.org/v2 (public, no auth)
  - https://raw.githubusercontent.com/niemopen/niem-model (for CSV enrichment)
"""

import csv
import io
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# ─── Configuration ────────────────────────────────────────────────────────

API_BASE = "https://api.niemopen.org/v2/stewards/niem/models/model/versions"
PAGE_SIZE = 100  # Max items per page for paginated endpoints
RETRY_DELAY = 2  # Seconds between retries on API errors
MAX_RETRIES = 3

# Namespace categories to include (skip code tables, adapters, utilities, etc.)
INCLUDE_CATEGORIES = {"core", "domain"}

# Namespaces to exclude per NIEM expert guidance (not appropriate for
# general-purpose semantic mapping tools)
EXCLUDE_NAMESPACES = {"mo", "usmtf"}

# Type patterns to include (all NIEM patterns per expert guidance)
INCLUDE_PATTERNS = {
    "object", "augmentation", "association", "complex_value",
    "simple_value", "simple_list", "simple_union", "metadata",
}

# Additional specific types to include from utility/infrastructure namespaces
# (not matchable targets, but needed as base types in inheritance chains)
INCLUDE_EXTRA_TYPES = {"structures:ObjectType"}


# GitHub CSV configuration
GITHUB_CSV_BASE = "https://raw.githubusercontent.com/niemopen/niem-model"
# Tag mapping: NIEM version -> GitHub tag
GITHUB_TAG_MAP = {
    "6.0": "6.0-ps02",
}


# ─── API Helpers ──────────────────────────────────────────────────────────

def api_get(url):
    """Fetch JSON from the NIEM API with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                print(f"    Retry {attempt + 1}/{MAX_RETRIES} for {url}: {e}")
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(f"API request failed after {MAX_RETRIES} retries: {url}") from e


def fetch_paginated(url_template, version):
    """Fetch all pages from a paginated endpoint."""
    all_items = []
    page = 0
    while True:
        url = url_template.format(version=version, page=page, size=PAGE_SIZE)
        data = api_get(url)
        items = data.get("content", [])
        all_items.extend(items)
        if data.get("last", True):
            break
        page += 1
    return all_items


# ─── GitHub CSV Helpers ───────────────────────────────────────────────────

# Expected columns per CSV file. If NIEM changes these in a future version,
# update these sets alongside the new GITHUB_TAG_MAP entry.
EXPECTED_COLUMNS = {
    "Facet.csv": {"QualifiedType", "FacetName", "FacetValue", "Definition"},
    "Type.csv": {"QualifiedType", "ParentQualifiedType", "ContentStyle",
                 "IsAugmentation", "IsAdapter", "IsMetadata"},
    "Property.csv": {"QualifiedProperty", "Definition", "QualifiedType",
                     "IsAbstract", "SubstitutionGroupQualifiedProperty"},
    "TypeContainsProperty.csv": {"QualifiedType", "PropertyName", "MinOccurs", "MaxOccurs"},
}


def validate_csv_columns(filename, actual_columns):
    """Check that expected columns are present; warn about any missing ones."""
    expected = EXPECTED_COLUMNS.get(filename, set())
    missing = expected - set(actual_columns)
    if missing:
        print(f"    WARNING: {filename} is missing expected columns: {sorted(missing)}")
        print(f"    This may indicate a NIEM version CSV schema change.")
        return False
    return True


def fetch_github_csv(version, filename):
    """Fetch a CSV file from the NIEM GitHub repo for the given version."""
    tag = GITHUB_TAG_MAP.get(version, version)
    url = f"{GITHUB_CSV_BASE}/{tag}/csv/{filename}"
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                rows = list(reader)
                if rows:
                    validate_csv_columns(filename, rows[0].keys())
                return rows
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                print(f"    Retry {attempt + 1}/{MAX_RETRIES} for {filename}: {e}")
                time.sleep(RETRY_DELAY)
            else:
                print(f"    WARNING: Failed to fetch {filename} after {MAX_RETRIES} retries: {e}")
                return None


def parse_facets_csv(rows):
    """Build {QualifiedType: [{value, definition}]} from Facet.csv rows."""
    facets = defaultdict(list)
    for row in rows:
        qt = row.get("QualifiedType", "").strip()
        value = row.get("FacetValue", "").strip()
        definition = row.get("Definition", "").strip()
        facet_name = row.get("FacetName", "").strip()
        if qt and value and facet_name == "enumeration":
            facets[qt].append({"value": value, "definition": definition})
    for qt in facets:
        facets[qt].sort(key=lambda f: f["value"])
    return dict(facets)


def parse_types_csv(rows):
    """Build {QualifiedType: {parentType, contentStyle, flags}} from Type.csv."""
    types = {}
    for row in rows:
        qt = row.get("QualifiedType", "").strip()
        if not qt:
            continue
        types[qt] = {
            "parentType": row.get("ParentQualifiedType", "").strip() or None,
            "contentStyle": row.get("ContentStyle", "").strip() or None,
            "isAugmentation": row.get("IsAugmentation", "").strip().lower() == "true",
            "isAdapter": row.get("IsAdapter", "").strip().lower() == "true",
            "isMetadata": row.get("IsMetadata", "").strip().lower() == "true",
        }
    return types


def parse_type_contains_property_csv(rows):
    """Build {QualifiedType: {propName: {min, max}}} from TypeContainsProperty.csv."""
    cardinalities = defaultdict(dict)
    for row in rows:
        qt = row.get("QualifiedType", "").strip()
        prop_name = row.get("PropertyName", "").strip()
        if not qt or not prop_name:
            continue
        min_occ = row.get("MinOccurs", "0").strip()
        max_occ = row.get("MaxOccurs", "unbounded").strip()
        cardinalities[qt][prop_name] = {
            "min": int(min_occ) if min_occ.isdigit() else 0,
            "max": max_occ if max_occ == "unbounded" else int(max_occ) if max_occ.isdigit() else max_occ,
        }
    return dict(cardinalities)


def parse_property_csv(rows):
    """Build property lookup from Property.csv.

    Returns dict keyed by unqualified property name -> list of property defs.
    The list handles the case where the same unqualified name exists in
    multiple namespaces (e.g., nc:Date vs j:Date).
    """
    props = defaultdict(list)
    for row in rows:
        qprop = row.get("QualifiedProperty", "").strip()
        if not qprop:
            continue
        # Unqualified name is the part after the colon
        unqualified = qprop.split(":")[-1] if ":" in qprop else qprop
        prefix = qprop.split(":")[0] if ":" in qprop else ""
        is_abstract = row.get("IsAbstract", "").strip()
        props[unqualified].append({
            "qualifiedProperty": qprop,
            "prefix": prefix,
            "definition": row.get("Definition", "").strip(),
            "qualifiedType": row.get("QualifiedType", "").strip() or None,
            "isAbstract": is_abstract == "1" or is_abstract.lower() == "true",
            "substitutionGroup": row.get("SubstitutionGroupQualifiedProperty", "").strip() or None,
        })
    return dict(props)


def resolve_property_definition(prop_name, type_prefix, property_lookup):
    """Look up a property definition, preferring same-namespace match.

    Args:
        prop_name: Unqualified property name (e.g., "PersonName")
        type_prefix: Namespace prefix of the containing type (e.g., "nc")
        property_lookup: Output of parse_property_csv()

    Returns:
        Property definition dict or None if not found.
    """
    candidates = property_lookup.get(prop_name)
    if not candidates:
        return None
    # Prefer same namespace as the containing type
    for c in candidates:
        if c["prefix"] == type_prefix:
            return {
                "qualifiedProperty": c["qualifiedProperty"],
                "definition": c["definition"],
                "qualifiedType": c["qualifiedType"],
                "isAbstract": c["isAbstract"],
                "substitutionGroup": c["substitutionGroup"],
            }
    # No same-namespace match — take first candidate (no namespace preference)
    c = candidates[0]
    return {
        "qualifiedProperty": c["qualifiedProperty"],
        "definition": c["definition"],
        "qualifiedType": c["qualifiedType"],
        "isAbstract": c["isAbstract"],
        "substitutionGroup": c["substitutionGroup"],
    }


def build_inheritance_chain(qname, github_types):
    """Build the full inheritance chain from a type to its root.

    Returns ordered list from immediate parent to root, e.g.:
    ["nc:ActivityType", "structures:ObjectType"]

    Uses cycle detection to handle any circular references.
    """
    chain = []
    visited = {qname}
    current = qname
    while True:
        gt = github_types.get(current)
        if not gt:
            break
        parent = gt.get("parentType")
        if not parent or parent in visited:
            break
        chain.append(parent)
        visited.add(parent)
        current = parent
    return chain


# Patterns whose types are terminal for composition recursion. Value-pattern
# types (code tables, primitive wrappers, unions, lists) carry infrastructure
# properties (lang, truncationIndicator, etc.) rather than domain-meaningful
# ones. Recursing into them adds noise without useful semantic signal.
# Types not found in type_lookup are also naturally terminal (niem-xs:*, xs:*,
# external code table namespaces) because the lookup returns None.
TERMINAL_PATTERNS = {"complex_value", "simple_value", "simple_list", "simple_union"}


def compute_terminal_types(catalog_types):
    """Compute the set of types that should not be recursed into.

    Terminal types are value-pattern types (code tables, primitive wrappers,
    lists, unions) plus structures:ObjectType. Computed from the catalog so
    the set stays correct as NIEM versions change.
    """
    terminals = {"structures:ObjectType"}
    for t in catalog_types:
        if t.get("pattern") in TERMINAL_PATTERNS:
            terminals.add(t["qname"])
    return frozenset(terminals)


def build_reachable_properties(type_entry, type_lookup, max_depth=2,
                               terminal_types=None):
    """Pre-compute all properties reachable via inheritance + composition.

    Returns dict of {property_name: {qualifiedProperty, definition, qualifiedType,
    depth, path, via}}.

    - Inherited properties (via baseType/inheritanceChain) are at depth 0
    - Composition properties (via qualifiedType navigation) increase depth
    - Stops at terminal_types (value-pattern types) and max_depth
    - If terminal_types is None, computes it from type_lookup
    """
    if terminal_types is None:
        terminal_types = compute_terminal_types(type_lookup.values())

    result = {}
    visited_types = set()

    def _recurse(tqn, prefix, depth):
        if tqn in visited_types or depth > max_depth or not tqn:
            return
        visited_types.add(tqn)

        t = type_lookup.get(tqn)
        if not t:
            return

        # Own properties (from propertyDefinitions)
        for name, info in t.get("propertyDefinitions", {}).items():
            path = f"{prefix}/{name}" if prefix else name
            # Don't overwrite a shallower path to the same property
            if name in result and result[name]["depth"] <= depth:
                # But still record the deeper path variant with full path key
                if path not in result:
                    result[path] = {
                        "qualifiedProperty": info.get("qualifiedProperty", ""),
                        "definition": info.get("definition", ""),
                        "qualifiedType": info.get("qualifiedType"),
                        "depth": depth,
                        "path": path,
                        "via": tqn,
                    }
            else:
                result[name] = {
                    "qualifiedProperty": info.get("qualifiedProperty", ""),
                    "definition": info.get("definition", ""),
                    "qualifiedType": info.get("qualifiedType"),
                    "depth": depth,
                    "path": path,
                    "via": tqn,
                }

            # Follow composition (recurse into property's type)
            prop_type = info.get("qualifiedType")
            if prop_type and prop_type not in terminal_types and depth < max_depth:
                _recurse(prop_type, path, depth + 1)

        # Follow inheritance (baseType) — don't increment depth
        base = t.get("baseType")
        if base and base not in visited_types:
            _recurse(base, prefix, depth)

    _recurse(type_entry["qname"], "", 0)
    return result


def build_property_index(catalog_types, github_properties, github_cardinalities,
                         namespace_filter=None):
    """Build a namespace-grouped property index for cross-domain search.

    Returns dict of {namespace_prefix: {properties: [...], propertyCount: N}}.
    Each property includes name, qualifiedProperty, definition, qualifiedType,
    isAbstract, and containingTypes.

    If namespace_filter is provided, only includes properties from those namespaces.
    """
    # Build reverse index: qualifiedProperty -> list of containing types
    prop_to_types = defaultdict(set)
    for type_qname, props in github_cardinalities.items():
        type_prefix = type_qname.split(":")[0] if ":" in type_qname else ""
        for prop_name in props:
            # Resolve the qualified property name
            qprop = f"{type_prefix}:{prop_name}"
            prop_to_types[qprop].add(type_qname)

    # Also check the property definitions on catalog types for containing info
    for t in catalog_types:
        tqn = t["qname"]
        for prop_name, pd in t.get("propertyDefinitions", {}).items():
            qp = pd.get("qualifiedProperty", "")
            if qp:
                prop_to_types[qp].add(tqn)

    # Build namespace-grouped index from Property.csv data
    ns_index = defaultdict(list)
    for unqualified_name, defs in github_properties.items():
        for d in defs:
            qp = d["qualifiedProperty"]
            prefix = d["prefix"]
            if namespace_filter and prefix not in namespace_filter:
                continue
            ns_index[prefix].append({
                "name": unqualified_name,
                "qualifiedProperty": qp,
                "definition": d["definition"],
                "qualifiedType": d["qualifiedType"],
                "isAbstract": d["isAbstract"],
                "containingTypes": sorted(prop_to_types.get(qp, set())),
            })

    # Sort properties within each namespace by name
    result = {}
    for prefix in sorted(ns_index):
        props = sorted(ns_index[prefix], key=lambda p: p["name"])
        result[prefix] = {
            "properties": props,
            "propertyCount": len(props),
        }

    return result


def build_augmentation_map(catalog_types, type_properties):
    """Build a map of base type -> augmentation contributions.

    NIEM augmentation types inject properties into base types they don't own.
    The naming convention is: FooAugmentationType augments FooType. For example,
    j:CaseAugmentationType adds properties (j:CaseCourt, j:CaseJudge, etc.)
    to nc:CaseType via the nc:CaseAugmentationPoint slot.

    Returns:
        augmentations: dict of {base_type_qname: [{augType, properties}]}
            where properties is the list of property names the augmentation
            contributes (excluding the AugmentationPoint self-reference).
    """
    # Index: local base name -> list of qnames (e.g., "CaseType" -> ["nc:CaseType"])
    object_types_by_local = defaultdict(list)
    for t in catalog_types:
        if t.get("pattern") != "augmentation":
            local = t["qname"].split(":")[-1] if ":" in t["qname"] else t["qname"]
            object_types_by_local[local].append(t["qname"])

    augmentations = defaultdict(list)
    aug_count = 0
    for t in catalog_types:
        qname = t["qname"]
        local = qname.split(":")[-1] if ":" in qname else qname
        if not local.endswith("AugmentationType"):
            continue

        # Derive target base type name: FooAugmentationType -> FooType
        base_local = local.replace("AugmentationType", "Type")

        # Find the base type qname(s) — no namespace preference
        candidates = object_types_by_local.get(base_local, [])
        if not candidates:
            continue

        base_qname = candidates[0]

        # Get properties this augmentation type contributes
        props = type_properties.get(qname, [])
        # Exclude the AugmentationPoint self-reference
        props = [p for p in props if "AugmentationPoint" not in p]
        if not props:
            continue

        augmentations[base_qname].append({
            "augType": qname,
            "properties": sorted(props),
        })
        aug_count += 1

    # Sort augmentation entries by augType for determinism
    for base in augmentations:
        augmentations[base].sort(key=lambda a: a["augType"])

    return dict(augmentations), aug_count


def build_catalog_summary(catalog_types, ns_map):
    """Build a namespace-grouped type summary for semantic processing.

    Produces a lightweight view of all types: qname, definition, baseType,
    property names, and property count. Grouped by namespace prefix so the
    evaluator can process one namespace at a time.

    Returns dict: {prefix: {label, types: [{qname, definition, baseType, properties, propertyCount}]}}
    """
    summary = {}
    for prefix, info in sorted(ns_map.items()):
        # Extract domain label from URI
        uri = info["uri"] if isinstance(info, dict) else info
        parts = uri.rstrip("/").rsplit("/", 2)
        label = parts[-2] if len(parts) >= 2 else prefix
        summary[prefix] = {"label": label, "types": []}

    # Augmentation types are excluded — they contribute properties to base
    # types via the augmentation map, not matchable targets themselves.
    # All other patterns are included in the summary.
    SUMMARY_EXCLUDE_PATTERNS = {"augmentation"}

    for t in catalog_types:
        if t.get("pattern") in SUMMARY_EXCLUDE_PATTERNS:
            continue
        prefix = t["qname"].split(":")[0] if ":" in t["qname"] else ""
        if prefix not in summary:
            continue
        summary[prefix]["types"].append({
            "qname": t["qname"],
            "definition": t.get("definition", ""),
            "baseType": t.get("baseType"),
            "properties": t.get("properties", []),
            "propertyCount": len(t.get("properties", [])),
        })

    # Remove empty namespaces
    return {k: v for k, v in summary.items() if v["types"]}


DIRECTORY_EXCLUDE_PATTERNS = {"augmentation"}


def build_type_directory(catalog_types):
    """Build a compact one-line-per-type directory for efficient semantic matching.

    Produces a flat list of type summaries, each containing qname, base type,
    a truncated definition, property count, pattern, and up to 8 top property
    names. The directory is source-independent — built once per NIEM version
    and reused across all pipeline runs regardless of domain.

    The evaluator scans the directory in chunks, holding all source concepts
    in working memory, to identify candidates across all namespaces in a single
    pass. Only identified candidates need full type details from the catalog.

    Augmentation types are excluded (same as catalog summary — they contribute
    properties via the augmentation map, not matchable targets).

    Returns list of dicts, sorted by qname:
        [{qname, definition, baseType, pattern, propertyCount, topProperties}]
    """
    directory = []
    for t in catalog_types:
        if t.get("pattern") in DIRECTORY_EXCLUDE_PATTERNS:
            continue
        props = t.get("properties", [])
        directory.append({
            "qname": t["qname"],
            "definition": (t.get("definition") or "")[:200],
            "baseType": t.get("baseType"),
            "pattern": t.get("pattern", "object"),
            "propertyCount": len(props),
            "topProperties": props[:8],
        })
    directory.sort(key=lambda e: e["qname"])
    return directory


def format_type_directory(directory):
    """Format the type directory as a compact, human-scannable text file.

    Each line contains: qname | baseType | pattern | propCount | definition | topProperties

    Fields are pipe-delimited for easy parsing. Definitions are truncated to
    120 chars. Top properties are comma-separated (up to 8).

    Returns the formatted text as a string (including a header comment).
    """
    lines = []
    lines.append("# NIEM Type Directory — one line per type for efficient semantic matching")
    lines.append("# Format: qname | baseType | pattern | propCount | definition | topProperties")
    lines.append(f"# Total: {len(directory)} types")
    lines.append("#")

    for entry in directory:
        qname = entry["qname"]
        base = entry.get("baseType") or "-"
        pattern = entry.get("pattern", "")
        prop_count = entry.get("propertyCount", 0)
        definition = (entry.get("definition") or "")[:120].replace("|", "/").replace("\n", " ")
        top_props = ", ".join(entry.get("topProperties", [])) or "-"

        lines.append(f"{qname} | {base} | {pattern} | {prop_count} | {definition} | {top_props}")

    return "\n".join(lines) + "\n"


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    # Parse arguments
    version = None
    output_path = None
    include_github_csv = True

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--version" and i + 1 < len(args):
            version = args[i + 1]
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            output_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--no-github-csv":
            include_github_csv = False
            i += 1
        elif args[i] == "--github-ref" and i + 1 < len(args):
            GITHUB_TAG_MAP[version or "6.0"] = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}")
            sys.exit(1)

    if not version:
        print("Error: --version is required (e.g. --version 6.0)")
        sys.exit(1)

    if output_path is None:
        from ontology_mapper.run_dir_utils import resolve_specs_dir
        output_path = resolve_specs_dir() / f"niem_reference_catalog_{version}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating NIEM reference catalog for version {version}")
    print(f"  API: {API_BASE}/{version}")
    print(f"  GitHub CSVs: {'enabled' if include_github_csv else 'disabled'}")
    print(f"  Output: {output_path}")

    # Step 1: Fetch namespaces
    print("\n  Step 1: Fetching namespaces...")
    ns_url = f"{API_BASE}/{version}/namespaces"
    namespaces_raw = api_get(ns_url)

    # The namespaces endpoint may return a list or paginated object
    if isinstance(namespaces_raw, dict) and "content" in namespaces_raw:
        ns_list = namespaces_raw["content"]
    elif isinstance(namespaces_raw, list):
        ns_list = namespaces_raw
    else:
        ns_list = []

    # Filter to core + domain namespaces, excluding expert-flagged ones
    target_namespaces = [
        ns for ns in ns_list
        if ns.get("category") in INCLUDE_CATEGORIES
        and ns.get("prefix", "") not in EXCLUDE_NAMESPACES
    ]
    # Also include namespaces needed for INCLUDE_EXTRA_TYPES
    extra_prefixes = {t.split(":")[0] for t in INCLUDE_EXTRA_TYPES if ":" in t}
    extra_namespaces = [
        ns for ns in ns_list
        if ns.get("prefix", "") in extra_prefixes
        and ns.get("prefix", "") not in {n.get("prefix", "") for n in target_namespaces}
    ]
    ns_map = {}
    for ns in target_namespaces + extra_namespaces:
        prefix = ns.get("prefix", "")
        ns_map[prefix] = {
            "prefix": prefix,
            "name": ns.get("name", ""),
            "uri": ns.get("uri", ""),
            "category": ns.get("category", ""),
        }
    print(f"    {len(ns_map)} namespaces: "
          f"{', '.join(sorted(ns_map.keys()))}")

    # Step 2: Fetch types from each namespace
    print(f"\n  Step 2: Fetching types (patterns: {', '.join(sorted(INCLUDE_PATTERNS))})...")
    all_types = []
    pattern_counts = defaultdict(int)
    for prefix in sorted(ns_map.keys()):
        is_extra_ns = prefix in extra_prefixes
        url_template = (
            f"{API_BASE}/{version}/namespaces/{prefix}/types"
            "?page={page}&size={size}"
        )
        types = fetch_paginated(url_template, version)
        if is_extra_ns:
            # For extra namespaces (e.g., structures), only include
            # specifically listed types, not all types in the namespace
            included = [
                t for t in types
                if t.get("qname") in INCLUDE_EXTRA_TYPES
                and not t.get("isDeprecated", False)
            ]
        else:
            included = [
                t for t in types
                if t.get("pattern") in INCLUDE_PATTERNS
                and not t.get("isDeprecated", False)
            ]
        for t in included:
            pattern_counts[t.get("pattern", "unknown")] += 1
        all_types.extend(included)
        counts_str = ", ".join(
            f"{sum(1 for t in included if t.get('pattern') == p)} {p}"
            for p in sorted({t.get("pattern", "unknown") for t in included})
        )
        print(f"    {prefix}: {len(types)} total, {len(included)} included"
              + (f" ({counts_str})" if counts_str else ""))

    counts_detail = ", ".join(
        f"{count} {pat}" for pat, count in sorted(pattern_counts.items())
    )
    print(f"    Total included types: {len(all_types)} ({counts_detail})")

    # Step 3: Fetch subproperties (all at once — single non-paginated endpoint)
    print("\n  Step 3: Fetching subproperties (this may take a moment)...")
    sp_url = f"{API_BASE}/{version}/subproperties"
    subprops_raw = api_get(sp_url)

    if isinstance(subprops_raw, dict) and "content" in subprops_raw:
        subprops = subprops_raw["content"]
    elif isinstance(subprops_raw, list):
        subprops = subprops_raw
    else:
        subprops = []
    print(f"    {len(subprops)} subproperty memberships")

    # Group subproperties by parent type qname
    type_properties = defaultdict(list)
    for sp in subprops:
        parent_type = (sp.get("type") or {}).get("qname", "")
        prop_info = sp.get("property") or {}
        prop_name = prop_info.get("name", "")
        if parent_type and prop_name:
            type_properties[parent_type].append(prop_name)

    # Sort property lists for determinism
    for qname in type_properties:
        type_properties[qname] = sorted(set(type_properties[qname]))

    # Step 4: Fetch GitHub CSV enrichment data
    github_facets = {}
    github_types = {}
    github_properties = {}
    github_cardinalities = {}
    if include_github_csv:
        print("\n  Step 4: Fetching GitHub CSV data...")
        tag = GITHUB_TAG_MAP.get(version, version)
        print(f"    Tag: {tag}")

        facet_rows = fetch_github_csv(version, "Facet.csv")
        if facet_rows is not None:
            github_facets = parse_facets_csv(facet_rows)
            total_facets = sum(len(v) for v in github_facets.values())
            print(f"    Facet.csv: {len(facet_rows)} rows -> {len(github_facets)} types with {total_facets} enumeration values")
        else:
            print("    Facet.csv: skipped (fetch failed)")

        type_rows = fetch_github_csv(version, "Type.csv")
        if type_rows is not None:
            github_types = parse_types_csv(type_rows)
            print(f"    Type.csv: {len(type_rows)} rows -> {len(github_types)} type records")
        else:
            print("    Type.csv: skipped (fetch failed)")

        prop_rows = fetch_github_csv(version, "Property.csv")
        if prop_rows is not None:
            github_properties = parse_property_csv(prop_rows)
            total_props = sum(len(v) for v in github_properties.values())
            print(f"    Property.csv: {len(prop_rows)} rows -> {len(github_properties)} unique names, {total_props} definitions")
        else:
            print("    Property.csv: skipped (fetch failed)")

        tcp_rows = fetch_github_csv(version, "TypeContainsProperty.csv")
        if tcp_rows is not None:
            github_cardinalities = parse_type_contains_property_csv(tcp_rows)
            print(f"    TypeContainsProperty.csv: {len(tcp_rows)} rows -> {len(github_cardinalities)} types with cardinalities")
        else:
            print("    TypeContainsProperty.csv: skipped (fetch failed)")
    else:
        print("\n  Step 4: Skipping GitHub CSV data (--no-github-csv)")

    # Step 5: Build catalog entries
    print("\n  Step 5: Building catalog...")
    catalog_types = []

    facet_enriched = 0
    type_enriched = 0
    cardinality_enriched = 0
    prop_def_enriched = 0

    for t in all_types:
        qname = t.get("qname", "")
        definition = t.get("definition", "")
        base_info = t.get("base") or {}
        base_qname = base_info.get("qname")

        properties = type_properties.get(qname, [])

        pattern = t.get("pattern", "object")

        entry = {
            "qname": qname,
            "definition": definition,
            "baseType": base_qname,
            "pattern": pattern,
            "properties": properties,
            "contentStyle": "",
            "isAugmentation": False,
            "isAdapter": False,
            "isMetadata": False,
            "propertyCardinalities": {},
            "propertyDefinitions": {},
            "inheritanceChain": [],
        }

        # Merge GitHub CSV data (qnames match CSV format directly)
        qualified = qname

        if qualified in github_facets:
            entry["facets"] = github_facets[qualified]
            facet_enriched += 1

        if qualified in github_types:
            gt = github_types[qualified]
            # Always prefer CSV parentType (more complete than API)
            if gt["parentType"]:
                entry["baseType"] = gt["parentType"]
            # Fallback: keep API base if CSV has no parent
            # (entry["baseType"] already set from API above)
            if gt["contentStyle"]:
                entry["contentStyle"] = gt["contentStyle"]
            entry["isAugmentation"] = gt["isAugmentation"]
            entry["isAdapter"] = gt["isAdapter"]
            entry["isMetadata"] = gt["isMetadata"]
            type_enriched += 1

        if qualified in github_cardinalities:
            entry["propertyCardinalities"] = github_cardinalities[qualified]
            cardinality_enriched += 1

        # Enrich properties with definitions and types from Property.csv
        if github_properties and properties:
            type_prefix = qname.split(":")[0] if ":" in qname else ""
            prop_defs = {}
            for prop_name in properties:
                prop_def = resolve_property_definition(
                    prop_name, type_prefix, github_properties
                )
                if prop_def:
                    prop_defs[prop_name] = prop_def
            if prop_defs:
                entry["propertyDefinitions"] = prop_defs
                prop_def_enriched += 1

        catalog_types.append(entry)

    # Sort by qname for deterministic output
    catalog_types.sort(key=lambda e: e["qname"])

    print(f"    {len(catalog_types)} types cataloged")
    print(f"    Types with properties: "
          f"{sum(1 for t in catalog_types if t['properties'])}")
    if include_github_csv:
        print(f"    GitHub CSV enrichment: {facet_enriched} with facets, "
              f"{type_enriched} with type metadata, "
              f"{cardinality_enriched} with cardinalities, "
              f"{prop_def_enriched} with property definitions")

    # Step 5b: Build inheritance chains
    if github_types:
        print("\n  Step 5b: Building inheritance chains...")
        chain_count = 0
        for entry in catalog_types:
            chain = build_inheritance_chain(entry["qname"], github_types)
            entry["inheritanceChain"] = chain or []
            if chain:
                chain_count += 1
        base_count = sum(1 for t in catalog_types if t.get("baseType"))
        print(f"    {base_count}/{len(catalog_types)} types with baseType")
        print(f"    {chain_count}/{len(catalog_types)} types with inheritanceChain")

    # Step 5b2: Build augmentation map
    print("\n  Step 5b2: Building augmentation map...")
    augmentation_map, aug_mapped_count = build_augmentation_map(
        catalog_types, type_properties
    )
    total_aug_props = sum(
        len(p) for augs in augmentation_map.values()
        for a in augs for p in [a["properties"]]
    )
    print(f"    {aug_mapped_count} augmentation types mapped to "
          f"{len(augmentation_map)} base types")
    print(f"    {total_aug_props} total augmented properties")

    # Note: reachableProperties are computed at runtime for just the
    # types needed (too large to pre-compute for all — avg 112 per type
    # at depth 2).

    # Step 5c: Build property-centric index
    property_index = {}
    if github_properties:
        print("\n  Step 5c: Building property-centric index...")
        catalog_ns = set(ns_map.keys())
        property_index = build_property_index(
            catalog_types, github_properties, github_cardinalities,
            namespace_filter=catalog_ns
        )
        total_indexed = sum(ns["propertyCount"] for ns in property_index.values())
        print(f"    {len(property_index)} namespaces, {total_indexed} properties indexed")

    # Step 5d: Build catalog summary for semantic processing
    print("\n  Step 5d: Building catalog summary...")
    catalog_summary = build_catalog_summary(catalog_types, ns_map)
    summary_type_count = sum(
        len(ns_data["types"]) for ns_data in catalog_summary.values()
    )
    print(f"    {len(catalog_summary)} namespaces, {summary_type_count} types summarized")

    # Write catalog summary
    summary_path = output_path.parent / f"niem_catalog_summary_{version}.json"
    summary_doc = {
        "version": version,
        "description": (
            f"NIEM {version} type summary for semantic processing. "
            f"Namespace-grouped types with definitions and property lists. "
            f"Generated alongside the reference catalog."
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "namespaces": len(catalog_summary),
            "totalTypes": summary_type_count,
        },
        "namespaces": catalog_summary,
    }
    summary_path.write_text(
        json.dumps(summary_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary_kb = summary_path.stat().st_size / 1024
    print(f"    Written: {summary_path} ({summary_kb:.0f} KB)")

    # Step 5e: Build type directory for efficient semantic scanning
    print("\n  Step 5e: Building type directory...")
    directory = build_type_directory(catalog_types)
    directory_text = format_type_directory(directory)
    directory_path = output_path.parent / f"niem_type_directory_{version}.txt"
    directory_path.write_text(directory_text, encoding="utf-8")
    directory_kb = directory_path.stat().st_size / 1024
    print(f"    {len(directory)} types in directory")
    print(f"    Written: {directory_path} ({directory_kb:.0f} KB)")

    # Step 6: Write catalog
    print(f"\n  Step 6: Writing {output_path}...")
    sources = ["NIEM API"]
    if include_github_csv and (github_facets or github_types or github_cardinalities):
        tag = GITHUB_TAG_MAP.get(version, version)
        sources.append(f"GitHub CSVs ({tag})")

    catalog = {
        "version": version,
        "description": (
            f"NIEM {version} reference catalog for semantic ontology alignment. "
            f"Generated from {' + '.join(sources)} on "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
            f"Includes type hierarchy, augmentation map, and namespace-grouped "
            f"property index for LLM semantic matching. "
            f"Excludes namespaces: {', '.join(sorted(EXCLUDE_NAMESPACES))}. "
            f"Regenerate with: om-generate-catalog "
            f"--version {version}"
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "actions": {
            "reuse": "The source concept maps directly to an existing NIEM type. Use the target type as-is.",
            "extend": "The source concept requires a new extension type that inherits from a NIEM base type via rdfs:subClassOf.",
            "augment": "The source concept contributes properties to an existing NIEM type via an augmentation type, without subclassing.",
        },
        "defaultBaseType": "structures:ObjectType",
        "typePatterns": {
            "object": "Container types with properties. The primary matching targets for domain concepts.",
            "association": "Relationship types with role properties. Match when the source concept represents a relationship between entities.",
            "complex_value": "Structured value types. Match when the source concept is a structured value, not a standalone entity.",
            "simple_value": "Code tables and primitive wrappers. Match when the source concept is a constrained value set.",
            "simple_list": "Space-separated list types. Rarely direct matching targets.",
            "simple_union": "Union types. Rarely direct matching targets.",
            "metadata": "Metadata containers. Match when the source concept carries metadata about other data.",
            "augmentation": "Augmentation types. Not matchable targets — they contribute properties to base types via the augmentation map.",
        },
        "stats": {
            "namespaces": len(ns_map),
            "totalTypes": len(catalog_types),
            "typesWithProperties": sum(1 for t in catalog_types if t["properties"]),
            "totalPropertyMemberships": sum(
                len(t["properties"]) for t in catalog_types
            ),
            "typesWithFacets": facet_enriched,
            "typesWithCardinalities": cardinality_enriched,
            "typesWithPropertyDefinitions": prop_def_enriched,
            "totalPropertyDefinitions": sum(
                len(t.get("propertyDefinitions", {})) for t in catalog_types
            ),
            "typesWithBaseType": sum(1 for t in catalog_types if t.get("baseType")),
            "typesWithInheritanceChain": sum(
                1 for t in catalog_types if t.get("inheritanceChain")
            ),
            "augmentationTypes": aug_mapped_count,
            "augmentedBaseTypes": len(augmentation_map),
            "augmentedProperties": total_aug_props,
            "propertyIndexNamespaces": len(property_index),
            "propertyIndexTotal": sum(
                ns["propertyCount"] for ns in property_index.values()
            ),
        },
        "namespaces": {
            prefix: info["uri"] for prefix, info in sorted(ns_map.items())
        },
        "propertyIndex": property_index,
        "augmentationMap": augmentation_map,
        "types": catalog_types,
    }

    output_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Summary
    size_kb = output_path.stat().st_size / 1024
    print(f"\n  Catalog generated: {output_path} ({size_kb:.0f} KB)")
    print(f"  {catalog['stats']['namespaces']} namespaces, "
          f"{catalog['stats']['totalTypes']} types, "
          f"{catalog['stats']['totalPropertyMemberships']} property memberships")


if __name__ == "__main__":
    main()
