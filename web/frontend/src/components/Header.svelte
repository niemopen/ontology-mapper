<script>
  import { getOrgName, getCurrentUser } from "../lib/auth.js";
  import { page, navigateTo, goToDashboard, pendingRequestCount, isAdmin } from "../lib/stores.js";

  const orgName = getOrgName();
  const user = getCurrentUser();
  const userLabel = user?.firstName || user?.username || "User";
</script>

<header class="bg-white border-b border-slate-200 sticky top-0 z-40">
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
    <div class="flex items-center justify-between h-14">
      <div class="flex items-center gap-4">
        <button
          class="flex items-center gap-2 hover:opacity-80 transition-opacity"
          on:click={goToDashboard}
        >
          <div class="w-8 h-8 bg-indigo-600 rounded-md flex items-center justify-center">
            <span class="text-white font-bold text-sm">OM</span>
          </div>
          <span class="font-semibold text-slate-900">OntologyMapper</span>
        </button>
        {#if orgName}
          <div class="h-6 w-px bg-slate-200"></div>
          <span class="text-sm text-slate-700">{orgName}</span>
        {/if}
      </div>

      <nav class="flex items-center gap-4">
        {#if $page !== "dashboard"}
          <button
            class="text-sm text-slate-500 hover:text-slate-700 transition-colors"
            on:click={goToDashboard}
          >
            Dashboard
          </button>
        {/if}
        {#if $isAdmin}
          <button
            class="relative text-slate-500 hover:text-slate-700 transition-colors"
            on:click={() => navigateTo("admin-requests")}
            title="Ontology requests"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
            </svg>
            {#if $pendingRequestCount > 0}
              <span class="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                {$pendingRequestCount}
              </span>
            {/if}
          </button>
        {/if}
        <span class="text-sm text-slate-600">{userLabel}</span>
      </nav>
    </div>
  </div>
</header>
