/**
 * Local authentication stub.
 *
 * This application runs with a single fixed local user and no external
 * authentication provider. Every session is the same "demo-user" in the
 * "demo" organization with admin rights, and getToken() returns a fixed
 * string the backend recognizes (the backend also runs without auth).
 *
 * Intended for internal / reviewer / single-tenant deployments only.
 * There is NO access control — do not expose this deployment publicly.
 */

const LOCAL_USER = {
  id: "demo-user",
  firstName: "Demo",
  username: "demo",
  organizationMemberships: [],
};
const LOCAL_ORG = { slug: "demo", name: "Demo Organization" };

/** @type {Set<(user: any) => void>} */
const listeners = new Set();

let _currentUser = null;

/** Initialize local auth. Call once at app startup. */
export function initAuth() {
  _currentUser = LOCAL_USER;
}

/** Subscribe to auth state changes. Returns unsubscribe function. */
export function onAuthChange(fn) {
  listeners.add(fn);
  fn(_currentUser); // immediate call with current state
  return () => listeners.delete(fn);
}

/** Get current user or null. */
export function getCurrentUser() {
  return _currentUser;
}

/** Get the active organization slug. */
export function getOrgSlug() {
  return LOCAL_ORG.slug;
}

/** Get the active organization name. */
export function getOrgName() {
  return LOCAL_ORG.name;
}

/** Get session token for API calls. Backend accepts this fixed token. */
export async function getToken() {
  return "demo";
}
