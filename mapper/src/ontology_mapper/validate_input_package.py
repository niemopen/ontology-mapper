#!/usr/bin/env python3
"""Validate that an input domain package has the minimum viable data for the pipeline.

Runs before Stage 1 to fail fast with clear messages rather than producing
cryptic errors three stages later. Does NOT enforce directory structure,
naming conventions, or specific serialization formats — only checks that
the minimum semantic content exists.

Checks:
  IV-010  Directory exists and is non-empty
  IV-020  Contains at least one parseable RDF/OWL file
  IV-030  Contains at least one class definition (owl:Class or rdfs:Class)
  IV-040  Contains at least one property definition (owl:ObjectProperty,
          owl:DatatypeProperty, or rdf:Property)

Usage:
    om-validate-input <path-to-domain-package>
"""

import sys
from pathlib import Path

from rdflib import Graph, RDF, OWL, RDFS, BNode


# Supported RDF file extensions and their rdflib format names
RDF_FORMATS = {
    ".ttl": "turtle",
    ".owl": "xml",
    ".rdf": "xml",
    ".n3": "n3",
    ".nt": "nt",
    ".jsonld": "json-ld",
}


def find_rdf_files(pkg_dir):
    """Find all files with recognized RDF extensions in the package directory."""
    rdf_files = []
    for path in sorted(pkg_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in RDF_FORMATS:
            rdf_files.append(path)
    return rdf_files


def try_parse(path):
    """Attempt to parse an RDF file, returning (graph, None) or (None, error)."""
    fmt = RDF_FORMATS.get(path.suffix.lower())
    if not fmt:
        return None, f"Unrecognized format: {path.suffix}"
    g = Graph()
    try:
        g.parse(str(path), format=fmt)
        return g, None
    except Exception as e:
        return None, str(e)


def validate_input_package(pkg_path):
    """Validate a domain package directory for minimum pipeline viability.

    Args:
        pkg_path: Path to the domain package directory.

    Returns:
        List of finding dicts: [{code, severity, message, detail}]
        severity is "error" for blockers, "warning" for concerns.
    """
    findings = []
    pkg = Path(pkg_path)

    # --- IV-010: Directory exists and is non-empty ---
    if not pkg.exists():
        findings.append({
            "code": "IV-010",
            "severity": "error",
            "message": "Package directory does not exist",
            "detail": str(pkg),
        })
        return findings  # Can't check further

    if not pkg.is_dir():
        findings.append({
            "code": "IV-010",
            "severity": "error",
            "message": "Path is not a directory",
            "detail": str(pkg),
        })
        return findings

    all_files = [f for f in pkg.rglob("*") if f.is_file()]
    if not all_files:
        findings.append({
            "code": "IV-010",
            "severity": "error",
            "message": "Package directory is empty",
            "detail": str(pkg),
        })
        return findings

    # --- IV-020: Contains at least one parseable RDF/OWL file ---
    rdf_files = find_rdf_files(pkg)
    if not rdf_files:
        findings.append({
            "code": "IV-020",
            "severity": "error",
            "message": "No RDF/OWL files found",
            "detail": (
                f"Found {len(all_files)} file(s) but none with recognized RDF "
                f"extensions ({', '.join(sorted(RDF_FORMATS.keys()))})"
            ),
        })
        return findings

    # Try to parse each RDF file, collect those that succeed
    parsed_graphs = []
    parse_errors = []
    for path in rdf_files:
        g, err = try_parse(path)
        if g is not None and len(g) > 0:
            parsed_graphs.append((path, g))
        elif err:
            parse_errors.append((path, err))

    if not parsed_graphs:
        detail = f"Found {len(rdf_files)} RDF file(s) but none could be parsed"
        if parse_errors:
            detail += ":\n" + "\n".join(
                f"  {p.name}: {e[:120]}" for p, e in parse_errors[:5]
            )
        findings.append({
            "code": "IV-020",
            "severity": "error",
            "message": "No parseable RDF/OWL files",
            "detail": detail,
        })
        return findings

    # Report parse errors as warnings (some files failing is OK if others succeed)
    for path, err in parse_errors:
        findings.append({
            "code": "IV-020",
            "severity": "warning",
            "message": f"RDF file could not be parsed: {path.name}",
            "detail": err[:200],
        })

    # --- IV-030: Contains at least one class definition ---
    class_count = 0
    for _path, g in parsed_graphs:
        for cls in g.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, BNode):
                class_count += 1
        for cls in g.subjects(RDF.type, RDFS.Class):
            if not isinstance(cls, BNode):
                class_count += 1

    if class_count == 0:
        findings.append({
            "code": "IV-030",
            "severity": "error",
            "message": "No class definitions found",
            "detail": (
                f"Parsed {len(parsed_graphs)} RDF file(s) but found no "
                f"owl:Class or rdfs:Class declarations. The pipeline needs "
                f"at least one class to extract and align."
            ),
        })

    # --- IV-040: Contains at least one property definition ---
    prop_count = 0
    prop_types = [OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property]
    for _path, g in parsed_graphs:
        for ptype in prop_types:
            for prop in g.subjects(RDF.type, ptype):
                if not isinstance(prop, BNode):
                    prop_count += 1

    if prop_count == 0:
        findings.append({
            "code": "IV-040",
            "severity": "error",
            "message": "No property definitions found",
            "detail": (
                f"Parsed {len(parsed_graphs)} RDF file(s) but found no "
                f"owl:ObjectProperty, owl:DatatypeProperty, or rdf:Property "
                f"declarations. A domain with classes but zero properties is "
                f"almost certainly incomplete."
            ),
        })

    return findings


def format_findings(findings):
    """Format validation findings for console output."""
    if not findings:
        return "\n  Input package validation: all checks passed"

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]

    lines = ["\n  Input Package Validation:"]
    for f in findings:
        icon = "X" if f["severity"] == "error" else "!"
        lines.append(f"    [{icon}] {f['code']}: {f['message']}")
        if f.get("detail"):
            for detail_line in f["detail"].split("\n"):
                lines.append(f"        {detail_line}")

    lines.append(f"    ({len(errors)} error(s), {len(warnings)} warning(s))")

    if errors:
        lines.append("")
        lines.append("  Pipeline cannot proceed — fix the errors above.")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validate a source domain input package")
    parser.add_argument("--package", required=True, help="Path to domain package directory")
    args = parser.parse_args()

    findings = validate_input_package(args.package)
    print(format_findings(findings))

    errors = [f for f in findings if f["severity"] == "error"]
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
