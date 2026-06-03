# Stage 6: Generate

Three sub-stages that produce the edge package.

---

## Stage 6a: Generate OWL/TTL

**Artifacts** (in `edge-package/`): `ontology/{source}-edge-*.ttl` (4 files), `cmf/{source}-model.cmf`, `cmf/{source}-model.cmf.json`

```
Action:  om-pipeline rerun --stage 6 --run-dir {run_dir}
         -> Bootstraps edge-package directory structure (creates subdirs).
         -> Does NOT run generation — only creates the output directory layout.

Action:  om-generate-ontology --run-dir {run_dir}
         -> Generates 4 TTL files + 2 CMF files in edge-package/

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 6a
```

---

## Stage 6b: Package Non-OWL Artifacts

**Artifacts** (in `edge-package/`): `mappings/`, `extensions/`, `governance/`, `package-manifest.json`, `README.md`

```
Action:  om-package-artifacts --run-dir {run_dir}

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 6b
```

---

## Stage 6c: Generate KG Artifacts

**Artifacts** (in `edge-package/`): `kg/neo4j/`, `kg/rdf/`, `kg/import/`

```
Action:  om-generate-kg --run-dir {run_dir}

Verify:  python runner_tools/verify_stage_outputs.py --run-dir {run_dir} --stage 6c

Action:  om-pipeline mark-complete --stage 6 --run-dir {run_dir}
```
