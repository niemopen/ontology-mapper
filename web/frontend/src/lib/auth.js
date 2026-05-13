/**
 * Clerk authentication wrapper.
 *
 * Initializes Clerk, exposes reactive auth state, and provides
 * getToken() for authenticated API calls.
 *
 * Demo mode (VITE_DEMO_MODE=1): bypasses Clerk entirely. Call
 * initDemoAuth() instead of initAuth(); the user is hardcoded as
 * "demo-user" in the "demo" org and getToken() returns a fixed string.
 * The backend recognizes the same bypass when DEMO_MODE=1 is set there.
 */
import { Clerk } from "@clerk/clerk-js";

/** @type {Clerk | null} */
let clerk = null;
let _demoMode = false;

const DEMO_USER = {
  id: "demo-user",
  firstName: "Demo",
  username: "demo",
  organizationMemberships: [],
};
const DEMO_ORG = { slug: "demo", name: "Demo Organization" };

/** @type {Set<(user: any) => void>} */
const listeners = new Set();

let _currentUser = null;
let _lastUserId = null;
let _lastOrgSlug = null;
let _orgPollInterval = null;

/**
 * Initialize Clerk. Call once at app startup.
 * @param {string} publishableKey - Clerk publishable key
 */
export async function initAuth(publishableKey) {
  clerk = new Clerk(publishableKey);
  await clerk.load();
  _currentUser = clerk.user || null;

  // Auto-activate the user's only org if none is active
  if (_currentUser && !clerk.organization) {
    const memberships = _currentUser.organizationMemberships || [];
    if (memberships.length === 1) {
      await clerk.setActive({ organization: memberships[0].organization.id });
    }
  }

  _lastUserId = _currentUser?.id || null;
  _lastOrgSlug = clerk.organization?.slug || null;

  // Poll for org changes (OrgSwitcher updates clerk.organization directly).
  // Clerk's addListener fires too aggressively, so we poll instead.
  _orgPollInterval = setInterval(() => {
    const userId = clerk.user?.id || null;
    const orgSlug = clerk.organization?.slug || null;
    if (userId !== _lastUserId || orgSlug !== _lastOrgSlug) {
      _lastUserId = userId;
      _lastOrgSlug = orgSlug;
      _currentUser = clerk.user || null;
      for (const fn of listeners) fn(_currentUser);
    }
  }, 2000);
}

/**
 * Initialize demo-mode auth (no Clerk). Call once at app startup when
 * VITE_DEMO_MODE is set. Backend must also have DEMO_MODE=1.
 */
export function initDemoAuth() {
  _demoMode = true;
  _currentUser = DEMO_USER;
  _lastUserId = DEMO_USER.id;
  _lastOrgSlug = DEMO_ORG.slug;
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

/** Get the active organization slug (if the user belongs to one). */
export function getOrgSlug() {
  if (_demoMode) return DEMO_ORG.slug;
  if (!clerk?.organization) return null;
  return clerk.organization.slug || null;
}

/** Get the active organization name. */
export function getOrgName() {
  if (_demoMode) return DEMO_ORG.name;
  if (!clerk?.organization) return null;
  return clerk.organization.name || null;
}

/** Get session token for API calls. Returns empty string if not signed in. */
export async function getToken() {
  if (_demoMode) return "demo";
  if (!clerk?.session) return "";
  const token = await clerk.session.getToken();
  return token || "";
}

/** Mount Clerk sign-in UI into a DOM element. */
export function mountSignIn(element) {
  if (_demoMode || !clerk) return;
  clerk.mountSignIn(element, {
    appearance: {
      elements: {
        rootBox: "mx-auto",
        card: "shadow-lg rounded-xl",
      },
    },
  });
}

/** Unmount Clerk sign-in UI. */
export function unmountSignIn(element) {
  if (_demoMode || !clerk) return;
  clerk.unmountSignIn(element);
}

/** Mount Clerk user button into a DOM element. */
export function mountUserButton(element) {
  if (_demoMode || !clerk) return;
  clerk.mountUserButton(element, {
    appearance: {
      elements: {
        avatarBox: "w-8 h-8",
      },
    },
  });
}

/** Mount Clerk organization switcher into a DOM element. */
export function mountOrgSwitcher(element) {
  if (_demoMode || !clerk) return;
  clerk.mountOrganizationSwitcher(element, {
    appearance: {
      elements: {
        rootBox: "inline-flex",
        organizationSwitcherTrigger: "text-sm text-slate-700 hover:text-slate-900",
      },
    },
    hidePersonal: true,
    afterSelectOrganizationUrl: "/",
  });
}

/** Unmount Clerk organization switcher. */
export function unmountOrgSwitcher(element) {
  if (_demoMode || !clerk) return;
  clerk.unmountOrganizationSwitcher(element);
}

/** Sign out. No-op in demo mode. */
export async function signOut() {
  if (_demoMode || !clerk) return;
  await clerk.signOut();
}
