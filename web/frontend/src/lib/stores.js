/**
 * Svelte stores for global application state.
 */
import { writable, derived } from "svelte/store";

/** Current page: "login" | "dashboard" | "new-project" | "review" | "results" */
export const page = writable("login");

/** Current run ID (when viewing a specific run). */
export const currentRunId = writable(null);

/** Current auth user object, or null. */
export const currentUser = writable(null);

/** Active organization slug, or null. */
export const currentOrg = writable(null);

/** Review state for the current run. */
export const reviewState = writable(null);

/** Global error message (auto-clears). */
export const errorMessage = writable(null);

/** Global loading flag. */
export const loading = writable(false);

/** Pending ontology request count (admin only). */
export const pendingRequestCount = writable(0);

/** Whether the current user is an admin. */
export const isAdmin = writable(false);

// --- Navigation helpers ---

let _skipPush = false;

function _pushState(pageName, runId) {
  if (_skipPush) return;
  const state = { page: pageName, runId: runId || null };
  const url = runId ? `/${pageName}/${runId}` : `/${pageName}`;
  history.pushState(state, "", url);
}

export function navigateTo(pageName, params = {}) {
  if (params.runId) currentRunId.set(params.runId);
  page.set(pageName);
  _pushState(pageName, params.runId);
}

export function goToReview(runId) {
  navigateTo("review", { runId });
}

export function goToResults(runId) {
  navigateTo("results", { runId });
}

export function goToDashboard() {
  currentRunId.set(null);
  reviewState.set(null);
  page.set("dashboard");
  _pushState("dashboard", null);
}

const _validPages = new Set(["dashboard", "new-project", "review", "results", "admin-requests"]);

/** Parse the current URL path into { page, runId }. */
function _parseUrl() {
  const path = window.location.pathname.replace(/^\/+|\/+$/g, "");
  if (!path) return { page: "dashboard", runId: null };
  const parts = path.split("/");
  const pageName = parts[0];
  if (!_validPages.has(pageName)) return { page: "dashboard", runId: null };
  return { page: pageName, runId: parts[1] || null };
}

/** Call once from App.svelte onMount to enable back/forward and URL-based navigation. */
export function initHistory() {
  window.addEventListener("popstate", (e) => {
    const state = e.state || _parseUrl();
    _skipPush = true;
    if (state.runId) currentRunId.set(state.runId);
    else currentRunId.set(null);
    page.set(state.page || "dashboard");
    _skipPush = false;
  });
  // Restore route from URL on initial load
  const initial = _parseUrl();
  if (initial.runId) currentRunId.set(initial.runId);
  page.set(initial.page);
  history.replaceState(initial, "", window.location.pathname);
}

// --- Error helper ---

let _errorTimeout;
export function showError(msg) {
  errorMessage.set(msg);
  clearTimeout(_errorTimeout);
  _errorTimeout = setTimeout(() => errorMessage.set(null), 8000);
}
