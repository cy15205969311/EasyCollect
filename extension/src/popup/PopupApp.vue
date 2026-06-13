<script setup lang="ts">
const backendUrl = "http://localhost:8000";
</script>

<template>
  <main class="w-80 bg-slate-950 p-4 text-slate-100">
    <header class="border-b border-slate-800 pb-3">
      <p class="text-xs uppercase tracking-wide text-emerald-300">EasyCollect</p>
      <h1 class="mt-1 text-lg font-semibold">EasyCollect Assistant</h1>
    </header>

    <section class="space-y-3 py-4 text-sm text-slate-300">
      <p>The extension is ready to capture product JSON on 1688 detail pages.</p>
      <p class="rounded-md bg-slate-900 px-3 py-2 font-mono text-xs text-emerald-200">
        {{ backendUrl }}
      </p>
    </section>
  </main>
</template>
