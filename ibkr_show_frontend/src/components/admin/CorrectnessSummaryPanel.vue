<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import Button from 'primevue/button'
import { fetchCorrectnessSummary } from '@/api/adminHarness'
import type {
  CorrectnessByAgent,
  CorrectnessByDimension,
  CorrectnessRecentFailure,
  CorrectnessSummary,
  CorrectnessSummaryResponse,
} from '@/types/adminHarness'

const summary = ref<CorrectnessSummary | null>(null)
const byAgent = ref<CorrectnessByAgent[]>([])
const byDimension = ref<CorrectnessByDimension[]>([])
const recentFailures = ref<CorrectnessRecentFailure[]>([])
const loading = ref(false)
const errorMessage = ref('')

const filters = reactive({
  agent_name: '',
  hours: 24 * 30,
  limit: 1000,
})

const summaryCards: { key: keyof CorrectnessSummary; label: string; format: 'int' | 'rate' | 'score' }[] = [
  { key: 'eval_run_count', label: 'Eval Run 数', format: 'int' },
  { key: 'judged_case_count', label: '被评测 Case 数', format: 'int' },
  { key: 'avg_overall_score', label: '平均 Overall Score', format: 'score' },
  { key: 'failed_dimension_count', label: '失败维度累计', format: 'int' },
  { key: 'high_risk_failure_count', label: '高风险失败', format: 'int' },
]

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const params: { agent_name?: string; hours?: number; limit?: number } = {
      hours: filters.hours,
      limit: filters.limit,
    }
    if (filters.agent_name.trim()) {
      params.agent_name = filters.agent_name.trim()
    }
    const response: CorrectnessSummaryResponse = await fetchCorrectnessSummary(params)
    summary.value = response.summary ?? null
    byAgent.value = Array.isArray(response.by_agent) ? response.by_agent : []
    byDimension.value = Array.isArray(response.by_dimension) ? response.by_dimension : []
    recentFailures.value = Array.isArray(response.recent_failures) ? response.recent_failures : []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载正确性报告失败'
  } finally {
    loading.value = false
  }
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  return value.toFixed(2)
}

function formatCardValue(card: { format: 'int' | 'rate' | 'score' }, value: number | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  if (card.format === 'int') return String(value)
  if (card.format === 'score') return formatScore(value)
  if (card.format === 'rate') return `${(value * 100).toFixed(1)}%`
  return String(value)
}

function formatList(items: string[] | undefined | null): string {
  if (!items || !items.length) return '-'
  return items.join(', ')
}

defineExpose({ load })
</script>

<template>
  <div class="correctness-panel">
    <div class="correctness-filters">
      <label>
        Agent
        <input v-model="filters.agent_name" placeholder="全部 Agent" />
      </label>
      <label>
        Hours
        <input v-model.number="filters.hours" type="number" min="1" max="8760" />
      </label>
      <label>
        Limit
        <input v-model.number="filters.limit" type="number" min="1" max="5000" />
      </label>
      <Button label="刷新正确性报告" icon="pi pi-refresh" class="p-button--accent" :loading="loading" @click="load" />
    </div>

    <p v-if="errorMessage" class="correctness-error">{{ errorMessage }}</p>

    <section class="correctness-section">
      <h4 class="correctness-section__title">总览卡片</h4>
      <div v-if="summary" class="correctness-summary-grid">
        <article v-for="card in summaryCards" :key="card.key" class="correctness-card">
          <span>{{ card.label }}</span>
          <strong>{{ formatCardValue(card, summary[card.key]) }}</strong>
        </article>
      </div>
      <div v-else class="empty-state">暂无汇总数据</div>
    </section>

    <section class="correctness-section">
      <h4 class="correctness-section__title">By Agent（按 Agent 聚合）</h4>
      <div class="table-shell">
        <table class="correctness-table">
          <thead>
            <tr>
              <th>agent_name</th>
              <th>judged_case_count</th>
              <th>avg_overall_score</th>
              <th>weakest_dimensions</th>
              <th>failed_count</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in byAgent" :key="row.agent_name">
              <td><code>{{ row.agent_name }}</code></td>
              <td>{{ row.judged_case_count ?? '-' }}</td>
              <td>{{ formatScore(row.avg_overall_score) }}</td>
              <td>{{ formatList(row.weakest_dimensions) }}</td>
              <td>{{ row.failed_count ?? '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!byAgent.length" class="empty-state">暂无 Agent 数据</div>
    </section>

    <section class="correctness-section">
      <h4 class="correctness-section__title">By Dimension（按维度聚合）</h4>
      <div class="table-shell">
        <table class="correctness-table">
          <thead>
            <tr>
              <th>dimension</th>
              <th>avg_score</th>
              <th>failed_count</th>
              <th>warning_count</th>
              <th>affected_agents</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in byDimension" :key="row.dimension">
              <td><code>{{ row.dimension }}</code></td>
              <td>{{ formatScore(row.avg_score) }}</td>
              <td>{{ row.failed_count ?? '-' }}</td>
              <td>{{ row.warning_count ?? '-' }}</td>
              <td>{{ formatList(row.affected_agents) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!byDimension.length" class="empty-state">暂无维度数据</div>
    </section>

    <section class="correctness-section">
      <h4 class="correctness-section__title">Recent Failures（最近失败 Case）</h4>
      <div class="table-shell">
        <table class="correctness-table">
          <thead>
            <tr>
              <th>eval_run_id</th>
              <th>case_id</th>
              <th>agent_name</th>
              <th>failed_dimensions</th>
              <th>failure_reasons</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in recentFailures" :key="`${row.eval_run_id}-${row.case_id}`">
              <td><code>{{ row.eval_run_id || '-' }}</code></td>
              <td><code>{{ row.case_id || '-' }}</code></td>
              <td>{{ row.agent_name || '-' }}</td>
              <td>{{ formatList(row.failed_dimensions) }}</td>
              <td>{{ formatList(row.failure_reasons) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!recentFailures.length" class="empty-state">暂无最近失败</div>
    </section>
  </div>
</template>

<style scoped>
.correctness-panel {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.correctness-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
}

.correctness-filters label {
  display: flex;
  flex-direction: column;
  font-size: 0.85rem;
  color: var(--text-color-secondary, #5b6b80);
  gap: 0.25rem;
}

.correctness-filters input[type='text'],
.correctness-filters input[type='number'],
.correctness-filters input:not([type]) {
  min-width: 160px;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--surface-border, #d6dde6);
  border-radius: 4px;
  background: var(--surface-card, #fff);
  color: inherit;
  font-size: 0.85rem;
}

.correctness-error {
  background: rgba(220, 53, 69, 0.1);
  color: #b02a37;
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  font-size: 0.85rem;
}

.correctness-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.75rem;
}

.correctness-card {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.75rem 1rem;
  background: var(--surface-card, #f7f9fc);
  border: 1px solid var(--surface-border, #e1e6ee);
  border-radius: 6px;
}

.correctness-card span {
  font-size: 0.8rem;
  color: var(--text-color-secondary, #5b6b80);
}

.correctness-card strong {
  font-size: 1.1rem;
  color: var(--text-color, #1a2333);
}

.correctness-section {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.correctness-section__title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-color, #1a2333);
}

.correctness-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.correctness-table th,
.correctness-table td {
  padding: 0.45rem 0.6rem;
  text-align: left;
  border-bottom: 1px solid var(--surface-border, #e1e6ee);
}

.correctness-table th {
  background: var(--surface-100, #f4f6fa);
  color: var(--text-color-secondary, #5b6b80);
  font-weight: 600;
}

.correctness-table code {
  font-family: 'SFMono-Regular', Menlo, Consolas, monospace;
  font-size: 0.8rem;
  color: var(--primary-color, #2563eb);
  background: rgba(37, 99, 235, 0.08);
  padding: 0.05rem 0.35rem;
  border-radius: 3px;
}

.table-shell {
  overflow-x: auto;
  border: 1px solid var(--surface-border, #e1e6ee);
  border-radius: 4px;
  background: var(--surface-card, #fff);
}

.empty-state {
  text-align: center;
  color: var(--text-color-secondary, #5b6b80);
  font-size: 0.85rem;
  padding: 0.75rem;
}
</style>
