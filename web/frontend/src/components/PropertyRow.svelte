<script>
  /**
   * Single property mapping row within an expanded MappingCard.
   *
   * Props:
   *   property      - property mapping object
   *   runId         - for catalog search
   *   onResolve(sourceProperty, action, targetProperty) - callback
   */
  import TypeaheadSearch from "./TypeaheadSearch.svelte";

  export let property;
  export let runId;
  export let readOnly = false;
  export let onResolve = () => {};

  let resolving = false;
  let rationaleExpanded = false;
  let selectedAction = "reuse-property";
  let selectedTarget = "";
  let selectedConfidence = "confident";

  $: actionColor = {
    "reuse-property": "bg-emerald-100 text-emerald-800",
    "create-property": "bg-blue-100 text-blue-800",
    "human-must-decide": "bg-red-100 text-red-800",
  }[property.action] || "bg-slate-100 text-slate-600";

  $: actionLabel = {
    "reuse-property": "Reuse",
    "create-property": "Create",
    "human-must-decide": "Must Decide",
  }[property.action] || property.action;

  $: statusIcon = property.reviewStatus === "accepted" ? "check" : "pending";
  $: isAccepted = property.reviewStatus === "accepted";
  $: needsDecision = property.action === "human-must-decide" && !isAccepted;

  function startResolve() {
    resolving = true;
    selectedAction = property.action === "human-must-decide" ? "reuse-property" : property.action;
    selectedTarget = property.targetProperty || "";
    selectedConfidence = property.confidence || "confident";
  }

  function cancelResolve() {
    resolving = false;
  }

  function confirmResolve() {
    onResolve(property.sourceProperty, selectedAction, selectedTarget || null, selectedConfidence);
    resolving = false;
  }

  function acceptProperty(confidence) {
    onResolve(property.sourceProperty, property.action, property.targetProperty || null, confidence);
  }

  function handleTypeaheadSelect(item) {
    selectedTarget = item.qualifiedProperty || item.qname || "";
  }
</script>

<div class="flex items-start gap-3 py-2 px-3 rounded-md transition-colors"
     class:bg-red-50={needsDecision}
     class:bg-slate-50={!needsDecision && !isAccepted}
     class:bg-emerald-50={isAccepted}>

  <!-- Status indicator -->
  <div class="mt-1 flex-shrink-0">
    {#if isAccepted}
      <svg class="w-4 h-4 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
      </svg>
    {:else if needsDecision}
      <svg class="w-4 h-4 text-red-500" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
      </svg>
    {:else}
      <div class="w-4 h-4 rounded-full border-2 border-slate-300"></div>
    {/if}
  </div>

  <!-- Property info -->
  <div class="flex-1 min-w-0">
    <div class="flex items-center gap-2 flex-wrap">
      <code class="text-sm font-medium text-slate-800">{property.sourceProperty}</code>
      <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {actionColor}">
        {actionLabel}
      </span>
    </div>

    {#if property.targetProperty}
      <div class="mt-0.5 flex items-center gap-1">
        <svg class="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/>
        </svg>
        <code class="text-sm text-indigo-600">{property.targetPropertyLabel || property.targetProperty}</code>
      </div>
    {/if}

    {#if property.rationale && !resolving}
      <button
        class="text-xs text-slate-500 mt-1 text-left w-full cursor-pointer hover:text-slate-700"
        on:click|stopPropagation={() => rationaleExpanded = !rationaleExpanded}
      >
        <p class:line-clamp-2={!rationaleExpanded}>{property.rationale}</p>
      </button>
    {/if}

    <!-- Resolve UI -->
    {#if resolving}
      <div class="mt-2 p-3 bg-white border border-slate-200 rounded-lg space-y-3">
        <div>
          <label for="property-action-select" class="block text-xs font-medium text-slate-600 mb-1">Action</label>
          <select
            id="property-action-select"
            bind:value={selectedAction}
            class="w-full text-sm border border-slate-300 rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="reuse-property">Reuse target property</option>
            <option value="create-property">Create new property</option>
          </select>
        </div>

        {#if selectedAction === "reuse-property"}
          <div>
            <!-- svelte-ignore a11y-label-has-associated-control -->
            <label class="block text-xs font-medium text-slate-600 mb-1">Target property</label>
            <TypeaheadSearch
              {runId}
              kind="property"
              placeholder="Search properties..."
              onSelect={handleTypeaheadSelect}
            />
            {#if selectedTarget}
              <p class="text-xs text-indigo-600 mt-1">Selected: {selectedTarget}</p>
            {/if}
          </div>
        {/if}

        <div>
          <!-- svelte-ignore a11y-label-has-associated-control -->
          <label class="block text-xs font-medium text-slate-600 mb-1">Confidence</label>
          <div class="flex gap-2">
            <label class="inline-flex items-center gap-1 text-sm cursor-pointer">
              <input type="radio" bind:group={selectedConfidence} value="confident"
                     class="text-indigo-600 focus:ring-indigo-500" />
              Confident
            </label>
            <label class="inline-flex items-center gap-1 text-sm cursor-pointer">
              <input type="radio" bind:group={selectedConfidence} value="best-guess"
                     class="text-amber-600 focus:ring-amber-500" />
              Best guess
            </label>
          </div>
        </div>

        <div class="flex gap-2">
          <button
            class="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700
                   disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            disabled={selectedAction === "reuse-property" && !selectedTarget}
            on:click={confirmResolve}
          >
            Apply
          </button>
          <button
            class="px-3 py-1.5 text-sm text-slate-600 hover:text-slate-800 transition-colors"
            on:click={cancelResolve}
          >
            Cancel
          </button>
        </div>
      </div>
    {/if}
  </div>

  <!-- Resolve / Accept / Edit buttons -->
  {#if !resolving && !readOnly}
    {#if needsDecision}
      <button
        class="flex-shrink-0 px-2.5 py-1 text-xs font-medium text-red-700 bg-red-100
               hover:bg-red-200 rounded transition-colors"
        on:click={startResolve}
      >
        Resolve
      </button>
    {:else}
      <div class="flex-shrink-0 flex items-center gap-1">
        <button
          class="px-2.5 text-xs font-medium rounded transition-all
                 {property.confidence === 'confident' && isAccepted
                   ? 'py-1.5 text-white bg-indigo-600 ring-2 ring-indigo-300'
                   : 'py-1 text-indigo-700 bg-indigo-50 hover:bg-indigo-100'}"
          on:click={() => acceptProperty("confident")}
          title="Accept — you're confident"
        >
          Confident
        </button>
        <button
          class="px-2.5 text-xs font-medium rounded transition-all
                 {property.confidence === 'best-guess' && isAccepted
                   ? 'py-1.5 text-amber-800 bg-amber-300 ring-2 ring-amber-200'
                   : 'py-1 text-amber-700 bg-amber-50 hover:bg-amber-100'}"
          on:click={() => acceptProperty("best-guess")}
          title="Accept as best guess"
        >
          Best Guess
        </button>
        <button
          class="px-2.5 py-1 text-xs font-medium text-slate-600 bg-slate-100
                 hover:bg-slate-200 rounded transition-colors"
          on:click={startResolve}
          title="Change action or target"
        >
          Edit
        </button>
      </div>
    {/if}
  {/if}
</div>
