"""Shared pure utility functions for ontology generation.

Used by generate_edge_ontology.py (OWL), generate_cmf_from_matrix.py (CMF),
and generate_kg_artifacts.py (knowledge graph). All functions are stateless
and do not perform I/O.
"""

import hashlib

XSD = "http://www.w3.org/2001/XMLSchema#"

_IRI_SCHEMES = ("http://", "https://", "urn:")


def is_full_iri(term):
    """True when a term carries its own scheme rather than a declared prefix.

    Such a term names something in a namespace the source package does not
    declare, so the generators cannot reference it by prefix — never by
    splitting the scheme off as if it were one. A term this package
    CREATES is minted into its own namespace instead
    (`created_property_qname`); a term it only REFERENCES is written out
    as the IRI it is (`source_term_ref`, `target_term_ref`).
    """
    return bool(term) and term.lower().startswith(_IRI_SCHEMES)


def definition_hash(definition):
    """Fingerprint a target definition for codebook drift detection.

    One home for the writer (alignment collection, the review cascade) and
    the reader (validation Check 12): a 16-character hex string, the 64-bit
    SHA-256 prefix, or None when there is no definition.
    """
    if definition is None:
        return None
    return hashlib.sha256(definition.encode("utf-8")).hexdigest()[:16]


def catalog_type_definition(target_type, catalog):
    """The catalog's own definition of a target type, or None if it has none."""
    for t in catalog.get("types", []):
        if t.get("qname") == target_type:
            return t.get("definition")
    return None


def catalog_type_label(target_type, catalog):
    """The catalog's display label for a target type (label-bearing catalogs
    such as SALI-FOLIO), or None when the catalog has none."""
    for t in catalog.get("types", []):
        if t.get("qname") == target_type:
            return t.get("label") or None
    return None


def property_qname_resolver(inventory):
    """Resolve a recorded property name to its inventory QName.

    Prefer exact identity, then a unique local-name match for old matrices
    that incorrectly used the parent concept's namespace. Ambiguous names
    remain unresolved; never guess between properties sharing a local name.
    """
    from ontology_mapper.build_strategy_reports import build_class_properties

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
    # "Which properties belong to this class" already has one home, and
    # it reads domains AND shape paths: a property declared with its
    # domain on a parent and attached to the child by the child's shape
    # is an ordinary source shape, and a domain-only test drops exactly
    # the population this fallback exists for.
    class_properties = build_class_properties(inventory)
    def resolve(name, concept=None):
        if not known or name in known:
            return name
        candidates = by_local.get(local_name(name), [])
        if concept is not None and class_properties:
            # A unique local name on a class that does not own it is a
            # different property; renaming a decision onto it invents a
            # mapping the reviewer never made. Asked only when the inventory
            # says something about ownership at all — an inventory with
            # neither domains nor shapes cannot answer it, and guessing
            # there is the old behaviour these callers relied on.
            # The concept's OWN properties, the same non-transitive answer
            # Stage 3/4 built the reviewer's list from: a decision row under
            # a concept is never legitimately about a property only an
            # ancestor declares, and unioning ancestors re-admits the
            # transplant this rule exists to block.
            candidates = [q for q in candidates
                          if q in class_properties.get(concept, set())]
        return candidates[0] if len(candidates) == 1 else name

    return resolve


def _same_decision(first, second):
    """Whether two rows record the same decision.

    Only the fields that ARE the decision: the provenance a row carries
    (`sourceProperty`, `sourcePath`, `sourceDefinition`, rationale) differs
    between a legacy spelling and its declared twin, which is exactly how two
    rows come to resolve to one key.
    """
    decided = ("action", "reviewStatus", "targetProperty", "newPropertyName")
    return all(first.get(field) == second.get(field) for field in decided)


def property_mapping_index(matrix, inventory=None):
    """Index decisions by (class QName, resolved source-property QName).

    Two rows can resolve to one key — a legacy spelling beside the
    declared one in a matrix saved before the identity rule, or edited by
    hand. Last-write-wins there would let row order decide whether an
    accepted reuse decision or a pending created property reaches the
    emitters, so the run refuses and names both rows. Two rows recording
    the SAME decision are one decision and pass.
    """
    resolve = property_qname_resolver(inventory)
    index = {}
    collisions = []
    for entry in matrix.get("mappings", []):
        concept = entry.get("sourceConcept")
        for pm in entry.get("propertyMappings") or []:
            key = (concept, resolve(pm.get("sourceProperty", ""), concept))
            previous = index.get(key)
            if previous is None:
                index[key] = pm
                continue
            if _same_decision(previous, pm):
                # A duplicated row carries no ambiguity: the same decision
                # twice is one decision, and refusing it would stop a run
                # over an editing slip that changes nothing.
                continue
            collisions.append((key, previous, pm))
    if collisions:
        raise ValueError(
            f"{len(collisions)} property decision(s) resolve to a decision "
            f"another row already made; reopen review:\n"
            + "\n".join(
                f"  - {concept}: {previous.get('sourceProperty')} and "
                f"{pm.get('sourceProperty')} both resolve to {resolved}"
                for (concept, resolved), previous, pm in collisions))
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


def qualified_target_property(target_prop, class_target_type):
    """A target property named by its local name alone, in its class's
    target namespace; any other spelling unchanged.

    One home for the OWL and CMF emitters: the OWL side qualified a bare
    local name by the class's target prefix while the CMF referenced it
    bare, an unbound reference Check 11 rejected. A bare catalog id with no
    prefixed class target to borrow from (SALI-FOLIO) stays as it is.
    """
    if (target_prop and ":" not in target_prop and class_target_type
            and ":" in class_target_type and not is_full_iri(class_target_type)):
        return f"{class_target_type.split(':', 1)[0]}:{target_prop}"
    return target_prop


def source_declared_properties(inventory):
    """The properties a source property list declares, as QNames.

    One home for the question every generator must answer alike: a term the
    source declares is minted into this package when no accepted reuse
    replaces it; a term only a SHACL shape names (``rdfs:label``, or a
    source term the source never declared) is referenced as the term it is.
    `build_class_properties` harvests shape paths as class properties, so
    such a term has a decision, but no emitter declares it.
    """
    return {p["qname"] for key in ("objectProperties", "datatypeProperties")
            for p in inventory.get(key, [])}


def created_property_is_declared(pm):
    """Whether the emitters declare a created term for this decision.

    The OWL emitter walks the inventory: a source property with no accepted
    reuse target is declared as a new term, whether its decision is still
    pending or absent. The CMF walks the inventory for reuse and extend
    classes, but an augmentation's properties from its `propertyMappings`
    rows, so the CMF declares an augmentation property only when a row
    exists. The extension catalog walks the decisions too, so it asks the
    same question here — otherwise the package's own inventory of what it
    adds omits terms its model declares.
    """
    return accepted_reuse_target(pm) is None


def source_prefix(inventory):
    """The primary source QName prefix: one home for every generator.

    The inventory declares it (``primaryNamespace``, written by extraction and
    CSV ingest). Classes are sorted by QName, so the first class belongs to
    whichever namespace sorts first, and an augmenting namespace can win that
    sort; it is only a fallback for inventories written before the declaration.
    """
    declared = (inventory.get("primaryNamespace") or {}).get("prefix") or ""
    if declared:
        return declared.rstrip(":")
    classes = inventory.get("classes") or []
    return classes[0]["qname"].split(":")[0] if classes else ""



def component_iri(namespace_uri, name):
    """A component's IRI from its namespace URI and name (NIEM NDR 6.0, 14.1.2)."""
    if namespace_uri.endswith(("/", "#", ":")):
        separator = ""
    elif namespace_uri.startswith("urn:"):
        separator = ":"
    else:
        separator = "/"
    return f"{namespace_uri}{separator}{name}"


def target_qname(term, namespaces):
    """Ground a full-IRI target term to its catalog QName.

    ``namespaces`` maps catalog prefixes to namespace URIs. A term that is not
    an IRI, or whose namespace the catalog does not bind, is returned unchanged
    so downstream reference validation still reports it.
    """
    if not is_full_iri(term):
        return term
    best = None
    for prefix, uri in sorted(namespaces.items()):
        base = component_iri(uri, "")
        if term.startswith(base) and len(term) > len(base):
            if best is None or len(base) > len(best[1]):
                best = (prefix, base)
    if best is None:
        return term
    prefix, base = best
    return f"{prefix}:{term[len(base):]}"


def created_property_qname(prop_qname, class_action, primary_prefix, bindings, edge_prefix):
    """One emitted identity for a created property in OWL, CMF and the catalog.

    A created property is a new term in the package's own namespace unless it
    belongs to a source namespace the package declares and re-binds. Extraction
    leaves a property whose namespace the manifest does not name as a full IRI
    (`make_to_qname` returns the IRI unchanged), and such a term has no prefix
    to split on and no binding to emit under: it is minted here like a primary
    one, never split into the pseudo-prefix `https`.
    """
    prefix = "" if is_full_iri(prop_qname) else prop_qname.split(":", 1)[0]
    if not prefix or prefix == primary_prefix:
        prefix = edge_prefix.rstrip(":") if class_action == "reuse" else "ext"
    else:
        prefix = bindings.get(prefix, (prefix, ""))[0]
    return f"{prefix}:{local_name(prop_qname)}"


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
    """Extract local name from qname (prefix:Foo → Foo) or IRI.

    The inverse of `component_iri` for every separator it writes. That
    function appends after a namespace already ending in "/", "#" or ":",
    and otherwise joins with ":" for `urn:` and "/" for the rest, so the
    name is whatever follows the LAST of those three characters: a `urn:`
    name is read from the right, and a namespace ending in one separator
    while containing another (`urn:example:model/v1`,
    `https://example.test/ns:`) still reads back whole.
    """
    if is_full_iri(qname_or_iri):
        cut = max(qname_or_iri.rfind(separator) for separator in ("#", "/", ":"))
        return qname_or_iri[cut + 1:] or qname_or_iri
    if ":" in qname_or_iri:
        return qname_or_iri.split(":", 1)[1]
    return qname_or_iri


def emitted_class_action(entry):
    """The action the emitters act on for a mapping entry, or None.

    "Only emit accepted mappings" — a `pending-review` entry is not one.
    Review exit blocks pending concepts other than exclusions, so
    reaching an emitter with one means review was bypassed. OWL and CMF
    must agree about that or they disagree about which classes the
    package contains.
    """
    if not entry:
        return None
    action = entry.get("action")
    if action == "exclude":
        # An exclusion is never presented for review (`get_pending_items`
        # filters it out), so its status stays `pending-review` for the
        # life of the run. Reading that as "undecided" made the emitters
        # skip the exclusion redirect and drop object properties ranged
        # on the excluded class — which the CMF kept declaring.
        return action
    if entry.get("reviewStatus") == "pending-review":
        return None
    return action


def range_class_for(class_qname, mapping_by_concept, class_by_qname):
    """The emitted source class an object range on *class_qname* stands for.

    The class itself when it is emitted; for an excluded class, the nearest
    emitted ancestor along first parents, through any number of exclusions;
    None when there is none. One home for the redirect, so the OWL/SHACL and
    CMF emitters name the same class for the same range: the OWL side went one
    step and only to a reuse or extend parent while the CMF recursed through
    any action, and the two models gave one property different ranges.
    """
    seen = set()
    qname = class_qname
    while qname and qname not in seen:
        seen.add(qname)
        action = emitted_class_action(mapping_by_concept.get(qname))
        if action is None:
            return None
        if action != "exclude":
            return qname
        parents = (class_by_qname.get(qname) or {}).get("subClassOf") or []
        qname = parents[0] if parents else None
    return None


def edge_class_name(qname):
    """Map source class qname to edge type name (e.g. prefix:Permit → PermitType)."""
    return local_name(qname) + "Type"


def colliding_edge_class_names(concepts):
    """Source concepts that would emit one edge class name.

    `edge_class_name` is namespace-blind, so two active classes sharing a
    local name across source namespaces — which augmenting and other
    non-primary namespaces make ordinary — collapse into a single emitted
    type carrying both superclasses, both labels and both property sets.
    No emitter can tell them apart afterwards, so the OWL generator — the
    entry every driver passes through, and the one that emits the class
    blocks — asks this before writing anything and refuses.

    Returns {emitted name: [source concepts]} for the colliding names only.
    """
    by_name = {}
    for qname in concepts:
        by_name.setdefault(edge_class_name(qname), []).append(qname)
    return {name: sorted(qnames) for name, qnames in sorted(by_name.items())
            if len(qnames) > 1}


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
