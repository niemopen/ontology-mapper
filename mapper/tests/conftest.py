"""Shared pytest configuration and markers for OntologyMapper tests."""

import pytest


@pytest.fixture
def native_class_catalog(tmp_path, monkeypatch):
    """A native model, including datatypes with misleading catalog patterns."""
    import gzip
    import json
    uri = "https://example.test/model/"
    cmf = "https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/"
    structures = "https://docs.oasis-open.org/niemopen/ns/model/structures/6.0/"

    def namespace(prefix, value):
        return (f'<Namespace structures:id="{prefix}"><NamespaceURI>{value}</NamespaceURI>'
                f'<NamespacePrefixText>{prefix}</NamespacePrefixText></Namespace>')

    def ref(kind, target):
        return f'<{kind} structures:ref="{target}" xsi:nil="true"/>'

    def component(kind, prefix, name, detail=""):
        return (f'<{kind} structures:id="{prefix}.{name}"><Name>{name}</Name>'
                + ref("Namespace", prefix) + detail + f'</{kind}>')
    kinds = {"Record": "Class", "ActualSimpleType": "Class",
             "Literal": "Class", "InheritedLiteral": "Class",
             "Restricted": "Restriction", "Values": "List",
             "Choice": "Union", "Primitive": "Datatype"}
    body = namespace("native", uri) + namespace("xs", "http://www.w3.org/2001/XMLSchema")
    # A reference class whose namespace the catalog does not bind: a real
    # class, but one no catalog QName or CMF id can name.
    body += namespace("other", "https://example.test/other/")
    body += component("Class", "other", "Foreign")
    body += component("Datatype", "xs", "string")
    for name, kind in kinds.items():
        detail = {"Restriction": ref("RestrictionBase", "xs.string"),
                  "List": ref("ListItemDatatype", "xs.string"),
                  "Union": ref("UnionMemberDatatype", "xs.string")}.get(kind, "")
        if name == "InheritedLiteral":
            detail = ref("SubClassOf", "native.Literal")
        body += component(kind, "native", name, detail)
    xml = (f'<Model xmlns="{cmf}" xmlns:structures="{structures}" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' + body + '</Model>')
    catalog = {
        "version": "1.0", "namespaces": {"alias": uri},
        "types": [{"qname": f"alias:{name}", "definition": "A catalog definition.",
                   "pattern": "object", "properties": []} for name in kinds],
        "propertyIndex": {"alias": {"properties": [{
            "qualifiedProperty": "alias:value", "name": "value",
            "qualifiedType": "alias:Restricted", "definition": "A coded value."}]}},
    }
    (tmp_path / "example_reference_model_1.0.cmf.gz").write_bytes(gzip.compress(xml.encode()))
    (tmp_path / "example_reference_catalog_1.0.json").write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("OM_SPECS_DIR", str(tmp_path))
    return catalog


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that exercise generated artifacts end-to-end "
        "(e.g. loading TriG into rdflib, parsing Cypher scripts). "
        "Deselect with: pytest -m 'not integration'",
    )
    config.addinivalue_line(
        "markers",
        "docker: marks tests that require Docker (e.g. testcontainers Neo4j). "
        "Deselect with: pytest -m 'not docker'",
    )


@pytest.fixture
def fake_type_retrieval(monkeypatch):
    """Install a deterministic retrieval order without FAISS or the embedding model.

    ``install(ids)`` makes every query see the entries in the given order with
    descending scores. ``query_index`` still applies ``top_k`` and any
    eligibility predicate exactly as it does over a real index.
    """

    class FakeIndex:
        def __init__(self, total):
            self.ntotal = total

        def search(self, vectors, k):
            k = min(k, self.ntotal)
            return ([[1.0 - 0.01 * i for i in range(k)] for _ in vectors],
                    [[i for i in range(k)] for _ in vectors])

    def install(ids):
        metadata = [{"id": identifier, "definition": "", "kind": "type", "metadata": {}}
                    for identifier in ids]
        monkeypatch.setattr("ontology_mapper.vector_index.load_index",
                            lambda name, kind: (FakeIndex(len(ids)), metadata))
        monkeypatch.setattr("ontology_mapper.vector_index.embed_texts",
                            lambda texts, **kwargs: [[0.0] for _ in texts])
        return metadata

    return install
