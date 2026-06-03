<script>
  import { onMount } from "svelte";
  import { listRuns, deleteRun } from "../lib/api.js";
  import { navigateTo, goToReview, goToResults, showError, currentOrg } from "../lib/stores.js";
  import { STAGES, stageDescription } from "../lib/stages.js";

  let runs = [];
  let isLoading = false;
  let prevOrg = undefined;
  let confirmDelete = null; // run object pending deletion
  let deleting = false;

  async function handleDelete() {
    if (!confirmDelete) return;
    deleting = true;
    try {
      await deleteRun(confirmDelete.run_id);
      runs = runs.filter((r) => r.run_id !== confirmDelete.run_id);
      confirmDelete = null;
    } catch (e) {
      showError(`Failed to delete run: ${e.message}`);
    } finally {
      deleting = false;
    }
  }

  async function loadRuns() {
    isLoading = true;
    try {
      runs = await listRuns();
    } catch (e) {
      showError(`Failed to load runs: ${e.message}`);
    } finally {
      isLoading = false;
    }
  }

  onMount(() => {
    prevOrg = $currentOrg;
    loadRuns();
  });

  // Reload only when org actually changes
  $: {
    const org = $currentOrg;
    if (prevOrg !== undefined && org !== prevOrg) {
      prevOrg = org;
      loadRuns();
    }
  }

  function stageLabel(stage) {
    const labels = {
      "0": "Initialized",
      "1": "Ingested",
      "2": "Extracted",
      "3": "Reconciled",
      "4": "Ready for Review",
      "5": "Reviewed",
      "6": "Generated",
      "7": "Validated",
      "8": "Finalized",
    };
    return labels[stage] || `Stage ${stage}`;
  }

  function stageColor(stage) {
    const n = parseInt(stage);
    if (n >= 8) return "bg-emerald-100 text-emerald-800";
    if (n >= 5) return "bg-blue-100 text-blue-800";
    if (n >= 4) return "bg-amber-100 text-amber-800";
    return "bg-slate-100 text-slate-600";
  }

  function canReview(run) {
    const stage = parseInt(run.current_stage);
    return stage >= 4 && stage < 6;
  }

  function hasResults(run) {
    return parseInt(run.current_stage) >= 8;
  }
</script>

<div>
  <div class="flex items-center justify-between mb-6">
    <div>
      <h1 class="text-2xl font-bold text-slate-900">Pipeline Runs</h1>
      <p class="text-slate-500 text-sm mt-1">Select a run to review or create a new one</p>
    </div>
    <button
      class="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg
             hover:bg-indigo-700 transition-colors"
      on:click={() => navigateTo("new-project")}
    >
      New Run
    </button>
  </div>

  {#if isLoading}
    <div class="text-center py-12 text-slate-400">Loading runs...</div>
  {:else if runs.length === 0}
    <div class="text-center py-16">
      <div class="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
        <svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
      </div>
      <h3 class="text-lg font-medium text-slate-700">No pipeline runs yet</h3>
      <p class="text-slate-500 text-sm mt-1">Create your first run to get started</p>
      <button
        class="mt-4 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg
               hover:bg-indigo-700 transition-colors"
        on:click={() => navigateTo("new-project")}
      >
        New Run
      </button>
    </div>
  {:else}
    <div class="grid gap-3">
      {#each runs as run (run.run_id)}
        <div class="bg-white border border-slate-200 rounded-lg p-4 hover:border-slate-300 transition-colors">
          <div class="flex items-center justify-between">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-3">
                <h3 class="font-semibold text-slate-900">
                  {run.organization}
                  <span class="text-slate-400 font-normal">/</span>
                  {run.source}
                </h3>
                <span
                  class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {stageColor(run.current_stage)}"
                  title={stageDescription(run.current_stage)}
                >
                  {stageLabel(run.current_stage)}
                </span>
              </div>
              <div class="flex items-center gap-4 mt-1 text-xs text-slate-500">
                <span>Target: <strong>{run.target_ontology} {run.target_version}</strong></span>
                <span>{run.run_id}</span>
              </div>
            </div>

            <div class="flex items-center gap-2">
              {#if hasResults(run)}
                <button
                  class="px-3 py-1.5 text-sm font-medium text-white bg-emerald-600
                         hover:bg-emerald-700 rounded-md transition-colors"
                  on:click={() => goToResults(run.run_id)}
                >
                  Results
                </button>
                <button
                  class="px-3 py-1.5 text-sm font-medium text-slate-600 bg-slate-100
                         hover:bg-slate-200 rounded-md transition-colors"
                  on:click={() => goToReview(run.run_id)}
                >
                  Review
                </button>
              {:else if canReview(run)}
                <button
                  class="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600
                         hover:bg-indigo-700 rounded-md transition-colors"
                  on:click={() => goToReview(run.run_id)}
                >
                  Review
                </button>
              {:else}
                <button
                  class="px-3 py-1.5 text-sm font-medium text-slate-600 bg-slate-100
                         hover:bg-slate-200 rounded-md transition-colors"
                  on:click={() => goToReview(run.run_id)}
                >
                  View
                </button>
              {/if}
              <button
                class="px-2 py-1.5 text-sm text-slate-400 hover:text-red-600
                       hover:bg-red-50 rounded-md transition-colors"
                title="Delete run"
                on:click={() => (confirmDelete = run)}
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Pipeline stages -->
  <div class="bg-white border border-slate-200 rounded-lg p-4 mt-6">
    <h3 class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Pipeline Stages</h3>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      {#each Object.entries(STAGES) as [num, stage]}
        <div class="flex items-start gap-2">
          <span class="flex-shrink-0 w-5 h-5 rounded-full bg-slate-100 text-slate-600 flex items-center justify-center text-xs font-bold">
            {num}
          </span>
          <div>
            <div class="text-sm font-medium text-slate-800">{stage.title}</div>
            <div class="text-xs text-slate-500 leading-snug">{stage.description}</div>
          </div>
        </div>
      {/each}
    </div>
  </div>

  {#if confirmDelete}
    <div class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
        <h3 class="text-lg font-semibold text-slate-900">Delete this run?</h3>
        <p class="text-sm text-slate-600 mt-2">
          <strong>{confirmDelete.organization} / {confirmDelete.source}</strong>
          <span class="block text-slate-400 text-xs mt-0.5">{confirmDelete.run_id}</span>
        </p>
        <p class="text-sm text-red-600 mt-3">
          This permanently deletes all artifacts, review decisions, and generated files.
          This cannot be undone.
        </p>
        <div class="flex justify-end gap-2 mt-6">
          <button
            class="px-4 py-2 text-sm font-medium text-slate-700 bg-slate-100
                   hover:bg-slate-200 rounded-md transition-colors"
            disabled={deleting}
            on:click={() => (confirmDelete = null)}
          >
            Cancel
          </button>
          <button
            class="px-4 py-2 text-sm font-medium text-white bg-red-600
                   hover:bg-red-700 rounded-md transition-colors disabled:opacity-50"
            disabled={deleting}
            on:click={handleDelete}
          >
            {deleting ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>
