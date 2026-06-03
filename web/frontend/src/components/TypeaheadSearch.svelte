<script>
  /**
   * Typeahead search against the target catalog.
   * User types a few characters, results appear in a dropdown.
   *
   * Props:
   *   runId   - current run ID (for catalog context)
   *   kind    - "type" | "property" | "both"
   *   onSelect(item) - callback when user picks a result
   *   placeholder - input placeholder text
   */
  import { searchCatalog } from "../lib/api.js";

  export let runId;
  export let kind = "both";
  export let onSelect = () => {};
  export let placeholder = "Search types...";

  let query = "";
  let results = { types: [], properties: [] };
  let isOpen = false;
  let loading = false;
  let debounceTimer;
  let inputEl;

  function handleInput() {
    clearTimeout(debounceTimer);
    if (query.length < 2) {
      results = { types: [], properties: [] };
      isOpen = false;
      return;
    }
    loading = true;
    debounceTimer = setTimeout(async () => {
      try {
        results = await searchCatalog(runId, query, kind);
        isOpen = true;
      } catch (e) {
        results = { types: [], properties: [] };
      } finally {
        loading = false;
      }
    }, 250);
  }

  function selectItem(item) {
    onSelect(item);
    query = item.qname || item.qualifiedProperty || "";
    isOpen = false;
  }

  function handleBlur() {
    // Delay to allow click on dropdown
    setTimeout(() => { isOpen = false; }, 200);
  }

  function handleKeydown(e) {
    if (e.key === "Escape") {
      isOpen = false;
      inputEl?.blur();
    }
  }

  $: hasResults = (results.types?.length || 0) + (results.properties?.length || 0) > 0;
</script>

<div class="relative">
  <div class="relative">
    <input
      bind:this={inputEl}
      bind:value={query}
      on:input={handleInput}
      on:focus={() => { if (hasResults) isOpen = true; }}
      on:blur={handleBlur}
      on:keydown={handleKeydown}
      type="text"
      {placeholder}
      class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
             focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent
             placeholder:text-slate-400"
    />
    {#if loading}
      <div class="absolute right-3 top-2.5">
        <div class="w-4 h-4 border-2 border-slate-300 border-t-indigo-500 rounded-full animate-spin"></div>
      </div>
    {/if}
  </div>

  {#if isOpen && hasResults}
    <div class="absolute z-50 w-full mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-72 overflow-y-auto">
      {#if results.types?.length}
        <div class="px-3 py-1.5 text-xs font-medium text-slate-400 uppercase tracking-wider bg-slate-50">
          Types
        </div>
        {#each results.types as t}
          <button
            class="w-full text-left px-3 py-2 hover:bg-indigo-50 transition-colors border-b border-slate-50 last:border-0"
            on:mousedown|preventDefault={() => selectItem(t)}
          >
            <div class="font-mono text-sm text-indigo-700">{t.qname}</div>
            {#if t.definition}
              <div class="text-xs text-slate-500 truncate mt-0.5">{t.definition}</div>
            {/if}
          </button>
        {/each}
      {/if}

      {#if results.properties?.length}
        <div class="px-3 py-1.5 text-xs font-medium text-slate-400 uppercase tracking-wider bg-slate-50">
          Properties
        </div>
        {#each results.properties as p}
          <button
            class="w-full text-left px-3 py-2 hover:bg-indigo-50 transition-colors border-b border-slate-50 last:border-0"
            on:mousedown|preventDefault={() => selectItem(p)}
          >
            <div class="font-mono text-sm text-blue-700">{p.qualifiedProperty}</div>
            {#if p.definition}
              <div class="text-xs text-slate-500 truncate mt-0.5">{p.definition}</div>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  {/if}
</div>
