<script>
  /**
   * A single concept mapping card. Expandable to show details and properties.
   *
   * Props:
   *   mapping    - mapping entry from mapping-matrix.json
   *   runId      - for catalog search
   *   onApprove(concept) - callback
   *   onChangeTarget(concept) - callback
   *   onResolveProperty(concept, sourceProperty, action, targetProperty) - callback
   */
  import PropertyRow from "./PropertyRow.svelte";
  import TypeaheadSearch from "./TypeaheadSearch.svelte";

  export let mapping;
  export let runId;
  export let readOnly = false;
  export let onApprove = () => {};
  export let onChangeTarget = () => {};
  export let onResolveProperty = () => {};

  let expanded = false;
  let changingTarget = false;
  let newTargetType = "";

  function toggleExpanded() {
    expanded = !expanded;
  }

  function onHeaderKeydown(e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleExpanded();
    }
  }

  $: action = mapping.action;
  $: isAccepted = mapping.reviewStatus === "accepted";
  $: isPending = mapping.reviewStatus === "pending-review";
  $: properties = mapping.propertyMappings || [];
  $: mustDecideCount = properties.filter(
    (p) => p.action === "human-must-decide" && p.reviewStatus === "pending-review"
  ).length;
  $: pendingPropCount = properties.filter(
    (p) => p.reviewStatus === "pending-review"
  ).length;
  $: acceptedPropCount = properties.filter(
    (p) => p.reviewStatus === "accepted"
  ).length;

  $: actionStyle = {
    reuse: { bg: "bg-emerald-50 border-emerald-200", badge: "bg-emerald-100 text-emerald-800", ring: "ring-emerald-500" },
    extend: { bg: "bg-blue-50 border-blue-200", badge: "bg-blue-100 text-blue-800", ring: "ring-blue-500" },
    augment: { bg: "bg-amber-50 border-amber-200", badge: "bg-amber-100 text-amber-800", ring: "ring-amber-500" },
    exclude: { bg: "bg-slate-50 border-slate-200", badge: "bg-slate-100 text-slate-600", ring: "ring-slate-400" },
  }[action] || { bg: "bg-slate-50 border-slate-200", badge: "bg-slate-100 text-slate-600", ring: "ring-slate-400" };

  function handleApprove(e) {
    e.stopPropagation();
    onApprove(mapping.sourceConcept, "confident");
  }

  function handleBestGuess(e) {
    e.stopPropagation();
    onApprove(mapping.sourceConcept, "best-guess");
  }

  function startChangeTarget(e) {
    e.stopPropagation();
    changingTarget = true;
    newTargetType = mapping.targetType || "";
  }

  function cancelChangeTarget() {
    changingTarget = false;
  }

  function confirmChangeTarget() {
    if (newTargetType && newTargetType !== mapping.targetType) {
      onChangeTarget(mapping.sourceConcept, newTargetType);
    }
    changingTarget = false;
  }

  function handleTypeaheadSelect(item) {
    newTargetType = item.qname || "";
  }

  function handlePropertyResolve(sourceProperty, propAction, targetProperty, confidence) {
    onResolveProperty(mapping.sourceConcept, sourceProperty, propAction, targetProperty, confidence);
  }
</script>

<div
  class="border rounded-lg transition-all {actionStyle.bg}"
  class:ring-2={expanded}
  class:{actionStyle.ring}={expanded}
>
  <!-- Card header (always visible) -->
  <div
    class="w-full text-left px-4 py-3 flex items-center gap-3 cursor-pointer"
    role="button"
    tabindex="0"
    aria-expanded={expanded}
    on:click={toggleExpanded}
    on:keydown={onHeaderKeydown}
  >
    <!-- Expand/collapse icon -->
    <svg
      class="w-4 h-4 text-slate-400 transition-transform flex-shrink-0"
      class:rotate-90={expanded}
      fill="none" stroke="currentColor" viewBox="0 0 24 24"
    >
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
    </svg>

    <!-- Status -->
    <div class="flex-shrink-0">
      {#if isAccepted}
        <div class="w-6 h-6 rounded-full bg-emerald-500 flex items-center justify-center">
          <svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
          </svg>
        </div>
      {:else}
        <div class="w-6 h-6 rounded-full border-2 border-amber-400 bg-amber-50"></div>
      {/if}
    </div>

    <!-- Concept name + action badge -->
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 flex-wrap">
        <code class="font-semibold text-sm text-slate-900">{mapping.sourceConcept}</code>
        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {actionStyle.badge}">
          {action}
        </span>
      </div>
      {#if mapping.targetType}
        <div class="flex items-center gap-1 mt-0.5">
          <svg class="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/>
          </svg>
          <code class="text-xs text-indigo-600">{mapping.targetTypeLabel || mapping.targetType}</code>
        </div>
      {/if}
    </div>

    <!-- Property counts -->
    <div class="flex-shrink-0 text-right">
      {#if properties.length > 0}
        <div class="text-xs text-slate-500">
          {properties.length} props
        </div>
        {#if mustDecideCount > 0}
          <div class="text-xs text-red-600 font-medium">
            {mustDecideCount} must-decide
          </div>
        {/if}
      {/if}
    </div>

    <!-- Confident / Best Guess toggle -->
    {#if !readOnly}
      <div class="flex-shrink-0 flex items-center gap-1">
        <button
          class="px-3 text-xs font-medium rounded-md transition-all
                 {mapping.confidence === 'confident' && isAccepted
                   ? 'py-1.5 text-white bg-indigo-600 ring-2 ring-indigo-300'
                   : 'py-1 text-indigo-700 bg-indigo-50 hover:bg-indigo-100'}"
          on:click={handleApprove}
          title="Accept — you're confident in this mapping"
        >
          Confident
        </button>
        <button
          class="px-3 text-xs font-medium rounded-md transition-all
                 {mapping.confidence === 'best-guess' && isAccepted
                   ? 'py-1.5 text-amber-800 bg-amber-300 ring-2 ring-amber-200'
                   : 'py-1 text-amber-700 bg-amber-50 hover:bg-amber-100'}"
          on:click={handleBestGuess}
          title="Accept as best guess — you're not fully sure"
        >
          Best Guess
        </button>
      </div>
    {:else if isAccepted && mapping.confidence}
      <span class="flex-shrink-0 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium
                   {mapping.confidence === 'best-guess' ? 'bg-amber-100 text-amber-700' : 'bg-indigo-100 text-indigo-700'}">
        {mapping.confidence === 'best-guess' ? 'best guess' : 'confident'}
      </span>
    {/if}
  </div>

  <!-- Expanded details -->
  {#if expanded}
    <div class="px-4 pb-4 border-t border-slate-200/50 mt-0">
      <!-- Rationale -->
      {#if mapping.rationale}
        <div class="mt-3">
          <h4 class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-1">Rationale</h4>
          <p class="text-sm text-slate-700">{mapping.rationale}</p>
        </div>
      {/if}

      <!-- Action-specific fields -->
      {#if action === "extend"}
        <div class="mt-3 flex gap-4 text-sm">
          {#if mapping.extensionType}
            <div>
              <span class="text-slate-500">Extension:</span>
              <code class="text-blue-700 ml-1">{mapping.extensionType}</code>
            </div>
          {/if}
          {#if mapping.baseType}
            <div>
              <span class="text-slate-500">Base:</span>
              <code class="text-blue-700 ml-1">{mapping.baseType}</code>
            </div>
          {/if}
        </div>
      {:else if action === "augment"}
        <div class="mt-3 flex gap-4 text-sm">
          {#if mapping.augmentationType}
            <div>
              <span class="text-slate-500">Augmentation:</span>
              <code class="text-amber-700 ml-1">{mapping.augmentationType}</code>
            </div>
          {/if}
          {#if mapping.augmentsType}
            <div>
              <span class="text-slate-500">Augments:</span>
              <code class="text-amber-700 ml-1">{mapping.augmentsType}</code>
            </div>
          {/if}
        </div>
      {/if}

      <!-- Change target -->
      {#if !readOnly}
      <div class="mt-3">
        {#if changingTarget}
          <div class="p-3 bg-white border border-slate-200 rounded-lg space-y-2">
            <!-- svelte-ignore a11y-label-has-associated-control -->
            <label class="block text-xs font-medium text-slate-600">New target type</label>
            <TypeaheadSearch
              {runId}
              kind="type"
              placeholder="Search target types..."
              onSelect={handleTypeaheadSelect}
            />
            {#if newTargetType}
              <p class="text-xs text-indigo-600">Selected: {newTargetType}</p>
            {/if}
            <div class="flex gap-2 pt-1">
              <button
                class="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded
                       hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                disabled={!newTargetType}
                on:click={confirmChangeTarget}
              >
                Change Target
              </button>
              <button
                class="px-3 py-1.5 text-sm text-slate-600 hover:text-slate-800 transition-colors"
                on:click={cancelChangeTarget}
              >
                Cancel
              </button>
            </div>
          </div>
        {:else}
          <button
            class="text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
            on:click={startChangeTarget}
          >
            Change target type...
          </button>
        {/if}
      </div>
      {/if}

      <!-- Properties -->
      {#if properties.length > 0}
        <div class="mt-4">
          <h4 class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-2">
            Properties
            <span class="text-slate-400 normal-case">
              ({acceptedPropCount} accepted, {pendingPropCount} pending{mustDecideCount > 0 ? `, ${mustDecideCount} must-decide` : ""})
            </span>
          </h4>
          <div class="space-y-1">
            {#each properties as prop (prop.sourceProperty)}
              <PropertyRow
                property={prop}
                {runId}
                {readOnly}
                onResolve={handlePropertyResolve}
              />
            {/each}
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
