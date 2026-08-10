<script>
  /**
   * Source and target definitions for one mapping, side by side.
   *
   * Both values come straight from the mapping matrix entry — no fetch.
   * Shown inline and clamped, matching how rationale is presented.
   *
   * Props:
   *   sourceLabel      - qname of the source concept/property
   *   sourceDefinition - definition from the source model
   *   targetLabel      - display label (or qname) of the target
   *   targetDefinition - definition from the target ontology
   *   targetNote       - placeholder when there is no target definition,
   *                      for the cases where the reason is not "no data"
   */
  export let sourceLabel = "";
  export let sourceDefinition = "";
  export let targetLabel = "";
  export let targetDefinition = "";
  export let targetNote = "[no data]";

  let expanded = false;

  // "[undecided]" is a pipeline sentinel, not something to show as a name.
  $: shownTargetLabel = targetLabel === "[undecided]" ? "" : targetLabel;

  // NODS definitions embed hard newlines; SALI definitions run to 3.5k chars.
  const LONG = 200;
  $: isLong =
    (sourceDefinition || "").length > LONG ||
    (targetDefinition || "").length > LONG ||
    (sourceDefinition || "").includes("\n") ||
    (targetDefinition || "").includes("\n");

</script>

  <div class="mt-3">
    <div class="grid gap-x-4 gap-y-3 sm:grid-cols-2 items-start">
      <div class="min-w-0">
        <h5 class="text-xs font-medium text-slate-500 uppercase tracking-wider">Source</h5>
        {#if sourceLabel}
          <code class="block text-xs text-slate-500 truncate">{sourceLabel}</code>
        {/if}
        {#if sourceDefinition}
          <p
            class="text-sm text-slate-700 mt-0.5 whitespace-pre-line break-words"
            class:line-clamp-3={!expanded}
          >{sourceDefinition}</p>
        {:else}
          <p class="text-sm text-slate-400 mt-0.5">[no data]</p>
        {/if}
      </div>

      <div class="min-w-0">
        <h5 class="text-xs font-medium text-slate-500 uppercase tracking-wider">Target</h5>
        {#if shownTargetLabel}
          <code class="block text-xs text-indigo-500 truncate">{shownTargetLabel}</code>
        {/if}
        {#if targetDefinition}
          <p
            class="text-sm text-slate-700 mt-0.5 whitespace-pre-line break-words"
            class:line-clamp-3={!expanded}
          >{targetDefinition}</p>
        {:else}
          <p class="text-sm text-slate-400 mt-0.5">{targetNote}</p>
        {/if}
      </div>
    </div>

    {#if isLong}
      <button
        class="mt-1 text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
        on:click|stopPropagation={() => (expanded = !expanded)}
      >
        {expanded ? "Show less" : "Show more"}
      </button>
    {/if}
  </div>
