/**
 * Pipeline stage metadata — static map.
 *
 * Authoritative source: AGENTS/Pipeline__STAGE_{1..8}.md in the Runner repo.
 * If stage titles or purposes change there, update this file to match.
 */

export const STAGES = {
  1: {
    title: "Ingest",
    description:
      "Validates the input package, scans files, and writes the source inventory.",
  },
  2: {
    title: "Extract",
    description:
      "Extracts concepts, properties, and relationships from the source ontology into a concept inventory.",
  },
  3: {
    title: "Semantic Alignment",
    description:
      "Searches the target ontology for semantic matches and evaluates each candidate via LLM reasoning.",
  },
  4: {
    title: "Build Mapping Matrix",
    description:
      "Reshapes alignments into the mapping matrix with actions, scaffolding, and a generation audit.",
  },
  5: {
    title: "Review",
    description:
      "Interactive human review of all mappings — approve, change targets, or resolve undecided properties.",
  },
  6: {
    title: "Generate",
    description:
      "Produces the edge ontology (OWL/TTL), CMF model, knowledge graph artifacts, and packages them.",
  },
  7: {
    title: "Validate",
    description:
      "Runs cross-artifact validation checks (syntax, conformance, consistency) and generates a feedback report.",
  },
  8: {
    title: "Finalize",
    description:
      "Writes governance artifacts (lineage, versioning, validation summary) and marks the pipeline complete.",
  },
};

export function stageTitle(stage) {
  return STAGES[stage]?.title || `Stage ${stage}`;
}

export function stageDescription(stage) {
  return STAGES[stage]?.description || "";
}
