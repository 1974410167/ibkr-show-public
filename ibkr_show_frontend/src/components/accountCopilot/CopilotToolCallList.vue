<script setup lang="ts">
import { sanitizeJsonValue } from '@/utils/sanitizeJson'

defineProps<{
  toolCalls: Record<string, any>[]
}>()

function sanitizeJson(value: unknown): string {
  return JSON.stringify(sanitizeJsonValue(value ?? {}), null, 2)
}
</script>

<template>
  <div class="trace-list">
    <article v-for="call in toolCalls" :key="call.id || `${call.tool_name}-${call.round}`" class="trace-card">
      <div class="trace-card__line">
        <strong>{{ call.tool_name || '--' }}</strong>
        <span :class="call.ok ? 'is-ok' : 'is-failed'">{{ call.ok ? 'ok' : 'failed' }}</span>
      </div>
      <p>round {{ call.round ?? '--' }} · {{ call.latency_ms ?? '--' }}ms</p>
      <details>
        <summary>arguments</summary>
        <pre>{{ sanitizeJson(call.arguments) }}</pre>
      </details>
    </article>
  </div>
</template>

<style scoped>
.trace-list {
  display: grid;
  gap: 10px;
}

.trace-card {
  padding: 10px;
  border: 1px solid rgba(125, 211, 252, 0.13);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.58);
}

.trace-card__line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.trace-card p,
.trace-card summary {
  color: #94a3b8;
  font-size: 0.78rem;
}

pre {
  max-height: 180px;
  overflow: auto;
  color: #c4b5fd;
  font-size: 0.74rem;
}

.is-ok {
  color: #34d399;
}

.is-failed {
  color: #f87171;
}
</style>
