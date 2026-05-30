<script setup lang="ts">
import { sanitizeJsonValue } from '@/utils/sanitizeJson'

defineProps<{
  observations: Record<string, any>[]
}>()

function sanitizeJson(value: unknown): string {
  return JSON.stringify(sanitizeJsonValue(value ?? {}), null, 2)
}
</script>

<template>
  <div class="observation-list">
    <article v-for="obs in observations" :key="obs.id || `${obs.tool_name}-${obs.skill_name}-${obs.round}`" class="observation-card">
      <div class="observation-card__line">
        <strong>{{ obs.tool_name || obs.skill_name || obs.observation_type || '--' }}</strong>
        <span :class="obs.ok ? 'is-ok' : 'is-failed'">{{ obs.ok ? 'ok' : 'failed' }}</span>
      </div>
      <p>{{ obs.data_summary || 'No summary' }}</p>
      <div v-if="obs.data_limitations?.length" class="observation-card__limitations">
        {{ obs.data_limitations.join('；') }}
      </div>
      <details>
        <summary>data preview</summary>
        <pre>{{ sanitizeJson(obs.data) }}</pre>
      </details>
    </article>
  </div>
</template>

<style scoped>
.observation-list {
  display: grid;
  gap: 10px;
}

.observation-card {
  padding: 10px;
  border: 1px solid rgba(125, 211, 252, 0.13);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.58);
}

.observation-card__line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.observation-card p,
.observation-card summary {
  color: #cbd5e1;
  font-size: 0.78rem;
}

.observation-card__limitations {
  color: #facc15;
  font-size: 0.76rem;
}

pre {
  max-height: 180px;
  overflow: auto;
  color: #bae6fd;
  font-size: 0.74rem;
}

.is-ok {
  color: #34d399;
}

.is-failed {
  color: #f87171;
}
</style>
