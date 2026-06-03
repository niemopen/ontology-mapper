"""Shared pure utility functions for ontology generation.

Used by generate_edge_ontology.py (OWL), generate_cmf_from_matrix.py (CMF),
and generate_kg_artifacts.py (knowledge graph). All functions are stateless
and do not perform I/O.
"""

XSD = "http://www.w3.org/2001/XMLSchema#"


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
        target_cls = shape["targetClass"]
        for prop in shape["properties"]:
            path = prop["path"]
            shape_domains.setdefault(path, set()).add(target_cls)
    return shape_domains


def assign_properties_to_classes(properties, all_active_classes, shape_domains):
    """Assign properties to classes using explicit domains, then SHACL inference."""
    assigned = {}
    unassigned = []

    for prop in properties:
        qname = prop["qname"]
        domains = prop["domain"]

        if domains:
            active_domains = [d for d in domains if d in all_active_classes]
            if active_domains:
                assigned[qname] = active_domains
                continue

        if qname in shape_domains:
            shape_classes = [d for d in shape_domains[qname] if d in all_active_classes]
            if shape_classes:
                assigned[qname] = shape_classes
                continue

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
