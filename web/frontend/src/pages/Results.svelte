<script>
  import { onMount } from "svelte";
  import { getResults, downloadUrl, fileUrl } from "../lib/api.js";
  import { getToken } from "../lib/auth.js";

  async function openFile(path) {
    try {
      const token = await getToken();
      const res = await fetch(fileUrl(runId, path), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      window.open(URL.createObjectURL(blob), "_blank");
    } catch (e) {
      showError(`Failed to open file: ${e.message}`);
    }
  }
  import { currentRunId, goToDashboard, goToReview, showError, loading } from "../lib/stores.js";
  import { STAGES } from "../lib/stages.js";

  let results = null;

  $: runId = $currentRunId;

  onMount(() => loadResults());

  async function loadResults() {
    if (!runId) return;
    loading.set(true);
    try {
      results = await getResults(runId);
    } catch (e) {
      showError(`Failed to load results: ${e.message}`);
    } finally {
      loading.set(false);
    }
  }

  // Group files by directory for display
  $: fileGroups = groupFiles(results?.files || []);

  const dirDescriptions = {
    ontology: "OWL ontology files",
    shapes: "SHACL validation shapes",
    vocab: "Code lists and vocabularies",
    mappings: "Mapping decisions and alignment",
    extensions: "Extension type definitions",
    governance: "Audit trail, validation, and lineage",
    kg: "Knowledge graph (Neo4j + RDF/SPARQL)",
    cmf: "Canonical Model Format exchange",
    root: "Package metadata",
  };

  function groupFiles(files) {
    const groups = {};
    for (const f of files) {
      const slash = f.path.indexOf("/");
      const dir = slash > 0 ? f.path.substring(0, slash) : "";
      if (!groups[dir]) groups[dir] = [];
      groups[dir].push(f);
    }
    return Object.entries(groups).map(([dir, items]) => ({
      dir: dir || "root",
      description: dirDescriptions[dir || "root"] || "",
      items,
    }));
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDate(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      return d.toLocaleDateString("en-US", {
        year: "numeric", month: "long", day: "numeric",
        hour: "2-digit", minute: "2-digit", timeZoneName: "short",
      });
    } catch { return iso; }
  }

  async function handleDownload() {
    try {
      const token = await getToken();
      const res = await fetch(downloadUrl(runId), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.headers.get("Content-Disposition")?.match(/filename="(.+)"/)?.[1] || `${runId}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      showError(`Download failed: ${e.message}`);
    }
  }

  $: totalSize = (results?.files || []).reduce((sum, f) => sum + f.size, 0);
  $: totalFiles = (results?.files || []).length;

  function formatDuration(startIso, endIso) {
    if (!startIso || !endIso) return null;
    try {
      const ms = new Date(endIso) - new Date(startIso);
      if (ms < 0) return null;
      const secs = Math.floor(ms / 1000);
      if (secs < 60) return `${secs}s`;
      const mins = Math.floor(secs / 60);
      const remSecs = secs % 60;
      if (mins < 60) return `${mins}m ${remSecs}s`;
      const hrs = Math.floor(mins / 60);
      const remMins = mins % 60;
      return `${hrs}h ${remMins}m`;
    } catch { return null; }
  }

  $: stageTimings = results?.stageTimings || {};
</script>

<div>
  <!-- Header -->
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
    <div class="flex-1">
      <h1 class="text-2xl font-bold text-slate-900">Pipeline Results</h1>
      {#if results?.metadata}
        <p class="text-sm text-slate-500">
          {results.metadata.organization}
          <span class="text-slate-300 mx-1">/</span>
          {results.metadata.source}
          <span class="text-slate-300 mx-1">|</span>
          {results.metadata.targetOntology} {results.metadata.targetVersion}
        </p>
      {/if}
    </div>
    {#if results}
      <button
        class="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium
               rounded-lg hover:bg-indigo-700 transition-colors"
        on:click={handleDownload}
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
        Download Package
      </button>
    {/if}
  </div>

  {#if $loading && !results}
    <div class="text-center py-16 text-slate-400">Loading results...</div>
  {:else if results}

    <!-- Metadata + Stats cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">

      <!-- Run info -->
      <div class="bg-white border border-slate-200 rounded-lg p-4">
        <h3 class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Run Details</h3>
        <dl class="space-y-2 text-sm">
          <div>
            <dt class="text-slate-500">Package</dt>
            <dd class="font-medium text-slate-900">{results.metadata.packageName || runId}</dd>
          </div>
          <div>
            <dt class="text-slate-500">Version</dt>
            <dd class="font-medium text-slate-900">{results.metadata.packageVersion || "—"}</dd>
          </div>
          <div>
            <dt class="text-slate-500">Created</dt>
            <dd class="font-medium text-slate-900">{formatDate(results.metadata.createdAt)}</dd>
          </div>
          <div>
            <dt class="text-slate-500">Finalized</dt>
            <dd class="font-medium text-slate-900">{formatDate(results.metadata.finalizedAt)}</dd>
          </div>
        </dl>
        {#if Object.keys(stageTimings).length > 0}
          <div class="mt-3 pt-3 border-t border-slate-100">
            <dt class="text-xs text-slate-500 mb-1.5">Stage Durations</dt>
            <div class="space-y-1">
              {#each Object.entries(STAGES) as [num, stage]}
                {@const timing = stageTimings[num]}
                {@const dur = timing ? formatDuration(timing.startedAt, timing.completedAt) : null}
                {#if timing}
                  <div class="flex items-center justify-between text-xs">
                    <span class="text-slate-600">{num}. {stage.title}</span>
                    <span class="font-medium {timing.status === 'completed' ? 'text-slate-700' : 'text-amber-600'}">
                      {dur || (timing.status === 'completed' ? '—' : timing.status)}
                    </span>
                  </div>
                {/if}
              {/each}
            </div>
          </div>
        {/if}
      </div>

      <!-- Review stats -->
      <div class="bg-white border border-slate-200 rounded-lg p-4">
        <h3 class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Review Decisions</h3>
        {#if results.reviewStats?.totalConcepts}
          <div class="text-2xl font-bold text-slate-900 mb-3">
            {results.reviewStats.totalConcepts} <span class="text-sm font-normal text-slate-500">concepts</span>
          </div>
          <div class="space-y-1.5">
            {#each Object.entries(results.reviewStats.actionCounts || {}) as [action, count]}
              {@const colors = { reuse: "bg-emerald-100 text-emerald-800", extend: "bg-blue-100 text-blue-800", augment: "bg-amber-100 text-amber-800" }}
              <div class="flex items-center justify-between">
                <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {colors[action] || 'bg-slate-100 text-slate-600'}">
                  {action}
                </span>
                <span class="text-sm font-medium text-slate-700">{count}</span>
              </div>
            {/each}
          </div>
          {#if results.reviewStats.confidenceCounts}
            <div class="mt-3 pt-3 border-t border-slate-100 space-y-1">
              {#each Object.entries(results.reviewStats.confidenceCounts) as [conf, count]}
                <div class="flex items-center justify-between text-xs">
                  <span class="{conf === 'best-guess' ? 'text-amber-600' : 'text-indigo-600'} font-medium">{conf}</span>
                  <span class="text-slate-500">{count}</span>
                </div>
              {/each}
            </div>
          {/if}
        {:else}
          <p class="text-sm text-slate-400">No review data available</p>
        {/if}

        <button
          class="mt-3 text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
          on:click={() => goToReview(runId)}
        >
          View review decisions...
        </button>
      </div>

      <!-- Validation summary -->
      <div class="bg-white border border-slate-200 rounded-lg p-4">
        <h3 class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Validation</h3>
        {#if results.validation?.checkCount}
          <div class="flex items-center gap-2 mb-3">
            {#if results.validation.allPassed}
              <div class="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center">
                <svg class="w-5 h-5 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                </svg>
              </div>
              <span class="text-lg font-semibold text-emerald-700">All Passed</span>
            {:else}
              <div class="w-8 h-8 rounded-full bg-red-100 flex items-center justify-center">
                <svg class="w-5 h-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                </svg>
              </div>
              <span class="text-lg font-semibold text-red-700">{results.validation.failCount} Failed</span>
            {/if}
          </div>
          <p class="text-sm text-slate-600 mb-3">
            {results.validation.passCount} / {results.validation.checkCount} checks passed
          </p>
          <div class="space-y-1 max-h-48 overflow-y-auto">
            {#each results.validation.checks || [] as check}
              <div class="flex items-start gap-2 text-xs">
                <span class="mt-0.5 flex-shrink-0 {check.status === 'pass' ? 'text-emerald-500' : 'text-red-500'}">
                  {check.status === "pass" ? "pass" : "FAIL"}
                </span>
                <div>
                  <span class="font-medium text-slate-700">{check.check}</span>
                  <span class="text-slate-400 ml-1">{check.details}</span>
                </div>
              </div>
            {/each}
          </div>
        {:else}
          <p class="text-sm text-slate-400">No validation data available</p>
        {/if}
      </div>
    </div>

    <!-- Pipeline stages -->
    <div class="bg-white border border-slate-200 rounded-lg p-4 mb-6">
      <h3 class="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Pipeline Stages</h3>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        {#each Object.entries(STAGES) as [num, stage]}
          <div class="flex items-start gap-2">
            <span class="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center text-xs font-bold">
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

    <!-- File inventory -->
    <div class="bg-white border border-slate-200 rounded-lg overflow-hidden">
      <div class="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-slate-900">Package Contents</h3>
        <span class="text-xs text-slate-500">{totalFiles} files, {formatBytes(totalSize)}</span>
      </div>
      <div class="divide-y divide-slate-100">
        {#each fileGroups as group}
          <div class="px-4 py-3">
            <div class="flex items-center gap-2 mb-2">
              <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
              </svg>
              <span class="text-sm font-medium text-slate-800">{group.dir === "root" ? "/" : group.dir + "/"}</span>
              {#if group.description}
                <span class="text-xs text-slate-500">{group.description}</span>
              {/if}
            </div>
            <div class="ml-6 space-y-0.5">
              {#each group.items as file}
                {@const displayPath = group.dir !== "root" ? file.path.substring(group.dir.length + 1) : file.path}
                <div class="flex items-center justify-between text-xs">
                  <button
                    class="text-indigo-600 hover:text-indigo-800 hover:underline font-mono text-left"
                    on:click={() => openFile(file.path)}
                  >{displayPath}</button>
                  <span class="text-slate-400">{formatBytes(file.size)}</span>
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>

  {/if}
</div>
