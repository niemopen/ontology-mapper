<script>
  import { onMount } from "svelte";
  import { initAuth, onAuthChange, getOrgSlug } from "./lib/auth.js";
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

  // This app runs with a single fixed local user (no external auth).
  onMount(() => {
    initAuth();
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
  });
</script>

{#if !authReady}
  <div class="flex items-center justify-center min-h-screen">
    <div class="text-slate-400 text-lg">Loading...</div>
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
