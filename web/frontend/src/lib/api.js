/**
 * API client.
 *
 * All calls include the Authorization header automatically (a fixed local
 * token; the backend runs without external authentication).
 */
import { getToken } from "./auth.js";

const BASE = "/api";

/**
 * Make an authenticated API call.
 * @param {string} path - API path (e.g., "/runs")
 * @param {RequestInit} options - Fetch options
 * @returns {Promise<any>} Parsed JSON response
 */
async function fetchAPI(path, options = {}, _retry = true) {
  const token = await getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(`${BASE}${path}`, { ...options, headers });

  // Retry once on a transient 401
  if (res.status === 401 && _retry) {
    await new Promise((r) => setTimeout(r, 500));
    return fetchAPI(path, options, false);
  }

  if (!res.ok) {
    const text = await res.text();
    let detail;
    try {
      const body = JSON.parse(text);
      detail = body.detail || text;
    } catch {
      detail = text;
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return res.json();
}

// --- Runs ---

export function listRuns() {
  return fetchAPI("/runs");
}

export function getRun(runId) {
  return fetchAPI(`/runs/${runId}`);
}

export function createRun(data) {
  return fetchAPI("/runs", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deleteRun(runId) {
  return fetchAPI(`/runs/${runId}`, { method: "DELETE" });
}

export function executePipeline(runId) {
  return fetchAPI(`/runs/${runId}/execute`, { method: "POST" });
}

export function getRunStatus(runId) {
  return fetchAPI(`/runs/${runId}/status`);
}

export function continuePipeline(runId) {
  return fetchAPI(`/runs/${runId}/continue`, { method: "POST" });
}

export function getOntologies() {
  return fetchAPI("/ontologies");
}

export async function uploadFiles(source, files) {
  const token = await getToken();
  const formData = new FormData();
  formData.append("source", source);
  for (const file of files) {
    formData.append("files", file);
  }
  const res = await fetch(`${BASE}/sources/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function listSources() {
  return fetchAPI("/sources");
}

// --- Review ---

export function getReviewState(runId) {
  return fetchAPI(`/runs/${runId}/review`);
}

export function getConceptDetail(runId, concept) {
  return fetchAPI(`/runs/${runId}/review/${encodeURIComponent(concept)}`);
}

export function approveConcept(runId, concept, confidence = "confident") {
  return fetchAPI(`/runs/${runId}/review/approve`, {
    method: "POST",
    body: JSON.stringify({ concept, confidence }),
  });
}

export function approveAll(runId) {
  return fetchAPI(`/runs/${runId}/review/approve-all`, { method: "POST" });
}

export function changeTarget(runId, concept, newTargetType) {
  return fetchAPI(`/runs/${runId}/review/change-target`, {
    method: "POST",
    body: JSON.stringify({ concept, new_target_type: newTargetType }),
  });
}

export function resolveProperty(runId, concept, sourceProperty, propertyAction, targetProperty, confidence = "confident") {
  return fetchAPI(`/runs/${runId}/review/resolve-property`, {
    method: "POST",
    body: JSON.stringify({
      concept,
      source_property: sourceProperty,
      property_action: propertyAction,
      target_property: targetProperty || null,
      confidence,
    }),
  });
}

export function getValidation(runId) {
  return fetchAPI(`/runs/${runId}/review/validation`);
}

export function submitReview(runId) {
  return fetchAPI(`/runs/${runId}/review/submit`, { method: "POST" });
}

export function resetReview(runId) {
  return fetchAPI(`/runs/${runId}/review/reset`, { method: "POST" });
}

// --- Catalog Search ---

export function searchCatalog(runId, query, kind = "both", maxResults = 20) {
  const params = new URLSearchParams({
    run_id: runId,
    q: query,
    kind,
    max_results: String(maxResults),
  });
  return fetchAPI(`/catalog/search?${params}`);
}

// --- Results ---

export function getResults(runId) {
  return fetchAPI(`/runs/${runId}/results`);
}

export function downloadUrl(runId) {
  return `${BASE}/runs/${runId}/download`;
}

export function fileUrl(runId, filePath) {
  return `${BASE}/runs/${runId}/file/${filePath}`;
}

// --- Ontology Requests ---

export function createOntologyRequest(data) {
  return fetchAPI("/ontology-requests", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function listOntologyRequests() {
  return fetchAPI("/ontology-requests");
}

export function getOntologyRequestCount() {
  return fetchAPI("/ontology-requests/pending-count");
}

export function completeOntologyRequest(requestId) {
  return fetchAPI(`/ontology-requests/${requestId}/complete`, { method: "POST" });
}
