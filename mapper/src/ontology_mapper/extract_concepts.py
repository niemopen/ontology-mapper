#!/usr/bin/env python3
"""Stage 2: Extract — build concept inventory from internal ontology package.

Reads the package manifest (auto-generated if absent) to determine
namespaces, file locations, and prefix mappings. No domain-specific
hardcoding — works with any OWL/SHACL/SKOS domain package.
"""

import json
import sys
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS, OWL, SKOS, SH, URIRef, BNode
from datetime import datetime, timezone

from ontology_mapper.run_dir_utils import resolve_run_dir, load_state


# ─── Manifest Loading ────────────────────────────────────────────────────

def load_or_build_manifest(pkg):
    """Load package-manifest.json, auto-generating it if absent."""
    manifest_path = pkg / "package-manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    # Auto-generate
    from ontology_mapper.build_package_manifest import build_manifest
    manifest, warnings, needs_input = build_manifest(str(pkg))
    if manifest is None:
        raise RuntimeError(f"Cannot build manifest for {pkg}: {'; '.join(warnings)}")

    # Save for future runs
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  Auto-generated package manifest: {manifest_path}")
    if warnings:
        for w in warnings:
            print(f"    ! {w}")

    return manifest


def build_ns_map(manifest):
    """Build namespace URI → prefix mapping from manifest."""
    ns_map = {}
    primary = manifest["namespaces"]["primary"]
    if primary:
        ns_map[primary["uri"]] = primary["prefix"] + ":"
    for aug in manifest["namespaces"].get("augmenting", []):
        ns_map[aug["uri"]] = aug["prefix"] + ":"
    return ns_map


def make_to_qname(ns_map):
    """Create a qname resolver function from a namespace map."""
    def to_qname(iri):
        s = str(iri)
        for ns, prefix in ns_map.items():
            if s.startswith(ns):
                return prefix + s[len(ns):]
        return s
    return to_qname


# ─── Input Resolution ────────────────────────────────────────────────────

def load_inputs(pkg_arg=None, run_dir_arg=None):
    """Resolve package path and output directory from mapper state or CLI arguments."""
    if run_dir_arg:
        run_dir = resolve_run_dir(run_dir_arg)
        state = load_state(run_dir)
        pkg = Path(pkg_arg) if pkg_arg else Path(state["inputs"]["input_package_path"])
    elif pkg_arg:
        # Package given but no run dir
        pkg = Path(pkg_arg)
        run_dir = None
    else:
        raise ValueError("Either run_dir_arg or pkg_arg is required")
    return pkg, run_dir


# ─── Graph Loading ────────────────────────────────────────────────────────

def load_ontology_graph(pkg, manifest):
    """Load ontology files into a single graph, skipping aggregate files."""
    g = Graph()
    aggregate_files = set(manifest["files"].get("aggregate", []))
    for rel_path in manifest["files"]["ontology"]:
        full = pkg / rel_path
        # Skip aggregate/combined files that just import others
        if rel_path in aggregate_files:
            continue
        g.parse(str(full), format="turtle")
    return g


def load_shapes_graph(pkg, manifest):
    """Load SHACL shape files into a graph."""
    g = Graph()
    for rel_path in manifest["files"].get("shapes", []):
        g.parse(str(pkg / rel_path), format="turtle")
    return g


def load_vocab_graph(pkg, manifest):
    """Load vocabulary files into a graph."""
    g = Graph()
    for rel_path in manifest["files"].get("vocab", []):
        g.parse(str(pkg / rel_path), format="turtle")
    return g


def load_seed_graph(pkg, manifest):
    """Load seed data files into a graph."""
    g = Graph()
    for rel_path in manifest["files"].get("seedData", []):
        g.parse(str(pkg / rel_path), format="turtle")
    return g


# ─── Extraction ───────────────────────────────────────────────────────────

def extract_classes(g, to_qname):
    classes = []
    for cls in g.subjects(RDF.type, OWL.Class):
        if isinstance(cls, BNode):
            continue
        label = str(g.value(cls, RDFS.label) or "")
        comment = str(g.value(cls, RDFS.comment) or "")
        subclass_of = []
        for sc in g.objects(cls, RDFS.subClassOf):
            if isinstance(sc, URIRef):
                subclass_of.append(to_qname(sc))
        classes.append({
            "iri": str(cls),
            "qname": to_qname(cls),
            "label": label,
            "comment": comment,
            "subClassOf": subclass_of,
        })
    return sorted(classes, key=lambda c: c["qname"])


def extract_object_properties(g, to_qname):
    props = []
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(prop, BNode):
            continue
        label = str(g.value(prop, RDFS.label) or "")
        comment = str(g.value(prop, RDFS.comment) or "")
        domains = [to_qname(d) for d in g.objects(prop, RDFS.domain) if isinstance(d, URIRef)]
        ranges = [to_qname(r) for r in g.objects(prop, RDFS.range) if isinstance(r, URIRef)]
        props.append({
            "iri": str(prop),
            "qname": to_qname(prop),
            "label": label,
            "comment": comment,
            "domain": domains,
            "range": ranges,
        })
    return sorted(props, key=lambda p: p["qname"])


def extract_datatype_properties(g, to_qname):
    props = []
    for prop in g.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(prop, BNode):
            continue
        label = str(g.value(prop, RDFS.label) or "")
        comment = str(g.value(prop, RDFS.comment) or "")
        domains = [to_qname(d) for d in g.objects(prop, RDFS.domain) if isinstance(d, URIRef)]
        ranges = [str(r) for r in g.objects(prop, RDFS.range)]
        props.append({
            "iri": str(prop),
            "qname": to_qname(prop),
            "label": label,
            "comment": comment,
            "domain": domains,
            "range": ranges,
        })
    return sorted(props, key=lambda p: p["qname"])


def extract_codelist_schemes(vocab_g, to_qname):
    schemes = []
    for scheme in vocab_g.subjects(RDF.type, SKOS.ConceptScheme):
        label = str(vocab_g.value(scheme, RDFS.label) or "")
        concepts = []
        for concept in vocab_g.subjects(SKOS.inScheme, scheme):
            clabel = str(vocab_g.value(concept, SKOS.prefLabel) or "")
            concepts.append({"iri": str(concept), "label": clabel})
        schemes.append({
            "iri": str(scheme),
            "label": label,
            "conceptCount": len(concepts),
            "concepts": sorted(concepts, key=lambda c: c["label"]),
        })
    return sorted(schemes, key=lambda s: s["label"])


def extract_workflow_models(g, primary_ns_uri, to_qname):
    """Extract workflow models using the primary namespace for predicates.

    Looks for instances of {primary}WorkflowModel with workflow-related
    predicates like hasWorkflowState, hasWorkflowTransition, etc.
    """
    ns = Namespace(primary_ns_uri)
    wf_models = []
    for wf in g.subjects(RDF.type, ns.WorkflowModel):
        label = str(g.value(wf, RDFS.label) or "")
        applies_to = to_qname(g.value(wf, ns.appliesToClass) or "")
        states = []
        for st in g.objects(wf, ns.hasWorkflowState):
            slabel = str(g.value(st, RDFS.label) or "")
            states.append({"iri": str(st), "label": slabel})
        transitions = []
        for tr in g.objects(wf, ns.hasWorkflowTransition):
            tlabel = str(g.value(tr, RDFS.label) or "")
            from_st = str(g.value(tr, ns.fromState) or "")
            to_st = str(g.value(tr, ns.toState) or "")
            trigger = str(g.value(tr, ns.transitionTrigger) or "")
            transitions.append({
                "iri": str(tr),
                "label": tlabel,
                "fromState": from_st,
                "toState": to_st,
                "trigger": trigger,
            })
        wf_models.append({
            "iri": str(wf),
            "label": label,
            "appliesToClass": applies_to,
            "stateCount": len(states),
            "transitionCount": len(transitions),
            "states": sorted(states, key=lambda s: s["label"]),
            "transitions": transitions,
        })
    return sorted(wf_models, key=lambda w: w["label"])


def extract_shacl_shapes(shapes_g, to_qname):
    shapes = []
    for shape in shapes_g.subjects(RDF.type, SH.NodeShape):
        target_class = to_qname(shapes_g.value(shape, SH.targetClass) or "")
        props = []
        for prop_shape in shapes_g.objects(shape, SH.property):
            path = to_qname(shapes_g.value(prop_shape, SH.path) or "")
            min_count = shapes_g.value(prop_shape, SH.minCount)
            max_count = shapes_g.value(prop_shape, SH.maxCount)
            datatype = str(shapes_g.value(prop_shape, SH.datatype) or "")
            cls_val = to_qname(shapes_g.value(prop_shape, getattr(SH, "class")) or "")
            props.append({
                "path": path,
                "minCount": int(min_count) if min_count else None,
                "maxCount": int(max_count) if max_count else None,
                "datatype": datatype if datatype else None,
                "class": cls_val if cls_val else None,
            })
        shapes.append({
            "iri": str(shape),
            "targetClass": target_class,
            "propertyCount": len(props),
            "properties": props,
        })
    return shapes


def extract_augmenting_namespaces(g, manifest, to_qname):
    """Identify augmenting namespaces and their properties from manifest."""
    augmenting = []
    for aug in manifest["namespaces"].get("augmenting", []):
        aug_uri = aug["uri"]
        # Find properties in this namespace (both object and datatype)
        aug_props = []
        for prop in g.subjects(RDF.type, OWL.DatatypeProperty):
            if str(prop).startswith(aug_uri):
                aug_props.append(to_qname(prop))
        for prop in g.subjects(RDF.type, OWL.ObjectProperty):
            if str(prop).startswith(aug_uri):
                aug_props.append(to_qname(prop))
        if aug_props:
            augmenting.append({
                "prefix": aug["prefix"],
                "namespace": aug_uri,
                "propertyCount": len(aug_props),
                "properties": sorted(aug_props),
            })
    return augmenting


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 2: Extract concepts from source package")
    parser.add_argument("--package", default=None, help="Path to source domain package")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    args = parser.parse_args()

    PKG, run_dir = load_inputs(args.package, args.run_dir)

    # Load or auto-generate manifest
    manifest = load_or_build_manifest(PKG)
    primary_ns = manifest["namespaces"]["primary"]
    if not primary_ns:
        print("Error: No primary namespace found in package manifest.")
        sys.exit(1)

    # Build namespace map and qname resolver
    ns_map = build_ns_map(manifest)
    to_qname = make_to_qname(ns_map)

    print(f"  Package: {manifest['packageName']}")
    print(f"  Primary namespace: {primary_ns['prefix']}: <{primary_ns['uri']}>")

    # Load graphs from manifest-declared files
    g = load_ontology_graph(PKG, manifest)
    shapes_g = load_shapes_graph(PKG, manifest)
    vocab_g = load_vocab_graph(PKG, manifest)
    seed_g = load_seed_graph(PKG, manifest)

    # Extract everything
    classes = extract_classes(g, to_qname)
    obj_props = extract_object_properties(g, to_qname)
    data_props = extract_datatype_properties(g, to_qname)
    codelist_schemes = extract_codelist_schemes(vocab_g, to_qname)
    wf_models = extract_workflow_models(g, primary_ns["uri"], to_qname)
    shacl_shapes = extract_shacl_shapes(shapes_g, to_qname)
    augmenting_namespaces = extract_augmenting_namespaces(g, manifest, to_qname)

    # Build concept inventory
    inventory = {
        "extractedAt": datetime.now(timezone.utc).isoformat(),
        "sourcePackage": str(PKG),
        "primaryNamespace": primary_ns,
        "namespaceMap": ns_map,
        "summary": {
            "classCount": len(classes),
            "objectPropertyCount": len(obj_props),
            "datatypePropertyCount": len(data_props),
            "codelistSchemeCount": len(codelist_schemes),
            "totalCodelistConcepts": sum(s["conceptCount"] for s in codelist_schemes),
            "workflowModelCount": len(wf_models),
            "totalWorkflowStates": sum(w["stateCount"] for w in wf_models),
            "totalWorkflowTransitions": sum(w["transitionCount"] for w in wf_models),
            "shaclShapeCount": len(shacl_shapes),
            "augmentingNamespaceCount": len(augmenting_namespaces),
        },
        "classes": classes,
        "objectProperties": obj_props,
        "datatypeProperties": data_props,
        "codelistSchemes": codelist_schemes,
        "workflowModels": wf_models,
        "shaclShapes": shacl_shapes,
        "augmentingNamespaces": augmenting_namespaces,
    }

    # Print summary
    print(json.dumps(inventory["summary"], indent=2))
    print()
    print("Classes:")
    for c in inventory["classes"]:
        sc = f" < {', '.join(c['subClassOf'])}" if c["subClassOf"] else ""
        print(f"  {c['qname']}{sc}")
    print()
    print(f"Object Properties: {len(obj_props)}")
    print(f"Datatype Properties: {len(data_props)}")
    print(f"Codelist Schemes: {len(codelist_schemes)} ({inventory['summary']['totalCodelistConcepts']} concepts)")
    print(f"Workflow Models: {len(wf_models)} ({inventory['summary']['totalWorkflowStates']} states, {inventory['summary']['totalWorkflowTransitions']} transitions)")
    print(f"SHACL Shapes: {len(shacl_shapes)}")
    print(f"Augmenting Namespaces: {len(augmenting_namespaces)}")

    # Save — always to run directory
    if not run_dir:
        print("Error: run directory is required. Pass --run-dir to specify.", file=sys.stderr)
        sys.exit(1)
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "concept-inventory.json"
    out_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
