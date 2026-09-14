"""Shared pure utility functions for ontology generation.

Used by generate_edge_ontology.py (OWL), generate_cmf_from_matrix.py (CMF),
and generate_kg_artifacts.py (knowledge graph). All functions are stateless
and do not perform I/O.
"""

XSD = "http://www.w3.org/2001/XMLSchema#"


def property_qname_resolver(inventory):
    """Resolve a recorded property name to its inventory QName.

    Prefer exact identity, then a unique local-name match for old matrices
    that incorrectly used the parent concept's namespace. Ambiguous names
    remain unresolved; never guess between properties sharing a local name.
    """
    known = set()
    by_local = {}
    inventory = inventory or {}
    for prop in ((inventory.get("objectProperties") or [])
                 + (inventory.get("datatypeProperties") or [])):
        qname = prop.get("qname")
        if not qname:
            continue
        known.add(qname)
        by_local.setdefault(local_name(qname), []).append(qname)

    def resolve(name):
        if not known or name in known:
            return name
        candidates = by_local.get(local_name(name), [])
        return candidates[0] if len(candidates) == 1 else name

    return resolve


def property_mapping_index(matrix, inventory=None):
    """Index decisions by (class QName, resolved source-property QName)."""
    resolve = property_qname_resolver(inventory)
    index = {}
    for entry in matrix.get("mappings", []):
        concept = entry.get("sourceConcept")
        for pm in entry.get("propertyMappings") or []:
            index[(concept, resolve(pm.get("sourceProperty", "")))] = pm
    return index


def accepted_reuse_target(pm):
    """The target property an accepted ``reuse-property`` decision names, or
    None. One home for the three conditions the emitters must agree on."""
    if not pm or pm.get("action") != "reuse-property":
        return None
    if pm.get("reviewStatus") != "accepted":
        return None
    target = pm.get("targetProperty")
    return target if target and target != "[undecided]" else None


def source_prefix(inventory):
    """Source QName prefix, detected from the inventory's first class."""
    classes = inventory.get("classes") or []
    return classes[0]["qname"].split(":")[0] if classes else ""


def source_namespace_bindings(inventory, target_ns_map, edge_prefix):
    """Map source prefixes to (emitted prefix, URI), avoiding target collisions.

    QName lookup keys stay unchanged. Both emitters use the same stable alias
    only when one prefix would otherwise identify two different namespaces.
    """
    source = {prefix.rstrip(":"): uri for uri, prefix in inventory.get("namespaceMap", {}).items()}
    source.update({ns["prefix"].rstrip(":"): ns["namespace"]
                   for ns in inventory.get("augmentingNamespaces", [])})
    reserved = {**target_ns_map, edge_prefix.rstrip(":"): None, "ext": None,
                "owl": "http://www.w3.org/2002/07/owl#",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                "xsd": XSD, "xs": XSD, "skos": "http://www.w3.org/2004/02/skos/core#",
                "sh": "http://www.w3.org/ns/shacl#", "dcterms": "http://purl.org/dc/terms/"}
    occupied = set(reserved) | set(source)
    bindings = {}
    for prefix, uri in sorted(source.items()):
        if prefix == source_prefix(inventory):
            continue  # primary source properties get the edge/ext namespace
        emitted = prefix
        if prefix in reserved and reserved[prefix] != uri:
            emitted = f"source_{prefix}"
            suffix = 2
            while emitted in occupied:
                emitted = f"source_{prefix}_{suffix}"
                suffix += 1
            occupied.add(emitted)
        bindings[prefix] = (emitted, uri)
    return bindings


def local_name(qname_or_iri):
    """Extract local name from qname (prefix:Foo → Foo) or IRI."""
    if ":" in qname_or_iri and not qname_or_iri.startswith("http"):
        return qname_or_iri.split(":", 1)[1]
    if "#" in qname_or_iri:
        return qname_or_iri.split("#")[-1]
    return qname_or_iri.rsplit("/", 1)[-1]


def edge_class_name(qname):
    """Map source class qname to edge type name (e.g. prefix:Permit → PermitType)."""
    return local_name(qname) + "Type"


def target_to_qname(target_type):
    """Return the prefixed qname form of a target ontology type."""
    return target_type


def xsd_qname(full_iri):
    """Convert full XSD IRI or xs: shorthand to xsd:localName."""
    if full_iri and full_iri.startswith(XSD):
        return "xsd:" + full_iri[len(XSD):]
    if full_iri and full_iri.startswith("xs:"):
        return "xsd:" + full_iri[3:]
    return full_iri


# ---------------------------------------------------------------------------
# Data-driven domain inference for properties with empty rdfs:domain
# ---------------------------------------------------------------------------
def infer_domains_from_shapes(properties, shapes):
    """Use SHACL shapes to infer domains: if a shape targets class X
    and constrains property P, then P belongs to X."""
    shape_domains = {}
    for shape in shapes:
        if not shape_property_is_evaluated(shape):
            continue
        for prop in shape.get("properties", []):
            path = prop.get("path")
            if path and shape_property_is_evaluated(prop):
                shape_domains.setdefault(path, set()).update(shape_target_classes(shape))
    return shape_domains


def assign_properties_to_classes(properties, all_active_classes, shape_domains):
    """Combine explicit domains and active SHACL associations for each property."""
    assigned = {}
    unassigned = []

    for prop in properties:
        qname = prop["qname"]
        associations = set(prop["domain"]) | shape_domains.get(qname, set())
        active = sorted(associations & set(all_active_classes))
        if active:
            assigned[qname] = active
        else:
            unassigned.append(qname)

    return assigned, unassigned


def detect_consolidations(matrix, class_by_qname):
    """Find concepts excluded via human review that were absorbed into another class."""
    parent_to_absorbed = {}
    for m in matrix["mappings"]:
        if m["action"] != "exclude":
            continue
        src = m["sourceConcept"]
        cls = class_by_qname.get(src)
        if not cls or not cls.get("subClassOf"):
            continue
        parent = cls["subClassOf"][0]
        parent_to_absorbed.setdefault(parent, []).append(src)

    consolidations = []
    for parent, absorbed in parent_to_absorbed.items():
        if len(absorbed) >= 2:
            parent_local = local_name(parent)
            scheme_name = f"{parent_local}RoleScheme"
            consolidations.append((parent, absorbed, scheme_name))

    return consolidations


def shape_target_classes(shape):
    """Every class a SHACL NodeShape targets — the one home for that question.

    SHACL allows a NodeShape to carry several `sh:targetClass` values.
    Extraction used to keep one arbitrarily under `targetClass`, so a shape
    targeting two classes constrained only one of them and no consumer
    could tell. `targetClasses` now carries them all; this falls back to
    the single name for an inventory written before that, and for the test
    fixtures that still build shapes by hand.
    """
    targets = shape.get("targetClasses")
    if targets is not None:
        return list(targets)
    single = shape.get("targetClass")
    return [single] if single else []


def shape_property_is_evaluated(property_shape):
    """Whether SHACL evaluates a shape, independently of result severity.

    SHACL sections 2.1.4 and 2.1.6: severity categorizes results; only
    deactivation disables evaluation. Applies to node and property shapes.
    """
    return not property_shape.get("deactivated", False)
