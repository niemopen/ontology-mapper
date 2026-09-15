# Offline CMF reference models

Stage 6 reads `{target}_reference_model_{version}.cmf.gz` from the specification
directory (`OM_SPECS_DIR`, or this directory). These are native definitions for
exchange generation; the separate JSON search catalogs are not complete models.
Only referenced components and their transitive dependencies are imported.
Missing definitions remain unresolved and fail the existing Stage 7 CMF check.
No network service or Java installation is needed during a pipeline run.

## NIEM 6.0

`niem_reference_model_6.0.cmf.gz` is derived from the
[OASIS NIEM Open model, tag 6.0-ps02](https://github.com/niemopen/niem-model/tree/6.0-ps02),
the schema release used by the bundled search catalog. Copyright belongs to its
contributors. The data is licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/);
see the [upstream license and notices](https://github.com/niemopen/niem-model/blob/6.0-ps02/LICENSE.md).
This repository's Apache software license does not replace the data license.

Modification: converted the release's `xsd/niem-core.xsd` and `xsd/domains/*.xsd`
(excluding `mo.xsd` and `mo-usmtf.xsd`, as in the search catalog) using
[CMFTool 1.0](https://github.com/niemopen/cmftool), then compressed the resulting
XML with Python `gzip.compress(content, mtime=0)`. CMFTool follows schema imports
to include required code and external namespaces. The model contains 51
namespaces, 1,673 classes, 11,010 properties and 1,248 datatype declarations.

To reproduce, pass those schema paths as separate arguments:

```text
cmftool x2m -o niem-reference-6.0.cmf xsd/niem-core.xsd <selected domain XSD paths>
```

SHA-256 of the uncompressed CMF:
`7ce82a8041c1f28f1a07b3fcbd16b695721c9c345b946c5ada67ff5c425cbd5f`.

The converted CMF passes the bundled CMF XSD and has no unbound references.
NIEM `structures:ObjectType` is implicit in native CMF; its policy is owned by
`ontology_specific.cmf_implicit_roots`, not an invented reference declaration.
