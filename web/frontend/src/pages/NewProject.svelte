<script>
  import { onMount, onDestroy } from "svelte";
  import {
    getOntologies,
    createRun,
    uploadFiles,
    listSources,
    executePipeline,
    getRunStatus,
    createOntologyRequest,
  } from "../lib/api.js";
  import { goToReview, goToDashboard, showError, currentOrg } from "../lib/stores.js";
  import { getOrgSlug } from "../lib/auth.js";
  import { stageTitle } from "../lib/stages.js";

  let step = 1; // 1: source, 2: config, 3: running
  let ontologies = [];
  let showRequestForm = false;
  let requestName = "";
  let requestVersion = "";
  let requestUrl = "";
  let requestNotes = "";
  let requestSubmitted = false;
  let selectedOntology = "";
  let selectedVersion = "";
  let source = "";
  let files = [];
  let runId = null;
  let pipelineStatus = null;
  let polling = false;
  let stageElapsed = 0;
  let stageTimerInterval = null;
  let lastStage = null;

  $: {
    const stage = pipelineStatus?.stage;
    if (stage !== lastStage) {
      lastStage = stage;
      stageElapsed = 0;
      clearInterval(stageTimerInterval);
      if (stage && polling) {
        stageTimerInterval = setInterval(() => { stageElapsed += 1; }, 1000);
      }
    }
  }

  onDestroy(() => clearInterval(stageTimerInterval));
  let existingSources = [];
  let selectedSource = null; // existing source object or null for new upload
  let uploadMode = false;

  onMount(async () => {
    try {
      const [onts, sources] = await Promise.all([getOntologies(), listSources()]);
      ontologies = onts;
      existingSources = sources;
      if (ontologies.length) {
        selectedOntology = ontologies[0].key;
        selectedVersion = ontologies[0].versions[0];
      }
      // Pre-select if there's only one source, but stay on Step 1
      if (existingSources.length === 1) {
        selectExisting(existingSources[0]);
      }
    } catch (e) {
      showError(`Failed to load: ${e.message}`);
    }
  });

  $: org = $currentOrg;
  $: versions = ontologies.find((o) => o.key === selectedOntology)?.versions || [];
  $: if (versions.length && !versions.includes(selectedVersion)) selectedVersion = versions[0];
  $: canConfigure = (selectedSource || (uploadMode && files.length > 0 && source.trim()));

  function handleFiles(e) {
    files = Array.from(e.target.files);
  }

  function handleDrop(e) {
    e.preventDefault();
    files = Array.from(e.dataTransfer.files);
  }

  function selectExisting(src) {
    selectedSource = src;
    uploadMode = false;
    source = src.source_name;
  }

  function startUpload() {
    selectedSource = null;
    uploadMode = true;
    source = "";
    files = [];
  }

  function goToConfig() {
    step = 2;
  }

  async function handleStart() {
    try {
      // Upload new files first if needed
      if (uploadMode && files.length > 0) {
        await uploadFiles(source, files);
      }
      const result = await createRun({
        organization: org || "personal",
        source,
        target_ontology: selectedOntology,
        target_version: selectedVersion,
      });
      runId = result.run_id;
      step = 3;
      await startPipeline();
    } catch (e) {
      showError(`Failed: ${e.message}`);
    }
  }

  async function handleRequestSubmit() {
    try {
      await createOntologyRequest({
        name: requestName,
        version: requestVersion,
        reference_url: requestUrl,
        notes: requestNotes,
      });
      requestSubmitted = true;
      requestName = "";
      requestVersion = "";
      requestUrl = "";
      requestNotes = "";
    } catch (e) {
      showError(`Failed to submit request: ${e.message}`);
    }
  }

  async function startPipeline() {
    try {
      await executePipeline(runId);
      polling = true;
      pollStatus();
    } catch (e) {
      showError(`Failed to start pipeline: ${e.message}`);
    }
  }

  async function pollStatus() {
    if (!polling) return;
    try {
      const status = await getRunStatus(runId);
      pipelineStatus = status.pipeline;
      if (pipelineStatus?.status === "completed" || pipelineStatus?.status === "awaiting-review") {
        polling = false;
        clearInterval(stageTimerInterval);
        goToReview(runId);
      } else if (pipelineStatus?.status === "failed") {
        polling = false;
        clearInterval(stageTimerInterval);
        showError(`Pipeline failed at Stage ${pipelineStatus.stage}: ${pipelineStatus.error}`);
      } else {
        setTimeout(pollStatus, 2000);
      }
    } catch (e) {
      polling = false;
      showError(`Status check failed: ${e.message}`);
    }
  }
</script>

<div class="max-w-2xl mx-auto">
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
    <h1 class="text-2xl font-bold text-slate-900">New Pipeline Run</h1>
  </div>

  <!-- Progress steps -->
  <div class="flex items-center gap-2 mb-8">
    {#each [["Source", 1], ["Configure & Run", 2], ["Process", 3]] as [label, n]}
      <div class="flex items-center gap-2">
        <div
          class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium transition-colors"
          class:bg-indigo-600={step >= n}
          class:text-white={step >= n}
          class:bg-slate-200={step < n}
          class:text-slate-500={step < n}
        >
          {n}
        </div>
        <span class="text-sm text-slate-600">{label}</span>
        {#if n < 3}
          <div class="w-8 h-px bg-slate-300"></div>
        {/if}
      </div>
    {/each}
  </div>

  <!-- Step 1: Choose source -->
  {#if step === 1}
    <div class="bg-white border border-slate-200 rounded-lg p-6 space-y-4">
      <h2 class="text-sm font-semibold text-slate-700 uppercase tracking-wider">Select a Source</h2>

      <!-- Existing sources list -->
      {#if existingSources.length > 0}
        <div class="space-y-2">
          {#each existingSources as src}
            <button
              class="w-full text-left px-4 py-3 border rounded-lg transition-colors flex items-center gap-3"
              class:border-indigo-500={selectedSource?.package_name === src.package_name}
              class:bg-indigo-50={selectedSource?.package_name === src.package_name}
              class:ring-2={selectedSource?.package_name === src.package_name}
              class:ring-indigo-500={selectedSource?.package_name === src.package_name}
              class:border-slate-200={selectedSource?.package_name !== src.package_name}
              class:hover:border-slate-300={selectedSource?.package_name !== src.package_name}
              on:click={() => selectExisting(src)}
            >
              <div class="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center flex-shrink-0">
                <svg class="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                </svg>
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-sm font-medium text-slate-900">{src.source_name}</div>
                <div class="text-xs text-slate-500">{src.file_count} file{src.file_count !== 1 ? "s" : ""}</div>
              </div>
              {#if selectedSource?.package_name === src.package_name}
                <svg class="w-5 h-5 text-indigo-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
                </svg>
              {/if}
            </button>
          {/each}
        </div>

        <div class="flex items-center gap-3">
          <div class="flex-1 h-px bg-slate-200"></div>
          <span class="text-xs text-slate-400 uppercase">or</span>
          <div class="flex-1 h-px bg-slate-200"></div>
        </div>
      {/if}

      <!-- Upload new source -->
      {#if uploadMode}
        <div class="space-y-3 p-4 border border-indigo-200 bg-indigo-50 rounded-lg">
          <div>
            <label for="source-name-input" class="block text-xs font-medium text-slate-700 mb-1">Source Name</label>
            <input
              id="source-name-input"
              bind:value={source}
              type="text"
              placeholder="e.g., dbpi"
              class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                     focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <!-- Drop zone -->
          <!-- svelte-ignore a11y-no-static-element-interactions -->
          <div
            class="border-2 border-dashed border-slate-300 rounded-lg p-6 text-center bg-white
                   hover:border-indigo-400 transition-colors cursor-pointer"
            on:drop={handleDrop}
            on:dragover|preventDefault
          >
            <svg class="w-8 h-8 text-slate-400 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
            </svg>
            <p class="text-sm text-slate-600 mb-2">Drag and drop files, or</p>
            <label class="inline-block px-3 py-1.5 bg-white border border-slate-300 rounded-lg
                          text-sm font-medium text-slate-700 hover:bg-slate-50 cursor-pointer transition-colors">
              Browse
              <input type="file" multiple class="hidden" on:change={handleFiles} />
            </label>
          </div>

          {#if files.length > 0}
            <div class="text-sm text-slate-600">
              <strong>{files.length}</strong> file{files.length > 1 ? "s" : ""} selected:
              <ul class="mt-1 text-xs text-slate-500">
                {#each files as f}
                  <li>{f.name} ({(f.size / 1024).toFixed(1)} KB)</li>
                {/each}
              </ul>
            </div>
          {/if}
        </div>
      {:else}
        <button
          class="w-full px-4 py-3 border-2 border-dashed border-slate-300 rounded-lg text-sm
                 text-slate-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors"
          on:click={startUpload}
        >
          Upload new source files...
        </button>
      {/if}

      <div class="pt-2">
        <button
          class="w-full px-4 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg
                 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          disabled={!canConfigure}
          on:click={goToConfig}
        >
          Continue
        </button>
      </div>
    </div>

  <!-- Step 2: Configure target & start -->
  {:else if step === 2}
    <div class="bg-white border border-slate-200 rounded-lg p-6 space-y-4">
      <!-- Source summary -->
      <div class="p-3 bg-slate-50 border border-slate-200 rounded-lg flex items-center gap-3">
        <svg class="w-5 h-5 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
        </svg>
        <div class="text-sm">
          <span class="font-medium text-slate-900">{org || "personal"}</span>
          <span class="text-slate-400 mx-1">/</span>
          <span class="font-medium text-slate-900">{source}</span>
          {#if selectedSource}
            <span class="text-xs text-slate-500 ml-2">({selectedSource.file_count} files)</span>
          {:else}
            <span class="text-xs text-indigo-600 ml-2">(new upload — {files.length} files)</span>
          {/if}
        </div>
        <button
          class="ml-auto text-xs text-indigo-600 hover:text-indigo-800"
          on:click={() => step = 1}
        >
          Change
        </button>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label for="target-ontology-select" class="block text-sm font-medium text-slate-700 mb-1">Target Ontology</label>
          <select
            id="target-ontology-select"
            bind:value={selectedOntology}
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                   focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {#each ontologies as ont}
              <option value={ont.key}>{ont.name}</option>
            {/each}
          </select>
          <button
            class="mt-1 text-xs text-indigo-600 hover:text-indigo-800"
            on:click={() => { showRequestForm = true; requestSubmitted = false; }}
            type="button"
          >
            Don't see yours? Request one
          </button>
        </div>
        <div>
          <label for="target-version-select" class="block text-sm font-medium text-slate-700 mb-1">Version</label>
          <select
            id="target-version-select"
            bind:value={selectedVersion}
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                   focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {#each versions as v}
              <option value={v}>{v}</option>
            {/each}
          </select>
        </div>
      </div>

      <div class="pt-2">
        <button
          class="w-full px-4 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg
                 hover:bg-indigo-700 transition-colors"
          on:click={handleStart}
        >
          Start Pipeline
        </button>
      </div>
    </div>

  <!-- Step 3: Processing -->
  {:else if step === 3}
    <div class="bg-white border border-slate-200 rounded-lg p-6 text-center">
      {#if pipelineStatus?.status === "failed"}
        <div class="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg class="w-6 h-6 text-red-500" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
        </div>
        <h3 class="text-lg font-semibold text-red-800">Pipeline Failed</h3>
        <p class="text-sm text-red-600 mt-2 whitespace-pre-wrap">{pipelineStatus.error}</p>
        <button
          class="mt-4 px-4 py-2 text-sm text-slate-600 hover:text-slate-800 transition-colors"
          on:click={goToDashboard}
        >
          Back to Dashboard
        </button>
      {:else}
        <div class="w-12 h-12 border-4 border-slate-200 border-t-indigo-600 rounded-full animate-spin mx-auto mb-4"></div>
        <h3 class="text-lg font-semibold text-slate-900">Processing Pipeline</h3>
        <p class="text-sm text-slate-500 mt-1">
          {#if pipelineStatus?.stage}
            Running Stage {pipelineStatus.stage}: {stageTitle(pipelineStatus.stage)}
          {:else}
            Starting...
          {/if}
        </p>
        {#if stageElapsed > 0}
          <p class="text-sm font-mono text-indigo-600 mt-2">
            {Math.floor(stageElapsed / 60)}:{(stageElapsed % 60).toString().padStart(2, "0")}
          </p>
        {/if}
        <p class="text-xs text-slate-400 mt-3">
          This may take several minutes (Stage 3 performs semantic evaluation)
        </p>
      {/if}
    </div>
  {/if}
</div>

<!-- Ontology request modal -->
{#if showRequestForm}
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div
    class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
    on:click|self={() => showRequestForm = false}
  >
    <div class="bg-white rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
      {#if requestSubmitted}
        <div class="text-center py-4">
          <div class="w-12 h-12 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-3">
            <svg class="w-6 h-6 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
            </svg>
          </div>
          <h3 class="text-lg font-semibold text-slate-900">Request Submitted</h3>
          <p class="text-sm text-slate-500 mt-1">We'll notify you when the ontology is available.</p>
          <button
            class="mt-4 px-4 py-2 text-sm text-slate-600 hover:text-slate-800"
            on:click={() => showRequestForm = false}
          >
            Close
          </button>
        </div>
      {:else}
        <h3 class="text-lg font-semibold text-slate-900">Request a New Ontology</h3>
        <div>
          <label for="req-name" class="block text-sm font-medium text-slate-700 mb-1">Ontology Name *</label>
          <input
            id="req-name"
            bind:value={requestName}
            type="text"
            placeholder="e.g., HL7 FHIR"
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                   focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label for="req-version" class="block text-sm font-medium text-slate-700 mb-1">Version</label>
          <input
            id="req-version"
            bind:value={requestVersion}
            type="text"
            placeholder="e.g., R4"
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                   focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label for="req-url" class="block text-sm font-medium text-slate-700 mb-1">Reference URL</label>
          <input
            id="req-url"
            bind:value={requestUrl}
            type="text"
            placeholder="https://..."
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                   focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label for="req-notes" class="block text-sm font-medium text-slate-700 mb-1">Notes</label>
          <textarea
            id="req-notes"
            bind:value={requestNotes}
            rows="2"
            placeholder="Any additional context..."
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                   focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          ></textarea>
        </div>
        <div class="flex gap-2 pt-1">
          <button
            class="flex-1 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg
                   hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            disabled={!requestName.trim()}
            on:click={handleRequestSubmit}
          >
            Submit Request
          </button>
          <button
            class="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 transition-colors"
            on:click={() => showRequestForm = false}
          >
            Cancel
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
