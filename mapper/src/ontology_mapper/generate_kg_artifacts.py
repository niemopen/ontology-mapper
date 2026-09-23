#!/usr/bin/env python3
"""Stage 6c: Generate KG Artifacts — knowledge graph deployment scripts.

Reads the concept inventory and mapping matrix from the pipeline run,
then emits all kg/ directory artifacts:

  - kg/neo4j/schema.cypher     (constraints, indexes, node/edge DDL)
  - kg/neo4j/seed.cypher       (sample data from source seed data)
  - kg/neo4j/queries/*.cypher  (reusable query templates)
  - kg/rdf/{source}-edge.trig  (named graph export in TriG)
  - kg/rdf/sparql/*.rq         (SPARQL query templates)
  - kg/import/internal-to-edge.json  (transform rules)
  - kg/import/loader-config.json     (graph import config)

This is a deterministic tool — no semantic reasoning required.

Usage:
    om-generate-kg                  # uses mapper state
    om-generate-kg <run_dir> <pkg>  # explicit paths
"""

import json
import re
import sys
from pathlib import Path
from ontology_mapper.run_dir_utils import utc_stamp

from ontology_mapper.pipeline_context import load_context
from ontology_mapper.generation_utils import local_name, relationship_type, XSD

SKOS_CONCEPT = "http://www.w3.org/2004/02/skos/core#Concept"


def xsd_to_cypher_type(xsd_iri):
    """Map XSD datatype IRI to Neo4j property type name."""
    if not xsd_iri:
        return "STRING"
    local = xsd_iri.replace(XSD, "") if xsd_iri.startswith(XSD) else xsd_iri
    mapping = {
        "string": "STRING", "anyURI": "STRING", "normalizedString": "STRING",
        "integer": "INTEGER", "int": "INTEGER", "long": "INTEGER",
        "nonNegativeInteger": "INTEGER", "positiveInteger": "INTEGER",
        "decimal": "FLOAT", "float": "FLOAT", "double": "FLOAT",
        "boolean": "BOOLEAN",
        "date": "DATE", "dateTime": "DATETIME",
    }
    return mapping.get(local, "STRING")




# ---------------------------------------------------------------------------
# Data model assembly
# ---------------------------------------------------------------------------
def build_active_classes(inv, matrix):
    """Build the list of active classes (reuse + extend + augment) with their properties.

    Returns a list of dicts with keys:
        sourceQname, iri, label, comment, action, targetType,
        datatypeProps (list of {qname, iri, label, range}),
        objectProps (list of {qname, iri, label, rangeQname, rangeLabel})

    ``iri`` is the identity the inventory recorded for the class or property;
    seed instances are matched on it, whatever namespace the QName belongs to.
    """
    from ontology_mapper.generation_utils import (
        emitted_class_action,
        emitted_graph_labels,
        graph_property_names,
        infer_domains_from_shapes,
        range_class_for,
        assign_properties_to_classes,
        shape_only_property_shapes,
        source_namespaces,
        source_prefix as primary_source_prefix,
    )

    mapping_by_concept = {m["sourceConcept"]: m for m in matrix["mappings"]}
    class_by_qname = {c["qname"]: c for c in inv["classes"]}

    labels = emitted_graph_labels(inv, matrix["mappings"])
    prop_names = graph_property_names(inv)
    shape_only = shape_only_property_shapes(inv)
    namespaces = source_namespaces(inv)
    active_qnames = set(labels)

    # Assign properties using the same logic as generate_edge_ontology
    shape_domains = infer_domains_from_shapes(
        inv["objectProperties"] + inv["datatypeProperties"],
        inv["shaclShapes"],
    )
    obj_assigned, _ = assign_properties_to_classes(
        inv["objectProperties"], active_qnames, shape_domains,
    )
    dt_assigned, _ = assign_properties_to_classes(
        inv["datatypeProperties"], active_qnames, shape_domains,
    )

    # Also pick up properties with explicit domains
    _primary = primary_source_prefix(inv)
    source_prefix = f"{_primary}:" if _primary else ""
    for prop in inv["datatypeProperties"]:
        if not prop["qname"].startswith(source_prefix) and prop["domain"]:
            active = [d for d in prop["domain"] if d in active_qnames]
            if active and prop["qname"] not in dt_assigned:
                dt_assigned[prop["qname"]] = active

    # Build lookup dicts
    obj_by_qname = {p["qname"]: p for p in inv["objectProperties"]}
    dt_by_qname = {p["qname"]: p for p in inv["datatypeProperties"]}

    def props_for_class(cls_qname):
        obj = []
        dt = []
        seen_obj = set()
        seen_dt = set()
        for pq, domains in obj_assigned.items():
            if cls_qname in domains and pq in obj_by_qname:
                obj.append(obj_by_qname[pq])
                seen_obj.add(pq)
        for pq, domains in dt_assigned.items():
            if cls_qname in domains and pq in dt_by_qname:
                dt.append(dt_by_qname[pq])
                seen_dt.add(pq)
        # Also pick up properties with explicit domain not yet found
        for p in inv["objectProperties"]:
            if cls_qname in p["domain"] and p["qname"] not in seen_obj:
                obj.append(p)
        for p in inv["datatypeProperties"]:
            if cls_qname in p["domain"] and p["qname"] not in seen_dt:
                dt.append(p)
        # A property only this class's shape names, which the OWL, SHACL
        # and CMF carry; its IRI from the source namespaces, so seed
        # triples find it, and its range from the shape.
        for path, spec in shape_only.get(cls_qname, {}).items():
            prefix, _, local = path.partition(":")
            p = {"qname": path, "iri": namespaces[prefix] + local if prefix in namespaces else None}
            if spec["class"]:
                obj.append({**p, "range": [spec["class"]]})
            else:
                dt.append({**p, "range": [spec["datatype"]] if spec["datatype"] else []})
        return (
            sorted(obj, key=lambda p: p["qname"]),
            sorted(dt, key=lambda p: p["qname"]),
        )

    result = []
    for cls in inv["classes"]:
        qname = cls["qname"]
        m = mapping_by_concept.get(qname)
        action = emitted_class_action(m)
        if action not in ("reuse", "extend", "augment"):
            continue

        obj_props, dt_props = props_for_class(qname)

        # Build cleaned property lists
        datatype_props = []
        for p in dt_props:
            ranges = p.get("range", [])
            datatype_props.append({
                "qname": p["qname"],
                # The inventory's own IRI for the predicate, which the
                # seed generator needs to recover a qname from a triple.
                # A CSV source mints `{ns}#{Class}.{prop}`, so tailing
                # the IRI by hand gives a key with a dot in it, which
                # Neo4j rejects.
                "iri": p.get("iri"),
                "label": prop_names[p["qname"]],
                "range": ranges[0] if ranges else XSD + "string",
            })

        object_props = []
        for p in obj_props:
            ranges = p.get("range", [])
            if not ranges:
                continue
            # An excluded range class stands for its nearest emitted
            # ancestor, the class the OWL/SHACL and CMF ranges name
            # (range_class_for, their shared redirect); dropping the
            # relationship left the graph without an edge both models have.
            range_qname = range_class_for(ranges[0], mapping_by_concept, class_by_qname) or ranges[0]
            # Only include if the range is an active class. Not "primary
            # AND inactive": an augmenting namespace is first-class here,
            # and an excluded class is excluded whatever namespace it
            # lives in — otherwise the graph carries a relationship, and
            # the transform rules a target node type, for a class the
            # package never declares.
            if range_qname not in active_qnames:
                continue
            # Skip SKOS Concept ranges (codelist references, not graph edges)
            if range_qname == SKOS_CONCEPT:
                continue
            object_props.append({
                "qname": p["qname"],
                "iri": p.get("iri"),
                "label": prop_names[p["qname"]],
                "rangeQname": range_qname,
                "rangeLabel": labels[range_qname],
            })

        result.append({
            "sourceQname": qname,
            "iri": cls["iri"],
            "label": labels[qname],
            "comment": cls.get("comment", ""),
            "action": action,
            "targetType": m.get("targetType"),
            "datatypeProps": datatype_props,
            "objectProps": object_props,
        })

    return sorted(result, key=lambda c: c["label"])


def build_relationships(active_classes):
    """Extract all unique relationships from active classes.

    Returns list of dicts: {name, sourceLabel, targetLabel, propQname, propLabel}
    """
    seen = set()
    rels = []
    for cls in active_classes:
        for op in cls["objectProps"]:
            key = (relationship_type(op["label"]), cls["label"], op["rangeLabel"])
            if key not in seen:
                seen.add(key)
                rels.append({
                    "name": key[0],
                    "sourceLabel": cls["label"],
                    "targetLabel": op["rangeLabel"],
                    "propQname": op["qname"],
                    "propLabel": op["label"],
                })
    return sorted(rels, key=lambda r: (r["sourceLabel"], r["name"]))


# ---------------------------------------------------------------------------
# Neo4j generators
# ---------------------------------------------------------------------------
def generate_schema_cypher(active_classes, relationships, source):
    """Generate kg/neo4j/schema.cypher — constraints, indexes, relationship docs."""
    now = utc_stamp()
    lines = [
        f"// {'=' * 65}",
        f"// {source.upper()} Edge Ontology — Neo4j Schema DDL",
        f"// Generated: {now}",
        f"// {'=' * 65}",
        "",
        "// ── Node Constraints ──────────────────────────────────────────",
        "// Uniqueness constraint on the canonical identifier for each node type.",
        "",
    ]

    for cls in active_classes:
        label = cls["label"]
        lines.append(f"CREATE CONSTRAINT {label}_identifier IF NOT EXISTS")
        lines.append(f"  FOR (n:{label}) REQUIRE n.identifier IS UNIQUE;")
        lines.append("")

        # Look for domain-specific identifiers (applicationNumber, permitNumber, etc.)
        for dp in cls["datatypeProps"]:
            prop_name = dp["label"]
            if prop_name != "identifier" and (
                prop_name.endswith("Number") or prop_name.endswith("Id")
            ):
                lines.append(f"CREATE CONSTRAINT {label}_{prop_name} IF NOT EXISTS")
                lines.append(f"  FOR (n:{label}) REQUIRE n.{prop_name} IS UNIQUE;")
                lines.append("")

    lines.append("// ── Indexes ──────────────────────────────────────────────────")
    lines.append("// Composite and property indexes for common query patterns.")
    lines.append("")

    for cls in active_classes:
        label = cls["label"]
        # Index on displayName or legalName if present
        name_props = [dp["label"] for dp in cls["datatypeProps"]
                      if dp["label"] in ("displayName", "legalName", "name")]
        if name_props:
            idx_prop = name_props[0]
            lines.append(f"CREATE INDEX {label}_{idx_prop} IF NOT EXISTS")
            lines.append(f"  FOR (n:{label}) ON (n.{idx_prop});")
            lines.append("")

        # Index on status-like properties
        status_props = [dp["label"] for dp in cls["datatypeProps"]
                        if "status" in dp["label"].lower() or "type" in dp["label"].lower()]
        for sp in status_props[:1]:  # At most one status index per class
            lines.append(f"CREATE INDEX {label}_{sp} IF NOT EXISTS")
            lines.append(f"  FOR (n:{label}) ON (n.{sp});")
            lines.append("")

    lines.append("// ── Relationship Types ────────────────────────────────────────")
    lines.append("// Documented relationship types in this graph.")
    lines.append("")

    for rel in relationships:
        lines.append(f"// {rel['name']}: (:{rel['sourceLabel']})-[:{rel['name']}]->(:{rel['targetLabel']})")

    lines.append("")
    return "\n".join(lines)


def generate_seed_cypher(active_classes, relationships, seed_data_path, source):
    """Generate kg/neo4j/seed.cypher — sample data from source seed TTL.

    Seed instances are matched on the ``iri`` each active class and object
    property carries from the inventory, so classes from augmenting or other
    non-primary source namespaces are seeded alongside the primary ones. The
    seed file's own prefix declarations are not consulted.
    """
    now = utc_stamp()

    header = [
        f"// {'=' * 65}",
        f"// {source.upper()} Edge Ontology — Neo4j Seed Data",
        f"// Generated: {now}",
        f"// Source: {seed_data_path}",
        f"// {'=' * 65}",
        "",
    ]

    if not Path(seed_data_path).exists():
        header.append("// No seed data file found. Populate manually or re-run with seed data present.")
        return "\n".join(header)

    try:
        from rdflib import Graph as RdfGraph, URIRef, RDF
    except ImportError:
        header.append("// rdflib not available — seed data generation skipped.")
        return "\n".join(header)

    g = RdfGraph()
    g.parse(str(seed_data_path), format="turtle")

    # Build class IRI -> label mapping from active classes
    if not active_classes:
        header.append("// No active classes — nothing to seed.")
        return "\n".join(header)

    active_labels = {URIRef(cls["iri"]): cls for cls in active_classes}
    seeded_types = {t for _, _, t in g.triples((None, RDF.type, None))}
    if not seeded_types & set(active_labels):
        # Silence here reads as "no seed data to load". Name one of each
        # so the mismatch (a trailing slash, http vs https) is visible.
        example_active = sorted(str(iri) for iri in active_labels)[0]
        example_seed = sorted(str(t) for t in seeded_types)[0] if seeded_types else "(none)"
        header.append("// No seed instance matches an active class. The seed "
                      "file types instances as " + example_seed + "; this run's "
                      "inventory records " + example_active + ".")

    # Collect datatype property label lookups, and the inventory's own
    # name for each predicate IRI: a CSV-shaped property IRI
    # (`{ns}#{Class}.{prop}`) tailed by hand gives a key with a dot in
    # it, which Neo4j rejects — the hazard this file already fixed for
    # relationship type names.
    dt_prop_labels = {}
    dt_prop_qnames = {}
    for cls in active_classes:
        for dp in cls["datatypeProps"]:
            dt_prop_labels[dp["qname"]] = dp["label"]
            if dp.get("iri"):
                dt_prop_qnames[str(dp["iri"])] = dp["qname"]

    # Phase 1: Create nodes
    node_lines = [
        "// ── Node Creation ─────────────────────────────────────────────",
        "",
    ]

    # Track created node identifiers for relationship creation
    node_identifiers = {}  # subject IRI -> (label, identifier_value)

    for subj in sorted(set(g.subjects(RDF.type, None))):
        # Find which active class this instance belongs to
        types = list(g.objects(subj, RDF.type))
        matched_cls = None
        for t in types:
            if t in active_labels:
                matched_cls = active_labels[t]
                break
        if not matched_cls:
            continue

        label = matched_cls["label"]
        props = {}

        # Collect datatype property values
        for pred, obj in g.predicate_objects(subj):
            if pred == RDF.type:
                continue
            pred_str = str(pred)
            # Only include literal (datatype) values for node creation
            if hasattr(obj, "datatype") or hasattr(obj, "language") or not hasattr(obj, "n3"):
                # It's a literal
                # The key schema.cypher and the transforms name
                # (graph_property_names); a local name of its own merged
                # two namespaces' properties into one key.
                known = dt_prop_qnames.get(pred_str)
                # A predicate the inventory does not declare keeps its local
                # name, cleaned to a key Neo4j accepts (`Class.prop` from a
                # CSV-shaped IRI was not one).
                prop_local = (dt_prop_labels[known] if known in dt_prop_labels
                              else re.sub(r"[^A-Za-z0-9_]", "_", local_name(pred_str)))
                val = str(obj)
                # Detect type for proper Cypher literal formatting
                if hasattr(obj, "datatype") and obj.datatype:
                    dt = str(obj.datatype)
                    if "integer" in dt or "int" in dt:
                        props[prop_local] = val  # numeric, no quotes
                    elif "decimal" in dt or "float" in dt or "double" in dt:
                        props[prop_local] = val
                    elif "boolean" in dt:
                        props[prop_local] = val.lower()
                    elif "date" in dt.lower():
                        props[prop_local] = f'"{val}"'
                    else:
                        props[prop_local] = f'"{_cypher_escape(val)}"'
                else:
                    props[prop_local] = f'"{_cypher_escape(val)}"'

        if not props:
            continue

        # Track for relationships — find an identifier property generically
        identifier = props.get("identifier")
        if not identifier:
            for k in sorted(props):
                if k.endswith("Number") or k.endswith("Id"):
                    identifier = props[k]
                    break
        if not identifier:
            # A node with no id-like property still has its instance IRI;
            # without one its relationships were dropped from the seed.
            identifier = f'"{_cypher_escape(str(subj))}"'
        if identifier:
            # Strip quotes if present
            id_val = identifier.strip('"')
            node_identifiers[str(subj)] = (label, id_val)
            # Relationships MATCH on `identifier` and schema.cypher
            # constrains it; a node whose identifier came from `feeNumber`
            # never carried one, so every seeded relationship matched
            # nothing when loaded.
            props.setdefault("identifier", identifier)

        prop_str = ", ".join(f"{k}: {v}" for k, v in sorted(props.items()))
        node_lines.append(f"CREATE (:{label} {{{prop_str}}});")

    node_lines.append("")

    # Phase 2: Create relationships
    rel_lines = [
        "// ── Relationships ─────────────────────────────────────────────",
        "",
    ]

    # Known relationship properties by IRI. The relationship type comes from
    # the property's QName, the same derivation schema.cypher and the import
    # transform use, not from the predicate string: a CSV-shaped property IRI
    # (`{ns}#{Class}.{prop}`) would otherwise yield `[:CLASS.PROP]`.
    rel_props = {op["iri"]: op for cls in active_classes for op in cls["objectProps"]}

    for subj, pred, obj in sorted(g):
        if pred == RDF.type:
            continue
        pred_str = str(pred)
        subj_str = str(subj)
        obj_str = str(obj)

        # Only process object properties (obj must be a URI, not a literal)
        if hasattr(obj, "datatype") or hasattr(obj, "language"):
            continue
        if not obj_str.startswith("http"):
            continue

        # Both subject and object must be known nodes
        if subj_str not in node_identifiers or obj_str not in node_identifiers:
            continue

        # Must be a known relationship property
        if pred_str not in rel_props:
            continue

        src_label, src_id = node_identifiers[subj_str]
        tgt_label, tgt_id = node_identifiers[obj_str]
        rel_name = relationship_type(rel_props[pred_str]["label"])

        rel_lines.append(f"MATCH (a:{src_label} {{identifier: \"{src_id}\"}})")
        rel_lines.append(f"MATCH (b:{tgt_label} {{identifier: \"{tgt_id}\"}})")
        rel_lines.append(f"CREATE (a)-[:{rel_name}]->(b);")
        rel_lines.append("")

    return "\n".join(header + node_lines + rel_lines)


def _cypher_escape(s):
    """Escape a string for use in Cypher string literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def generate_query_templates(active_classes, relationships, source):
    """Generate reusable Cypher query templates. Returns {name: content}."""
    now = utc_stamp()
    templates = {}

    # 1. find-by-identifier — generic
    templates["find-by-identifier"] = f"""\
// Find any node by its identifier
// Generated: {now}
// Parameters: $label (node label), $identifier (identifier value)
//
// Usage (Neo4j browser):
//   :param label => "PermitApplication"
//   :param identifier => "APP-2026-1001"

MATCH (n)
WHERE $label IN labels(n) AND n.identifier = $identifier
RETURN n;
"""

    # 2. Entity-specific search for top entity types (by property count)
    top_classes = sorted(active_classes, key=lambda c: len(c["datatypeProps"]), reverse=True)[:3]
    for cls in top_classes:
        label = cls["label"]
        name = f"find-{_kebab(label)}"
        templates[name] = f"""\
// Find {label} nodes by property value
// Generated: {now}
// Parameters: $propertyName, $value

MATCH (n:{label})
WHERE n[$propertyName] = $value
RETURN n;
"""

    # 3. Entity with all relations for well-connected types
    connected = [cls for cls in active_classes if len(cls["objectProps"]) >= 2]
    for cls in connected[:5]:
        label = cls["label"]
        name = f"{_kebab(label)}-with-relations"
        templates[name] = f"""\
// Retrieve {label} with all connected entities (depth 1)
// Generated: {now}
// Parameters: $identifier

MATCH (n:{label} {{identifier: $identifier}})
OPTIONAL MATCH (n)-[r]-(related)
RETURN n, collect(DISTINCT {{rel: type(r), node: related}}) AS connections;
"""

    # 4. Shortest path — generic
    templates["shortest-path"] = f"""\
// Find shortest path between two nodes
// Generated: {now}
// Parameters: $startId, $endId

MATCH (a {{identifier: $startId}}), (b {{identifier: $endId}})
MATCH p = shortestPath((a)-[*..6]-(b))
RETURN p;
"""

    # 5. Subgraph export — useful for graph exchange
    templates["export-subgraph"] = f"""\
// Export a subgraph rooted at a node (depth 2)
// Generated: {now}
// Parameters: $identifier

MATCH path = (root {{identifier: $identifier}})-[*0..2]-(connected)
RETURN path;
"""

    return templates


def _kebab(name):
    """Convert PascalCase to kebab-case."""
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", name).lower()


# ---------------------------------------------------------------------------
# RDF / SPARQL generators
# ---------------------------------------------------------------------------
def generate_trig(ctx):
    """Generate kg/rdf/{source}-edge.trig — named graph wrapping the edge ontology."""
    now = utc_stamp()
    edge_ns = ctx.edge_ns_hash

    # Read the core and extensions TTL
    ont_dir = ctx.pkg_dir / "ontology"
    core_path = ont_dir / ctx.ontology_filename("core")
    ext_path = ont_dir / ctx.ontology_filename("extensions")

    if not core_path.exists():
        return f"# No ontology files found — TriG generation skipped.\n# Generated: {now}\n"

    core_content = core_path.read_text(encoding="utf-8")
    ext_content = ext_path.read_text(encoding="utf-8") if ext_path.exists() else ""

    # Extract prefix declarations (deduplicated)
    prefixes = []
    seen_prefixes = set()
    triple_blocks = []

    for content in [core_content, ext_content]:
        block_lines = []
        for line in content.split("\n"):
            if line.startswith("@prefix "):
                pfx = line.split()[1]  # e.g. "nc:"
                if pfx not in seen_prefixes:
                    seen_prefixes.add(pfx)
                    prefixes.append(line)
            elif line.strip() and not line.startswith("@prefix"):
                block_lines.append(line)
        triple_blocks.append("\n".join(block_lines))

    lines = [
        f"# {'=' * 65}",
        f"# {ctx.source.upper()} Edge Ontology — Named Graph (TriG)",
        f"# Generated: {now}",
        f"# {'=' * 65}",
        "",
    ]
    lines.extend(prefixes)
    lines.append("")
    lines.append(f"GRAPH <{edge_ns.rstrip('#')}/graph> {{")
    lines.append("")

    for block in triple_blocks:
        # Indent the triple blocks inside the GRAPH wrapper
        for line in block.split("\n"):
            if line.strip():
                lines.append(f"    {line}")
            else:
                lines.append("")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_sparql_templates(ctx):
    """Generate SPARQL query templates. Returns {name: content}."""
    now = utc_stamp()
    edge_ns = ctx.edge_ns_hash
    templates = {}

    templates["describe-entity"] = f"""\
# Describe an entity by IRI
# Generated: {now}
# Parameters: Replace $entityIRI with the target entity IRI

PREFIX edge: <{edge_ns}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

DESCRIBE <$entityIRI>
"""

    templates["list-classes"] = f"""\
# List all edge ontology classes with labels
# Generated: {now}

PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class ?label ?comment
WHERE {{
  ?class a owl:Class .
  OPTIONAL {{ ?class rdfs:label ?label }}
  OPTIONAL {{ ?class rdfs:comment ?comment }}
}}
ORDER BY ?label
"""

    templates["find-by-type"] = f"""\
# Find all instances of a given type
# Generated: {now}
# Parameters: Replace $typeIRI with the target class IRI

PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?instance ?label
WHERE {{
  ?instance rdf:type <$typeIRI> .
  OPTIONAL {{ ?instance rdfs:label ?label }}
}}
ORDER BY ?label
"""

    templates["entity-neighborhood"] = f"""\
# Get an entity and all its direct relationships
# Generated: {now}
# Parameters: Replace $entityIRI with the target entity IRI

PREFIX edge: <{edge_ns}>

SELECT ?predicate ?object
WHERE {{
  <$entityIRI> ?predicate ?object .
}}
ORDER BY ?predicate
"""

    templates["construct-subgraph"] = f"""\
# Construct a subgraph for a given entity (all direct triples)
# Generated: {now}
# Parameters: Replace $entityIRI with the target entity IRI

PREFIX edge: <{edge_ns}>

CONSTRUCT {{
  <$entityIRI> ?p ?o .
  ?s ?p2 <$entityIRI> .
}}
WHERE {{
  {{ <$entityIRI> ?p ?o . }}
  UNION
  {{ ?s ?p2 <$entityIRI> . }}
}}
"""

    return templates


# ---------------------------------------------------------------------------
# Import config generators
# ---------------------------------------------------------------------------
def generate_internal_to_edge_transform(active_classes):
    """Generate kg/import/internal-to-edge.json — transform rules."""
    transforms = []
    for cls in active_classes:
        prop_mappings = []
        for dp in cls["datatypeProps"]:
            prop_name = dp["label"]
            transform = None
            # Detect date transforms
            range_iri = dp["range"]
            if range_iri in (XSD + "date", XSD + "dateTime", "xsd:date", "xsd:dateTime"):
                transform = "xsd:date-to-iso8601"
            # A property name alone does not establish a code-list conversion.
            prop_mappings.append({
                "source": dp["qname"],
                "target": prop_name,
                "transform": transform,
            })

        rel_mappings = []
        for op in cls["objectProps"]:
            rel_mappings.append({
                "source": op["qname"],
                "target": relationship_type(op["label"]),
                "targetNodeType": op["rangeLabel"],
            })

        transforms.append({
            "sourceType": cls["sourceQname"],
            "targetLabel": cls["label"],
            "propertyMappings": prop_mappings,
            "relationMappings": rel_mappings,
        })

    return {"transforms": sorted(transforms, key=lambda t: t["targetLabel"])}


def generate_loader_config(source):
    """Generate kg/import/loader-config.json — graph import configuration."""
    return {
        "targetPlatform": "neo4j",
        "connectionProfile": "default",
        "loadOrder": ["schema.cypher", "seed.cypher"],
        "importMode": "create-or-merge",
        "batchSize": 1000,
        "constraints": {
            "uniqueProperties": True,
            "requiredProperties": True,
        },
        "sourceDataPaths": {
            "seedData": "kg/neo4j/seed.cypher",
            "schemaScript": "kg/neo4j/schema.cypher",
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Stage 6c: Generate knowledge graph artifacts")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    parser.add_argument("--package-dir", default=None, help="Edge package directory path")
    args = parser.parse_args()

    ctx = load_context(args.run_dir, args.package_dir)

    print(f"\n  Stage 6c: Generate KG Artifacts")
    print(f"  Run directory: {ctx.run_dir}")
    print(f"  Edge package:  {ctx.pkg_dir}")
    print()

    # Convenience locals
    run_dir = ctx.run_dir
    pkg = ctx.pkg_dir

    # Load inputs
    inv = json.loads((run_dir / "concept-inventory.json").read_text(encoding="utf-8"))
    matrix = json.loads((run_dir / "mapping-matrix.json").read_text(encoding="utf-8"))

    # Build data model
    active_classes = build_active_classes(inv, matrix)
    relationships = build_relationships(active_classes)

    # Create directories
    neo4j_dir = pkg / "kg" / "neo4j"
    queries_dir = neo4j_dir / "queries"
    rdf_dir = pkg / "kg" / "rdf"
    sparql_dir = rdf_dir / "sparql"
    import_dir = pkg / "kg" / "import"
    for d in [neo4j_dir, queries_dir, rdf_dir, sparql_dir, import_dir]:
        d.mkdir(parents=True, exist_ok=True)

    files_written = {}

    def write_artifact(path, content):
        path.write_text(content, encoding="utf-8")
        files_written[str(path.relative_to(pkg))] = len(content)

    # ── Neo4j artifacts ───────────────────────────────────────────────

    write_artifact(
        neo4j_dir / "schema.cypher",
        generate_schema_cypher(active_classes, relationships, ctx.source),
    )

    seed_path = Path(ctx.input_package_path) / "seed-data" / f"{ctx.source}-seed-data.ttl"
    write_artifact(
        neo4j_dir / "seed.cypher",
        generate_seed_cypher(active_classes, relationships, seed_path, ctx.source),
    )

    for name, content in generate_query_templates(active_classes, relationships, ctx.source).items():
        write_artifact(queries_dir / f"{name}.cypher", content)

    # ── RDF artifacts ─────────────────────────────────────────────────

    write_artifact(
        rdf_dir / ctx.trig_filename,
        generate_trig(ctx),
    )

    for name, content in generate_sparql_templates(ctx).items():
        write_artifact(sparql_dir / f"{name}.rq", content)

    # ── Import artifacts ──────────────────────────────────────────────

    write_artifact(
        import_dir / "internal-to-edge.json",
        json.dumps(generate_internal_to_edge_transform(active_classes), indent=2) + "\n",
    )

    write_artifact(
        import_dir / "loader-config.json",
        json.dumps(generate_loader_config(ctx.source), indent=2) + "\n",
    )

    # ── Summary ───────────────────────────────────────────────────────
    print(f"  Active classes: {len(active_classes)}")
    print(f"  Relationships: {len(relationships)}")
    print(f"  Files written: {len(files_written)}")
    for path, size in sorted(files_written.items()):
        print(f"    {path} ({size:,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
