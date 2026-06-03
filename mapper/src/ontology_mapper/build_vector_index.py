#!/usr/bin/env python3
"""Build vector indexes for ontology-agnostic semantic similarity matching.

Creates FAISS indexes from any ontology via adapters.  Each ontology gets
its own pair of indexes (types + properties) stored under
specs/vector/indexes/{ontology_name}/.

Adapters:
  catalog  Any reference catalog (NIEM, OWL, CMF — single generic adapter)
  source   Pipeline concept inventory from a run directory

Usage:
    om-build-vector-index --adapter catalog --ontology niem --version 6.0
    om-build-vector-index --adapter catalog --ontology sali-folio --version 2.0
    om-build-vector-index --adapter catalog --ontology nods --version 1.0
    om-build-vector-index --adapter catalog --ontology niem --version 6.0 --rebuild
    om-build-vector-index --adapter source --ontology redvale-dbpi --run-dir {path}
    om-build-vector-index --list
    om-build-vector-index --ontology niem-6.0 --delete

Index naming: catalog indexes are stored as {ontology}-{version} (e.g., niem-6.0).
Source indexes use the ontology name as-is.
"""

import sys


def build_catalog(ontology_name: str, catalog_name: str, version: str):
    """Build type and property indexes from any reference catalog."""
    from ontology_mapper.adapters.catalog_adapter import extract_properties, extract_types
    from ontology_mapper.vector_index import build_index, save_index

    print(f"Extracting {catalog_name} v{version} types...")
    type_entries = extract_types(catalog_name, version)
    print(f"  {len(type_entries)} types extracted")

    print(f"Extracting {catalog_name} v{version} properties...")
    prop_entries = extract_properties(catalog_name, version)
    print(f"  {len(prop_entries)} properties extracted")

    if type_entries:
        print(f"\nBuilding type index ({len(type_entries)} entries)...")
        type_index, type_meta = build_index(type_entries)
        save_index(ontology_name, "types", type_index, type_meta)
        print(f"  Saved: types.faiss + types.meta.json")

    if prop_entries:
        print(f"Building property index ({len(prop_entries)} entries)...")
        prop_index, prop_meta = build_index(prop_entries)
        save_index(ontology_name, "properties", prop_index, prop_meta)
        print(f"  Saved: properties.faiss + properties.meta.json")

    from ontology_mapper.vector_index import index_dir_for
    print(f"\nIndexes saved to: {index_dir_for(ontology_name)}")


def build_source(ontology_name: str, run_dir: str):
    """Build type and property indexes from a source concept inventory."""
    from ontology_mapper.adapters.source_adapter import extract_properties, extract_types
    from ontology_mapper.vector_index import build_index, save_index

    print(f"Extracting source types from {run_dir}...")
    type_entries = extract_types(run_dir)
    print(f"  {len(type_entries)} types extracted")

    print(f"Extracting source properties from {run_dir}...")
    prop_entries = extract_properties(run_dir)
    print(f"  {len(prop_entries)} properties extracted")

    if type_entries:
        print(f"\nBuilding type index ({len(type_entries)} entries)...")
        type_index, type_meta = build_index(type_entries)
        save_index(ontology_name, "types", type_index, type_meta)
        print(f"  Saved: types.faiss + types.meta.json")

    if prop_entries:
        print(f"Building property index ({len(prop_entries)} entries)...")
        prop_index, prop_meta = build_index(prop_entries)
        save_index(ontology_name, "properties", prop_index, prop_meta)
        print(f"  Saved: properties.faiss + properties.meta.json")

    from ontology_mapper.vector_index import index_dir_for
    print(f"\nIndexes saved to: {index_dir_for(ontology_name)}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Build vector indexes for semantic similarity matching"
    )
    parser.add_argument("--ontology", help="Ontology name (e.g., niem, sali-folio, nods)")
    parser.add_argument("--adapter", choices=["catalog", "source"],
                        help="Adapter: catalog (any reference catalog) or source (concept inventory)")
    parser.add_argument("--version", default=None,
                        help="Catalog version (required for catalog adapter, e.g., 6.0, 2.0, 1.0)")
    parser.add_argument("--run-dir", default=None,
                        help="Run directory (required for source adapter)")
    parser.add_argument("--rebuild", action="store_true",
                        help="Force rebuild even if indexes exist")
    parser.add_argument("--delete", action="store_true",
                        help="Delete indexes for the specified ontology")
    parser.add_argument("--list", action="store_true", dest="list_indexes",
                        help="List all existing indexes")
    args = parser.parse_args()

    if args.list_indexes:
        from ontology_mapper.vector_index import list_indexes
        indexes = list_indexes()
        if not indexes:
            print("No indexes found.")
            return
        for entry in indexes:
            print(f"\n{entry['ontology']}:")
            for idx in entry["indexes"]:
                print(f"  {idx['kind']}: {idx['vectors']} vectors")
        return

    # Resolve the index directory name.
    # Catalog indexes include version: {ontology}-{version} (e.g., niem-6.0).
    # Source indexes use the ontology name as-is.
    # For --delete and --list, the user provides the full index name directly.
    if args.adapter == "catalog" and args.version:
        index_name = f"{args.ontology}-{args.version}"
    else:
        index_name = args.ontology  # source adapter, or --delete/--list

    if args.delete:
        if not args.ontology:
            print("Error: --ontology required with --delete", file=sys.stderr)
            sys.exit(1)
        from ontology_mapper.vector_index import delete_index
        if delete_index(args.ontology):
            print(f"Deleted indexes for: {args.ontology}")
        else:
            print(f"No indexes found for: {args.ontology}")
        return

    if not args.ontology or not args.adapter:
        parser.print_help()
        sys.exit(1)

    # Check if indexes already exist
    if not args.rebuild:
        from ontology_mapper.vector_index import index_exists
        if index_exists(index_name, "types") or index_exists(index_name, "properties"):
            print(f"Indexes already exist for '{index_name}'. Use --rebuild to overwrite.")
            return

    if args.adapter == "catalog":
        if not args.version:
            print("Error: --version required for catalog adapter", file=sys.stderr)
            sys.exit(1)
        build_catalog(index_name, args.ontology, args.version)

    elif args.adapter == "source":
        if not args.run_dir:
            from ontology_mapper.run_dir_utils import resolve_run_dir
            try:
                run_dir = str(resolve_run_dir(org=args.ontology))
            except FileNotFoundError:
                print("Error: --run-dir required for source adapter", file=sys.stderr)
                sys.exit(1)
        else:
            run_dir = args.run_dir
        build_source(index_name, run_dir)


if __name__ == "__main__":
    main()
