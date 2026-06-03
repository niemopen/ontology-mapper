<script>
  import { onMount } from "svelte";
  import {
    getReviewState,
    approveConcept,
    approveAll,
    changeTarget,
    resolveProperty,
    submitReview,
    resetReview,
    continuePipeline,
    getRunStatus,
    getRun,
    searchCatalog,
  } from "../lib/api.js";
  import { currentRunId, goToDashboard, goToResults, showError, loading } from "../lib/stores.js";
  import MappingCard from "../components/MappingCard.svelte";
  import TypeaheadSearch from "../components/TypeaheadSearch.svelte";

  let review = null;
  let currentStage = null;
  let submitting = false;
  let confirmReset = false;
  let postReview = null; // null | { status, stage, error }
  let postReviewPoll = null;
  let runSummary = null;
  let filterAction = "all"; // "all" | "reuse" | "extend" | "augment"
  let filterStatus = "all"; // "all" | "pending" | "accepted"
  let searchQuery = "";

  $: runId = $currentRunId;
  $: readOnly = currentStage !== null && parseInt(currentStage) !== 4 && parseInt(currentStage) !== 5;

  onMount(() => loadReview());

  async function loadReview() {
    if (!runId) return;
    loading.set(true);
    try {
      const run = await getRun(runId);
      currentStage = run?.summary?.current_stage || null;
      review = await getReviewState(runId);
    } catch (e) {
      showError(`Failed to load review: ${e.message}`);
    } finally {
      loading.set(false);
    }
  }

  // --- Derived values ---
  $: mappings = review?.mappings || [];
  $: validation = review?.validation || {};
  $: availableActions = Object.keys(review?.actions || {});
  $: totalConcepts = validation.totalConcepts || 0;
  $: accepted = validation.accepted || 0;
  $: pending = validation.pending || 0;
  $: mustDecide = validation.humanMustDecide || 0;
  $: bestGuessCount = validation.bestGuess || 0;
  $: canSubmit = validation.canSubmit && !submitting;
  $: progress = totalConcepts > 0 ? (accepted / totalConcepts) * 100 : 0;

  // Group mappings by action (only actions supported by the target ontology)
  const ACTION_META = {
    reuse: { label: "Reuse", color: "emerald" },
    augment: { label: "Augment", color: "amber" },
    extend: { label: "Extend", color: "blue" },
  };

  $: actionGroups = availableActions
    .filter((k) => ACTION_META[k])
    .map((k) => ({
      key: k,
      label: ACTION_META[k].label,
      color: ACTION_META[k].color,
      items: filteredMappings.filter((m) => m.action === k),
    }));

  // Filter mappings
  $: filteredMappings = mappings.filter((m) => {
    if (filterAction !== "all" && m.action !== filterAction) return false;
    if (filterStatus === "pending" && m.reviewStatus !== "pending-review") return false;
    if (filterStatus === "accepted" && m.reviewStatus !== "accepted") return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const inConcept = m.sourceConcept?.toLowerCase().includes(q);
      const inTarget = m.targetType?.toLowerCase().includes(q);
      if (!inConcept && !inTarget) return false;
    }
    return true;
  });

  // --- Actions ---

  async function handleApprove(concept, confidence = "confident") {
    try {
      await approveConcept(runId, concept, confidence);
      await loadReview();
    } catch (e) {
      showError(`Approve failed: ${e.message}`);
    }
  }

  async function handleApproveAll() {
    try {
      await approveAll(runId);
      await loadReview();
    } catch (e) {
      showError(`Approve all failed: ${e.message}`);
    }
  }

  async function handleReset() {
    try {
      await resetReview(runId);
      confirmReset = false;
      await loadReview();
    } catch (e) {
      showError(`Reset failed: ${e.message}`);
    }
  }

  async function handleChangeTarget(concept, newTargetType) {
    try {
      await changeTarget(runId, concept, newTargetType);
      await loadReview();
    } catch (e) {
      showError(`Change target failed: ${e.message}`);
    }
  }

  async function handleResolveProperty(concept, sourceProperty, propAction, targetProperty, confidence = "confident") {
    try {
      await resolveProperty(runId, concept, sourceProperty, propAction, targetProperty, confidence);
      await loadReview();
    } catch (e) {
      showError(`Resolve property failed: ${e.message}`);
    }
  }

  async function handleSubmit() {
    submitting = true;
    try {
      await submitReview(runId);
      // Stage 5 complete — kick off stages 6-8
      postReview = { status: "starting", stage: "6", error: null };
      await continuePipeline(runId);
      postReview = { status: "running", stage: "6", error: null };
      startPostReviewPoll();
    } catch (e) {
      showError(`Submit failed: ${e.message}`);
    } finally {
      submitting = false;
    }
  }

  function startPostReviewPoll() {
    if (postReviewPoll) clearInterval(postReviewPoll);
    postReviewPoll = setInterval(async () => {
      try {
        const status = await getRunStatus(runId);
        const bg = status.pipeline || {};
        postReview = {
          status: bg.status || "running",
          stage: bg.stage || postReview?.stage || "6",
          error: bg.error || null,
        };
        if (bg.status === "completed" || bg.status === "failed") {
          clearInterval(postReviewPoll);
          postReviewPoll = null;
          if (bg.status === "completed") {
            // Load final run summary
            try {
              const run = await getRun(runId);
              runSummary = run;
            } catch { /* not critical */ }
          }
        }
      } catch (e) {
        clearInterval(postReviewPoll);
        postReviewPoll = null;
        postReview = { status: "failed", stage: postReview?.stage || "?", error: e.message };
      }
    }, 3000);
  }

  const stageNames = {
    "6": "Generate",
    "7": "Validate",
    "8": "Finalize",
  };
</script>

<div>
  <!-- Back button + title -->
  <div class="flex items-center gap-3 mb-4">
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
      <h1 class="text-2xl font-bold text-slate-900">Review Mappings</h1>
      <p class="text-sm text-slate-500">
        {review?.targetOntology || ""} {review?.targetVersion || ""}
        <span class="text-slate-300 mx-1">|</span>
        {runId}
      </p>
    </div>
  </div>

  {#if $loading && !review}
    <div class="text-center py-16 text-slate-400">Loading review data...</div>
  {:else if review}

    <!-- Summary bar -->
    <div class="bg-white border border-slate-200 rounded-lg p-4 mb-6 sticky top-14 z-30">
      <div class="flex items-center gap-6">
        <!-- Progress bar -->
        <div class="flex-1">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-medium text-slate-700">
              {accepted} / {totalConcepts} reviewed
            </span>
            {#if bestGuessCount > 0}
              <span class="text-xs font-medium text-amber-600">
                {bestGuessCount} best-guess
              </span>
            {/if}
            {#if mustDecide > 0}
              <span class="text-xs font-medium text-red-600">
                {mustDecide} must-decide
              </span>
            {/if}
          </div>
          <div class="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              class:bg-emerald-500={progress === 100 && mustDecide === 0}
              class:bg-indigo-500={progress < 100 || mustDecide > 0}
              style="width: {progress}%"
            ></div>
          </div>
        </div>

        <!-- Action buttons -->
        <div class="flex items-center gap-2 flex-shrink-0">
          {#if readOnly}
            <span class="text-xs text-slate-400 italic">Read-only</span>
          {:else}
            <button
              class="px-3 py-1.5 text-sm font-medium text-red-600 bg-red-50
                     hover:bg-red-100 rounded-md transition-colors"
              on:click={() => confirmReset = true}
              title="Reset all decisions back to Stage 4 output"
            >
              Reset
            </button>

            {#if pending > 0}
              <button
                class="px-3 py-1.5 text-sm font-medium text-indigo-700 bg-indigo-50
                       hover:bg-indigo-100 rounded-md transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={mustDecide > 0}
                on:click={handleApproveAll}
                title={mustDecide > 0 ? `Blocked: ${mustDecide} properties need human decision` : "Approve all pending"}
              >
                Approve All ({pending})
              </button>
            {/if}

            <button
              class="px-4 py-1.5 text-sm font-medium text-white rounded-md transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
              class:bg-emerald-600={canSubmit}
              class:hover:bg-emerald-700={canSubmit}
              class:bg-slate-400={!canSubmit}
              disabled={!canSubmit}
              on:click={handleSubmit}
              title={canSubmit ? "Submit review and complete Stage 5" : `${pending} pending, ${mustDecide} must-decide`}
            >
              {#if submitting}
                Submitting...
            {:else}
              Submit Review
            {/if}
          </button>
          {/if}
        </div>
      </div>

      <!-- Validation blockers -->
      {#if !readOnly && !validation.canSubmit}
        <div class="mt-3 flex flex-wrap gap-2">
          {#if pending > 0}
            <span class="inline-flex items-center gap-1 px-2 py-1 bg-amber-50 text-amber-700 rounded text-xs">
              <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clip-rule="evenodd"/>
              </svg>
              {pending} concepts pending
            </span>
          {/if}
          {#if mustDecide > 0}
            <span class="inline-flex items-center gap-1 px-2 py-1 bg-red-50 text-red-700 rounded text-xs">
              <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
              </svg>
              {mustDecide} properties need decision
            </span>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Filters -->
    <div class="flex items-center gap-4 mb-4">
      <!-- Action filter -->
      <div class="flex items-center gap-1 bg-white border border-slate-200 rounded-lg p-0.5">
        {#each [["all", "All"], ...availableActions.filter((k) => ACTION_META[k]).map((k) => [k, ACTION_META[k].label])] as [key, label]}
          <button
            class="px-3 py-1 text-xs font-medium rounded-md transition-colors"
            class:bg-indigo-600={filterAction === key}
            class:text-white={filterAction === key}
            class:text-slate-600={filterAction !== key}
            class:hover:bg-slate-50={filterAction !== key}
            on:click={() => filterAction = key}
          >
            {label}
          </button>
        {/each}
      </div>

      <!-- Status filter -->
      <div class="flex items-center gap-1 bg-white border border-slate-200 rounded-lg p-0.5">
        {#each [["all", "All"], ["pending", "Pending"], ["accepted", "Accepted"]] as [key, label]}
          <button
            class="px-3 py-1 text-xs font-medium rounded-md transition-colors"
            class:bg-indigo-600={filterStatus === key}
            class:text-white={filterStatus === key}
            class:text-slate-600={filterStatus !== key}
            class:hover:bg-slate-50={filterStatus !== key}
            on:click={() => filterStatus = key}
          >
            {label}
          </button>
        {/each}
      </div>

      <!-- Text search -->
      <div class="flex-1 max-w-xs">
        <input
          bind:value={searchQuery}
          type="text"
          placeholder="Filter by name..."
          class="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-sm
                 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
      </div>

      <span class="text-xs text-slate-400">
        {filteredMappings.length} of {mappings.length}
      </span>
    </div>

    <!-- Mapping groups -->
    {#each actionGroups as group}
      {#if group.items.length > 0}
        <div class="mb-6">
          <h2 class="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-2">
            <span
              class="w-2.5 h-2.5 rounded-full"
              class:bg-emerald-500={group.color === "emerald"}
              class:bg-amber-500={group.color === "amber"}
              class:bg-blue-500={group.color === "blue"}
            ></span>
            {group.label}
            <span class="text-slate-400 font-normal">({group.items.length})</span>
          </h2>
          <div class="space-y-2">
            {#each group.items as mapping (mapping.sourceConcept)}
              <MappingCard
                {mapping}
                {runId}
                {readOnly}
                onApprove={handleApprove}
                onChangeTarget={handleChangeTarget}
                onResolveProperty={handleResolveProperty}
              />
            {/each}
          </div>
        </div>
      {/if}
    {/each}

    {#if filteredMappings.length === 0}
      <div class="text-center py-12 text-slate-400">
        No mappings match your filters
      </div>
    {/if}

  {/if}

  {#if postReview}
    <div class="fixed inset-0 z-50 bg-black/40 flex items-center justify-center">
      <div class="bg-white rounded-xl shadow-2xl p-8 max-w-lg w-full mx-4">
        {#if postReview.status === "running" || postReview.status === "starting"}
          <div class="text-center">
            <div class="w-12 h-12 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mx-auto mb-4"></div>
            <h3 class="text-lg font-semibold text-slate-900 mb-2">
              Generating Output
            </h3>
            <p class="text-sm text-slate-600 mb-4">
              Stage {postReview.stage}: {stageNames[postReview.stage] || "Processing"}...
            </p>
            <div class="flex justify-center gap-2">
              {#each ["6", "7", "8"] as s}
                {@const done = parseInt(postReview.stage) > parseInt(s)}
                {@const active = postReview.stage === s}
                <div class="flex items-center gap-1">
                  <div class="w-3 h-3 rounded-full"
                       class:bg-emerald-500={done}
                       class:bg-indigo-500={active}
                       class:animate-pulse={active}
                       class:bg-slate-200={!done && !active}
                  ></div>
                  <span class="text-xs text-slate-500">{stageNames[s]}</span>
                </div>
              {/each}
            </div>
          </div>

        {:else if postReview.status === "completed"}
          <div class="text-center">
            <div class="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg class="w-8 h-8 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
              </svg>
            </div>
            <h3 class="text-xl font-semibold text-slate-900 mb-2">
              Pipeline Complete
            </h3>
            <p class="text-sm text-slate-600 mb-6">
              All 8 stages finished successfully. Your edge package is ready.
            </p>
            <div class="flex justify-center gap-3">
              <button
                class="px-6 py-2 bg-indigo-600 text-white font-medium rounded-lg
                       hover:bg-indigo-700 transition-colors"
                on:click={() => { postReview = null; goToResults(runId); }}
              >
                View Results
              </button>
              <button
                class="px-4 py-2 text-slate-600 bg-slate-100 font-medium rounded-lg
                       hover:bg-slate-200 transition-colors"
                on:click={() => { postReview = null; goToDashboard(); }}
              >
                Dashboard
              </button>
            </div>
          </div>

        {:else if postReview.status === "failed"}
          <div class="text-center">
            <div class="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg class="w-8 h-8 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
              </svg>
            </div>
            <h3 class="text-lg font-semibold text-slate-900 mb-2">
              Pipeline Failed
            </h3>
            <p class="text-sm text-slate-600 mb-2">
              Failed at Stage {postReview.stage}: {stageNames[postReview.stage] || "Unknown"}
            </p>
            {#if postReview.error}
              <pre class="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-800 text-left overflow-auto max-h-48 mb-6">{postReview.error}</pre>
            {/if}
            <div class="flex justify-center gap-3">
              <button
                class="px-4 py-2 bg-slate-100 text-slate-700 font-medium rounded-lg
                       hover:bg-slate-200 transition-colors"
                on:click={() => { postReview = null; goToDashboard(); }}
              >
                Back to Dashboard
              </button>
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}

  {#if confirmReset}
    <div class="fixed inset-0 z-50 bg-black/40 flex items-center justify-center">
      <div class="bg-white rounded-xl shadow-2xl p-8 max-w-md w-full mx-4">
        <div class="flex items-start gap-3 mb-4">
          <div class="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0">
            <svg class="w-5 h-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
          </div>
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Reset All Decisions?</h3>
            <p class="text-sm text-slate-600 mt-1">
              This will discard all review decisions — approvals, confidence selections,
              resolved properties — and restore the original Stage 4 output.
            </p>
            <p class="text-sm font-medium text-red-600 mt-2">
              You will lose all of your work.
            </p>
          </div>
        </div>
        <div class="flex justify-end gap-3">
          <button
            class="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100
                   hover:bg-slate-200 rounded-lg transition-colors"
            on:click={() => confirmReset = false}
          >
            Cancel
          </button>
          <button
            class="px-4 py-2 text-sm font-medium text-white bg-red-600
                   hover:bg-red-700 rounded-lg transition-colors"
            on:click={handleReset}
          >
            Reset All
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>
