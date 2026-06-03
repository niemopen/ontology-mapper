<script>
  import { onMount } from "svelte";
  import { listOntologyRequests, completeOntologyRequest } from "../lib/api.js";
  import { goToDashboard, showError, loading, pendingRequestCount } from "../lib/stores.js";

  let requests = [];
  let filter = "pending"; // "pending" | "completed" | "all"

  onMount(() => loadRequests());

  async function loadRequests() {
    loading.set(true);
    try {
      requests = await listOntologyRequests();
    } catch (e) {
      showError(`Failed to load requests: ${e.message}`);
    } finally {
      loading.set(false);
    }
  }

  $: filtered = requests.filter((r) => {
    if (filter === "all") return true;
    return r.status === filter;
  });

  $: pendingCount = requests.filter((r) => r.status === "pending").length;

  async function handleComplete(id) {
    try {
      await completeOntologyRequest(id);
      await loadRequests();
      pendingRequestCount.set(pendingCount - 1);
    } catch (e) {
      showError(`Failed to complete request: ${e.message}`);
    }
  }

  function formatDate(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short", day: "numeric", year: "numeric",
    });
  }
</script>

<div>
  <div class="flex items-center gap-3 mb-6">
    <button
      class="text-slate-400 hover:text-slate-600 transition-colors"
      aria-label="Back to dashboard"
      on:click={goToDashboard}
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
      </svg>
    </button>
    <div>
      <h1 class="text-2xl font-bold text-slate-900">Ontology Requests</h1>
      <p class="text-sm text-slate-500">{pendingCount} pending</p>
    </div>
  </div>

  <!-- Filter -->
  <div class="flex items-center gap-1 bg-white border border-slate-200 rounded-lg p-0.5 mb-6 w-fit">
    {#each [["pending", "Pending"], ["completed", "Completed"], ["all", "All"]] as [key, label]}
      <button
        class="px-3 py-1 text-xs font-medium rounded-md transition-colors"
        class:bg-indigo-600={filter === key}
        class:text-white={filter === key}
        class:text-slate-600={filter !== key}
        class:hover:bg-slate-50={filter !== key}
        on:click={() => filter = key}
      >
        {label}
      </button>
    {/each}
  </div>

  {#if $loading && requests.length === 0}
    <div class="text-center py-12 text-slate-400">Loading...</div>
  {:else if filtered.length === 0}
    <div class="text-center py-12 text-slate-400">No {filter === "all" ? "" : filter} requests</div>
  {:else}
    <div class="space-y-3">
      {#each filtered as req (req.id)}
        <div class="bg-white border border-slate-200 rounded-lg p-4"
             class:border-amber-200={req.status === "pending"}
             class:bg-amber-50={req.status === "pending"}>
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-slate-900">{req.name}</span>
                {#if req.version}
                  <span class="text-sm text-slate-500">v{req.version}</span>
                {/if}
                <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                      class:bg-amber-100={req.status === "pending"}
                      class:text-amber-800={req.status === "pending"}
                      class:bg-emerald-100={req.status === "completed"}
                      class:text-emerald-800={req.status === "completed"}>
                  {req.status}
                </span>
              </div>

              <div class="mt-1 text-xs text-slate-500 flex items-center gap-3">
                <span>From: {req.requested_org}</span>
                <span>Requested: {formatDate(req.created_at)}</span>
                {#if req.completed_at}
                  <span>Completed: {formatDate(req.completed_at)}</span>
                {/if}
              </div>

              {#if req.reference_url}
                <div class="mt-2">
                  <a
                    href={req.reference_url}
                    target="_blank"
                    rel="noopener"
                    class="text-sm text-indigo-600 hover:text-indigo-800 break-all"
                  >
                    {req.reference_url}
                  </a>
                </div>
              {/if}

              {#if req.notes}
                <p class="mt-2 text-sm text-slate-600">{req.notes}</p>
              {/if}
            </div>

            {#if req.status === "pending"}
              <button
                class="flex-shrink-0 px-3 py-1.5 text-sm font-medium text-white bg-emerald-600
                       hover:bg-emerald-700 rounded-md transition-colors"
                on:click={() => handleComplete(req.id)}
              >
                Mark Complete
              </button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
