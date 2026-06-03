<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { sanitizeJsonValue } from '@/utils/sanitizeJson'

const props = withDefaults(
  defineProps<{
    value: unknown
    collapsed?: boolean
    title?: string
  }>(),
  {
    collapsed: false,
    title: '',
  },
)

const emit = defineEmits<{ 'update:collapsed': [value: boolean] }>()

const collapsedState = ref(props.collapsed)

watch(() => props.collapsed, (v) => { collapsedState.value = v })

function setCollapsed(value: boolean): void {
  collapsedState.value = value
  emit('update:collapsed', value)
}

const jsonText = computed(() => JSON.stringify(sanitizeJsonValue(props.value ?? null), null, 2))

defineExpose({ setCollapsed })
</script>

<template>
  <div class="json-block">
    <button v-if="title || collapsed" type="button" class="json-block__toggle" @click="setCollapsed(!collapsedState)">
      <span>{{ title || 'JSON' }}</span>
      <span class="pi" :class="collapsedState ? 'pi-chevron-down' : 'pi-chevron-up'" />
    </button>
    <pre v-if="!collapsedState">{{ jsonText }}</pre>
  </div>
</template>

<style scoped>
.json-block {
  min-width: 0;
}

.json-block__toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin-bottom: 8px;
  padding: 8px 10px;
  border: 1px solid rgba(129, 160, 207, 0.2);
  border-radius: var(--radius-sm);
  background: #0d1e33;
  color: var(--color-text-primary);
  cursor: pointer;
}

.json-block__toggle:hover {
  background: #112640;
}

pre {
  max-height: 420px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid rgba(129, 160, 207, 0.2);
  border-radius: var(--radius-sm);
  background: #060e1a;
  color: #c8d6e5;
  font-size: 0.8rem;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
