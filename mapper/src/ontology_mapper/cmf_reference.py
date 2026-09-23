"""Complete generated CMF with an offline reference model's native declarations.

Import raw XML: the smaller generation dataclasses do not model every CMF
datatype or metadata field. Component identity is namespace URI plus name;
prefixes and structures:id values are document-local identifiers.
"""

from collections import deque
from copy import deepcopy
from functools import lru_cache
import gzip
import os
from pathlib import Path
import sys

from lxml import etree

from ontology_mapper.run_dir_utils import resolve_specs_dir

_XSD_URI = "http://www.w3.org/2001/XMLSchema"
_XSI_URI = "http://www.w3.org/2001/XMLSchema-instance"
# W3C predefined simple types can be declared without a target reference model.
_XSD_TYPES = frozenset("""
    anySimpleType anyAtomicType string boolean decimal float double duration
    dateTime time date gYearMonth gYear gMonthDay gDay gMonth hexBinary base64Binary
    anyURI QName NOTATION normalizedString token language NMTOKEN NMTOKENS Name
    NCName ID IDREF IDREFS ENTITY ENTITIES integer nonPositiveInteger negativeInteger
    long int short byte nonNegativeInteger unsignedLong unsignedInt unsignedShort
    unsignedByte positiveInteger dateTimeStamp dayTimeDuration yearMonthDuration error
""".split())


def _reference_cmf_path(target_ontology: str, target_version: str) -> Path:
    """The configured reference's path, contained in the specs directory."""
    root = resolve_specs_dir().resolve()
    path = root / f"{target_ontology}_reference_model_{target_version}.cmf.gz"

    def inside(candidate):
        root_parts, parts = root.parts, candidate.parts
        if sys.platform in {"win32", "darwin"}:
            root_parts = tuple(p.casefold() for p in root_parts)
            parts = tuple(p.casefold() for p in parts)
        return parts[:len(root_parts)] == root_parts

    if not inside(Path(os.path.abspath(path))) or not inside(path.resolve()):
        raise ValueError("CMF reference path escapes the configured specs directory")
    return path


def reference_cmf_installed(target_ontology: str, target_version: str) -> bool:
    """Whether a package for this target carries CMF.

    The one home for that question: Stage 6 writes CMF, the package
    scaffold and README list it, and Stage 7 requires it exactly when this
    is true. A generated CMF references the target's classes and
    properties, and only a reference model declares them; the JSON search
    catalogs record property types but not the datatypes CMF requires, so
    a CMF for a target without one (NODS, SALI-FOLIO) could never validate.
    """
    return _reference_cmf_path(target_ontology, target_version).is_file()


CMF_OMITTED_REASON = ("No CMF reference model was installed for this target when this "
                      "package was generated, so a CMF could not declare the target "
                      "classes and properties it references.")


def load_reference_cmf(target_ontology: str, target_version: str):
    """Read the configured reference, if installed; never fetch during a run.

    Cached: the class policy asks about one target at a time — per matrix
    entry at review exit, per concept during collection — and this is a
    2 MB gzip that expands to 24 MB. Reading it per call made a 50-entry
    matrix check take ~6 seconds, and the three web review routes pay it
    inside the request. The file ships inside the installed package and
    does not change while a process runs.
    """
    path = _reference_cmf_path(target_ontology, target_version)
    try:
        return _read_reference_cmf(str(path), path.stat().st_mtime_ns)
    except OSError:
        # Absent, or removed between the check and the read: the
        # contract is "None when not installed", not a traceback.
        return None


@lru_cache(maxsize=2)
def _read_reference_cmf(path: str, mtime_ns: int):
    """The decompressed reference, cached by file identity.

    Keyed by the resolved path and its mtime, never by ontology name: the
    specs directory is resolved per call, so a cache on the name would
    answer for a directory the caller is no longer pointing at and would
    skip the containment check its caller performs.
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return stream.read()


class _CmfIndex:
    def __init__(self, root):
        self.root = root
        self.ns = etree.QName(root).namespace
        self.structures = root.nsmap["structures"]
        self.id_attr = f"{{{self.structures}}}id"
        self.ref_attr = f"{{{self.structures}}}ref"
        declarations = [e for e in root if e.get(self.id_attr)]
        self.by_id = {e.get(self.id_attr): e for e in declarations}
        self.namespaces = {
            sid: e.findtext(f"{{{self.ns}}}NamespaceURI")
            for sid, e in self.by_id.items() if etree.QName(e).localname == "Namespace"
        }
        self.by_identity = {}
        for element in declarations:
            identity = self.identity(element)
            previous = self.by_identity.get(identity)
            if (len(identity) == 2 and previous is not None
                    and self.signature(previous) != self.signature(element)):
                raise ValueError(f"Conflicting CMF declarations for {identity[0]} {identity[1]}")
            self.by_identity[identity] = element

    def identity(self, element):
        if etree.QName(element).localname == "Namespace":
            return (element.findtext(f"{{{self.ns}}}NamespaceURI"),)
        ns_ref = element.find(f"{{{self.ns}}}Namespace").get(self.ref_attr)
        return (self.namespaces[ns_ref], element.findtext(f"{{{self.ns}}}Name"))

    def reference_identity(self, sid):
        if sid in self.by_id:
            return self.identity(self.by_id[sid])
        namespaces = {"xs": _XSD_URI, **self.namespaces}
        if sid in namespaces:
            return (namespaces[sid],)
        for prefix in sorted(namespaces, key=len, reverse=True):
            if sid.startswith(prefix + "."):
                return (namespaces[prefix], sid[len(prefix) + 1:])
        return None

    def signature(self, element):
        """Compare native declarations without treating prefix aliases as changes."""
        attributes = []
        for key, value in element.attrib.items():
            if key in {self.id_attr, f"{{{_XSI_URI}}}nil"}:
                continue
            if key == self.ref_attr:
                key, value = "reference", self.reference_identity(value) or value
            attributes.append((key, value))
        return (etree.QName(element).localname, tuple(sorted(attributes)),
                (element.text or "").strip(),
                tuple(self.signature(child) for child in element if isinstance(child.tag, str)))


@lru_cache(maxsize=1)
def reference_class_identities(xml: str):
    """Native Class identities, including literal and inherited Classes.

    Cache the immutable answer by content so a changed reference is reread.
    Datatypes and XSD-only names are not Class declarations.
    """
    index = _CmfIndex(etree.fromstring(xml.encode("utf-8"),
                                     etree.XMLParser(resolve_entities=False)))
    return frozenset(identity for identity, element in index.by_identity.items()
                     if etree.QName(element).localname == "Class")


def _builtin_model(root):
    """CMF represents a predefined XSD type by its name and XSD namespace."""
    result = etree.Element(root.tag, nsmap=root.nsmap)
    cmf = etree.QName(root).namespace
    structures = root.nsmap["structures"]
    ns = etree.SubElement(result, f"{{{cmf}}}Namespace", {f"{{{structures}}}id": "xs"})
    for name, value in (("NamespaceURI", _XSD_URI), ("NamespacePrefixText", "xs"),
                        ("NamespaceCategoryCode", "XSD")):
        etree.SubElement(ns, f"{{{cmf}}}{name}").text = value
    for name in sorted(_XSD_TYPES):
        element = etree.SubElement(result, f"{{{cmf}}}Datatype", {f"{{{structures}}}id": f"xs.{name}"})
        etree.SubElement(element, f"{{{cmf}}}Name").text = name
        etree.SubElement(element, f"{{{cmf}}}Namespace", {
            f"{{{structures}}}ref": "xs", f"{{{_XSI_URI}}}nil": "true"})
    return _CmfIndex(result)


def complete_cmf_references(xml: str, reference_xml=None, *, implicit_roots=()) -> str:
    """Add transitive native definitions, preserving local identities and metadata.

    Missing target definitions remain unresolved for Stage 7 to report. A local
    declaration conflicting with a known target identity is a generation error.
    Property reference tags follow the referenced native property's kind; class
    versus datatype choices remain mapping decisions and are not reinterpreted.
    """
    def parse(content):
        return _CmfIndex(etree.fromstring(content.encode("utf-8"),
                                         etree.XMLParser(resolve_entities=False)))

    local = parse(xml)
    native = parse(reference_xml) if reference_xml is not None else None
    builtins = _builtin_model(local.root)
    references = [doc for doc in (native, builtins) if doc is not None]
    selected = {}  # expanded identity -> (origin document, declaration)
    extra_augmentations = {}

    def authoritative(identity):
        return next(((doc, doc.by_identity[identity]) for doc in references
                     if identity in doc.by_identity), None)

    for identity, element in local.by_identity.items():
        existing = authoritative(identity)
        if existing:
            origin, declaration = existing
            if len(identity) == 1:
                extra_augmentations[identity] = element.findall(f"{{{local.ns}}}AugmentationRecord")
            elif local.signature(element) != origin.signature(declaration):
                raise ValueError(f"Conflicting local CMF declaration for {identity[0]} {identity[1]}")
        selected[identity] = existing or (local, element)

    queue = deque(selected)
    while queue:
        identity = queue.popleft()
        origin, element = selected[identity]
        fragments = [(origin, element)] + [(local, e) for e in extra_augmentations.get(identity, [])]
        for doc, fragment in fragments:
            for child in fragment.iter():
                sid = child.get(doc.ref_attr)
                if sid is None:
                    continue
                target = doc.reference_identity(sid)
                if etree.QName(child).localname == "SubClassOf" and target in implicit_roots:
                    continue
                definition = authoritative(target)
                if target not in selected and definition:
                    selected[target] = definition
                    queue.append(target)

    # Keep every local ID; assign imported IDs using the retained namespace alias.
    output_ids = {identity: e.get(local.id_attr) for identity, e in local.by_identity.items()}
    used_ids = set(local.by_id)

    def allocate(identity, candidate):
        name, suffix = candidate, 2
        while name in used_ids:
            name, suffix = f"{candidate}_{suffix}", suffix + 1
        output_ids[identity] = name
        used_ids.add(name)

    for identity, (doc, element) in selected.items():
        if len(identity) == 1 and identity not in output_ids:
            allocate(identity, element.get(doc.id_attr))
    for identity in selected:
        if identity not in output_ids:
            allocate(identity, f"{output_ids[(identity[0],)]}.{identity[1]}")

    def rewrite(doc, element):
        copy = deepcopy(element)
        for child in list(copy.iter()):
            sid = child.get(doc.ref_attr)
            if sid is not None:
                target = doc.reference_identity(sid)
                kind = etree.QName(child).localname
                if kind == "SubClassOf" and target in implicit_roots:
                    child.getparent().remove(child)
                    continue
                if target in output_ids:
                    child.set(doc.ref_attr, output_ids[target])
                    target_kind = etree.QName(selected[target][1]).localname
                    if kind in {"ObjectProperty", "DataProperty"} and target_kind in {"ObjectProperty", "DataProperty"}:
                        child.tag = f"{{{local.ns}}}{target_kind}"
            for key, value in list(child.attrib.items()):
                if etree.QName(key).namespace == doc.structures and doc.structures != local.structures:
                    del child.attrib[key]
                    child.set(f"{{{local.structures}}}{etree.QName(key).localname}", value)
        return copy

    result = etree.Element(local.root.tag, attrib=local.root.attrib, nsmap=local.root.nsmap)
    # The CMF schema requires namespace declarations before components.
    for identity in sorted(selected, key=lambda key: len(key)):
        doc, element = selected[identity]
        copy = rewrite(doc, element)
        copy.set(local.id_attr, output_ids[identity])
        if len(identity) == 1:
            copy.find(f"{{{local.ns}}}NamespacePrefixText").text = output_ids[identity]
            for augmentation in extra_augmentations.get(identity, []):
                # AugmentationRecord precedes LocalTerm in NamespaceType.
                terms = copy.findall(f"{{{local.ns}}}LocalTerm")
                offset = copy.index(terms[0]) if terms else len(copy)
                copy.insert(offset, rewrite(local, augmentation))
        result.append(copy)
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True, pretty_print=True).decode("utf-8")
