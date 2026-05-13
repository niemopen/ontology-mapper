<script>
  import { onMount } from "svelte";
  import { initAuth, initDemoAuth, onAuthChange, getOrgSlug } from "./lib/auth.js";
  import { getOntologyRequestCount } from "./lib/api.js";
  import { page, currentUser, currentOrg, errorMessage, pendingRequestCount, isAdmin, initHistory } from "./lib/stores.js";
  import Header from "./components/Header.svelte";
  import Login from "./pages/Login.svelte";
  import Dashboard from "./pages/Dashboard.svelte";
  import NewProject from "./pages/NewProject.svelte";
  import Review from "./pages/Review.svelte";
  import Results from "./pages/Results.svelte";
  import AdminRequests from "./pages/AdminRequests.svelte";

  let authReady = false;
  let authError = null;

  // Demo mode defaults ON when VITE_DEMO_MODE is unset, so a fresh
  // checkout runs without Clerk configuration. Set VITE_DEMO_MODE=0 to
  // require Clerk auth.
  const _demoEnv = import.meta.env.VITE_DEMO_MODE;
  const DEMO_MODE =
    _demoEnv === undefined
      ? true
      : ["1", "true", "yes", "on"].includes(_demoEnv.toString().toLowerCase());

  onMount(async () => {
    if (DEMO_MODE) {
      initDemoAuth();
      initHistory();
      onAuthChange((user) => {
        currentUser.set(user);
        currentOrg.set(getOrgSlug());
        getOntologyRequestCount()
          .then((rc) => {
            pendingRequestCount.set(rc.count);
            isAdmin.set(rc.is_admin);
          })
          .catch(() => {});
        if ($page === "login") page.set("dashboard");
      });
      authReady = true;
      return;
    }
    // The publishable key is injected at build time or fetched from backend
    // For now, read from a meta tag or hardcode for dev
    const key = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || "";
    if (!key) {
      authError = "Missing VITE_CLERK_PUBLISHABLE_KEY in frontend/.env (or set VITE_DEMO_MODE=1)";
      authReady = true;
      return;
    }
    try {
      await initAuth(key);
      initHistory();
      let adminChecked = false;
      onAuthChange((user) => {
        currentUser.set(user);
        currentOrg.set(getOrgSlug());
        if (user) {
          if (!adminChecked) {
            adminChecked = true;
            getOntologyRequestCount()
              .then((rc) => {
                pendingRequestCount.set(rc.count);
                isAdmin.set(rc.is_admin);
              })
              .catch(() => {});
          }
          if ($page === "login") page.set("dashboard");
        } else {
          adminChecked = false;
          page.set("login");
        }
      });
      authReady = true;
    } catch (e) {
      authError = `Auth init failed: ${e.message}`;
      authReady = true;
    }
  });
</script>

{#if !authReady}
  <div class="flex items-center justify-center min-h-screen">
    <div class="text-slate-400 text-lg">Loading...</div>
  </div>
{:else if authError}
  <div class="flex items-center justify-center min-h-screen">
    <div class="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md">
      <h2 class="text-red-800 font-semibold mb-2">Configuration Error</h2>
      <p class="text-red-600 text-sm">{authError}</p>
      <p class="text-slate-500 text-xs mt-3">
        Create a <code class="bg-slate-100 px-1 rounded">frontend/.env</code> file with:<br />
        <code class="bg-slate-100 px-1 rounded text-xs">VITE_CLERK_PUBLISHABLE_KEY=pk_test_...</code>
      </p>
    </div>
  </div>
{:else}
  {#if $currentUser}
    <Header />
  {/if}

  {#if $errorMessage}
    <div class="fixed top-4 right-4 z-50 bg-red-50 border border-red-300 text-red-800 px-4 py-3 rounded-lg shadow-lg max-w-md">
      <p class="text-sm">{$errorMessage}</p>
    </div>
  {/if}

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
    {#if $page === "login"}
      <Login />
    {:else if $page === "dashboard"}
      <Dashboard />
    {:else if $page === "new-project"}
      <NewProject />
    {:else if $page === "review"}
      <Review />
    {:else if $page === "results"}
      <Results />
    {:else if $page === "admin-requests"}
      <AdminRequests />
    {/if}
  </main>
{/if}
