<!--
  This app runs with a single fixed local user, so the sign-in page is
  normally bypassed (App.svelte routes straight to the dashboard). It
  remains as a harmless fallback / loading state.
-->
<div class="min-h-screen flex flex-col items-center justify-center -mt-16">
  <div class="mb-8 text-center">
    <div class="w-16 h-16 bg-indigo-600 rounded-xl flex items-center justify-center mx-auto mb-4">
      <span class="text-white font-bold text-2xl">OM</span>
    </div>
    <h1 class="text-2xl font-bold text-slate-900">OntologyMapper</h1>
    <p class="text-slate-500 mt-1">Semantic alignment pipeline</p>
  </div>
</div>
