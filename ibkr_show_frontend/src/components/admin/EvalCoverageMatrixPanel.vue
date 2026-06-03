<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import { getEvalCoverage } from '@/api/adminHarness'
import type { EvalCaseCoverageRow, EvalCoverageResponse } from '@/types/adminHarness'

const emit = defineEmits<{
  openCase: [caseId: string]
  openRun: [runId: string]
  filterAgent: [agentName: string]
  filterNode: [agentName: string, nodeName: string]
}>()

const coverage = ref<EvalCoverageResponse | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const filters = reactive({
  agent_name: '',
  hours: 720,
  limit: 1000,
  include_disabled: true,
})

const summaryCards = [
  { key: 'case_count', label: 'Case 总数' },
  { key: 'enabled_case_count', label: 'Enabled Case' },
  { key: 'disabled_case_count', label: 'Disabled Case' },
  { key: 'agent_count', label: 'Agent 数' },
  { key: 'judge_case_count', label: 'Judge Case' },
  { key: 'replay_source_count', label: 'Replay 来源' },
  { key: 'manual_source_count', label: 'Manual 来源' },
  { key: 'bad_case_source_count', label: 'Bad Case 来源' },
  { key: 'recent_eval_run_count', label: '最近 Eval Run' },
  { key: 'recent_evaluated_case_count', label: '最近被评测 Case' },
  { key: 'never_evaluated_case_count', label: '统计窗口内未运行 Case' },
] as const

interface NodeCoverageRow {
  agent_name: string
  node_name: string
  case_count: number
  enabled_case_count: number
  judge_case_count: number
  recent_pass_rate: number | null
  recent_failed_count: number
  never_evaluated_case_count: number
}

const nodeCoverageRows = computed<NodeCoverageRow[]>(() => {
  if (!coverage.value) return []
  const rows = (coverage.value.case_coverage ?? []) as EvalCaseCoverageRow[]
  const buckets = new Map<string, NodeCoverageRow>()
  for (const row of rows) {
    if (row.eval_scope !== 'node') continue
    const agent = row.agent_name || 'unknown'
    const node = row.node_name || '(unnamed)'
    const key = `${agent}::${node}`
    let bucket = buckets.get(key)
    if (!bucket) {
      bucket = {
        agent_name: agent,
        node_name: node,
        case_count: 0,
        enabled_case_count: 0,
        judge_case_count: 0,
        recent_pass_rate: null,
        recent_failed_count: 0,
        never_evaluated_case_count: 0,
      }
      buckets.set(key, bucket)
    }
    bucket.case_count += 1
    if (row.enabled !== false) bucket.enabled_case_count += 1
    if (row.judge_enabled) bucket.judge_case_count += 1
    if (row.never_evaluated) bucket.never_evaluated_case_count += 1
    const runs = row.recent_run_count ?? 0
    const passes = row.recent_pass_count ?? 0
    if (runs > 0) {
      const existing = bucket.recent_pass_rate ?? 0
      const existingCount = bucket.case_count - 1
      const newRate = passes / runs
      const totalRuns = (bucket.recent_pass_rate !== null ? existing * Math.max(1, existingCount) : 0) + runs
      const totalPasses = (bucket.recent_pass_rate !== null ? existing * Math.max(1, existingCount) : 0) + passes
      bucket.recent_pass_rate = totalRuns > 0 ? totalPasses / totalRuns : null
    }
    bucket.recent_failed_count += row.recent_failed_count ?? 0
  }
  return Array.from(buckets.values()).sort(
    (a, b) => a.agent_name.localeCompare(b.agent_name) || a.node_name.localeCompare(b.node_name),
  )
})

async function load(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    coverage.value = await getEvalCoverage(filters)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载覆盖矩阵失败'
  } finally {
    loading.value = false
  }
}

function formatRate(value?: number | null): string {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function severityClass(severity?: string | null): string {
  if (severity === 'critical') return 'p-tag--danger'
  if (severity === 'high') return 'p-tag--warning'
  if (severity === 'low') return 'p-tag--info'
  return 'p-tag--secondary'
}

function rowNodeName(row: EvalCaseCoverageRow): string {
  return row.node_name || '-'
}

function rowScopeTagClass(scope?: string | null): string {
  return scope === 'node' ? 'p-tag--info' : 'p-tag--secondary'
}

function rowScopeLabel(scope?: string | null): string {
  return scope === 'node' ? 'NODE' : 'AGENT'
}

function gapNodeName(gap: { metadata?: Record<string, unknown> } & Record<string, unknown>): string {
  const fromMeta = gap.metadata?.node_name
  if (fromMeta) return String(fromMeta)
  return '-'
}

function recNodeName(rec: { metadata?: Record<string, unknown> } & Record<string, unknown>): string {
  const fromMeta = rec.metadata?.node_name
  if (fromMeta) return String(fromMeta)
  return '-'
}

defineExpose({ load })
</script>

<template>
  <div class="coverage-matrix">
    <div class="coverage-filters">
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
      <label class="checkbox-label">
        <input v-model="filters.include_disabled" type="checkbox" />
        包含禁用 Case
      </label>
      <Button label="刷新覆盖矩阵" icon="pi pi-refresh" class="p-button--accent" :loading="loading" @click="load" />
    </div>

    <p v-if="errorMessage" class="coverage-error">{{ errorMessage }}</p>

    <template v-if="coverage">
      <div class="coverage-summary-grid">
        <article v-for="card in summaryCards" :key="card.key" class="coverage-card">
          <span>{{ card.label }}</span>
          <strong>{{ coverage.summary[card.key] ?? '-' }}</strong>
        </article>
      </div>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Agent 覆盖总览</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead>
              <tr>
                <th>agent_name</th><th>case_count</th><th>enabled</th><th>judge</th>
                <th>high</th><th>critical</th><th>eval_runs</th><th>pass_rate</th>
                <th>failed</th><th>errors</th><th>high_crit_fail</th><th>未运行</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in coverage.by_agent" :key="row.agent_name">
                <td><code class="clickable" @click="emit('filterAgent', row.agent_name)">{{ row.agent_name }}</code></td>
                <td>{{ row.case_count ?? '-' }}</td>
                <td>{{ row.enabled_case_count ?? '-' }}</td>
                <td>{{ row.judge_case_count ?? '-' }}</td>
                <td>{{ row.high_case_count ?? '-' }}</td>
                <td>{{ row.critical_case_count ?? '-' }}</td>
                <td>{{ row.recent_eval_run_count ?? '-' }}</td>
                <td>{{ formatRate(row.recent_pass_rate) }}</td>
                <td>{{ row.recent_failed_count ?? '-' }}</td>
                <td>{{ row.recent_error_count ?? '-' }}</td>
                <td :class="{ 'coverage-danger': (row.high_critical_failure_count ?? 0) > 0 }">{{ row.high_critical_failure_count ?? '-' }}</td>
                <td :class="{ 'coverage-warning': (row.never_evaluated_case_count ?? 0) > 0 }">{{ row.never_evaluated_case_count ?? '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.by_agent.length" class="empty-state">暂无数据</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Agent × Category</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead><tr><th>agent</th><th>category</th><th>cases</th><th>enabled</th><th>high</th><th>critical</th><th>pass_rate</th><th>failed</th></tr></thead>
            <tbody>
              <tr v-for="row in coverage.by_agent_category" :key="`${row.agent_name}-${row.category}`">
                <td>{{ row.agent_name }}</td><td>{{ row.category }}</td>
                <td>{{ row.case_count ?? '-' }}</td><td>{{ row.enabled_case_count ?? '-' }}</td>
                <td>{{ row.high_case_count ?? '-' }}</td><td>{{ row.critical_case_count ?? '-' }}</td>
                <td>{{ formatRate(row.recent_pass_rate) }}</td><td>{{ row.recent_failed_count ?? '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.by_agent_category.length" class="empty-state">暂无数据</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Agent × Severity</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead><tr><th>agent</th><th>severity</th><th>cases</th><th>enabled</th><th>pass_rate</th><th>failed</th></tr></thead>
            <tbody>
              <tr v-for="row in coverage.by_agent_severity" :key="`${row.agent_name}-${row.severity}`">
                <td>{{ row.agent_name }}</td>
                <td><Tag :value="row.severity" :class="severityClass(row.severity)" /></td>
                <td>{{ row.case_count ?? '-' }}</td><td>{{ row.enabled_case_count ?? '-' }}</td>
                <td>{{ formatRate(row.recent_pass_rate) }}</td><td>{{ row.recent_failed_count ?? '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.by_agent_severity.length" class="empty-state">暂无数据</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Agent × Tag</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead><tr><th>agent</th><th>tag</th><th>cases</th><th>enabled</th><th>pass_rate</th></tr></thead>
            <tbody>
              <tr v-for="row in coverage.by_agent_tag" :key="`${row.agent_name}-${row.tag}`">
                <td>{{ row.agent_name }}</td><td>{{ row.tag }}</td>
                <td>{{ row.case_count ?? '-' }}</td><td>{{ row.enabled_case_count ?? '-' }}</td>
                <td>{{ formatRate(row.recent_pass_rate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.by_agent_tag.length" class="empty-state">暂无数据</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Case 来源分布</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead><tr><th>source</th><th>cases</th><th>enabled</th></tr></thead>
            <tbody>
              <tr v-for="row in coverage.by_source" :key="row.source">
                <td>{{ row.source }}</td><td>{{ row.case_count ?? '-' }}</td><td>{{ row.enabled_case_count ?? '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.by_source.length" class="empty-state">暂无数据</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Case 覆盖明细</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead>
              <tr>
                <th>case_id</th><th>agent</th><th>scope</th><th>node_name</th>
                <th>title</th><th>enabled</th>
                <th>severity</th><th>category</th><th>tags</th><th>source</th>
                <th>prompt_key</th><th>model</th>
                <th>judge</th><th>last_status</th><th>score</th>
                <th>evaluated_at</th><th>runs</th><th>failed</th><th>未运行</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in coverage.case_coverage" :key="row.case_id">
                <td><code class="clickable" @click="emit('openCase', row.case_id)">{{ row.case_id }}</code></td>
                <td>{{ row.agent_name || '-' }}</td>
                <td><Tag :value="rowScopeLabel(row.eval_scope)" :class="rowScopeTagClass(row.eval_scope)" /></td>
                <td>{{ rowNodeName(row) }}</td>
                <td>{{ row.title || '-' }}</td>
                <td><Tag :value="row.enabled === false ? '禁用' : '启用'" :class="row.enabled === false ? 'p-tag--warning' : 'p-tag--positive'" /></td>
                <td><Tag :value="row.severity || '-'" :class="severityClass(row.severity)" /></td>
                <td>{{ row.category || '-' }}</td>
                <td>{{ (row.tags || []).join(', ') || '-' }}</td>
                <td>{{ row.source || '-' }}</td>
                <td>{{ row.prompt_key || '-' }}</td>
                <td>{{ row.model || '-' }}</td>
                <td><Tag v-if="row.judge_enabled" value="LLM Judge" class="p-tag--info" /><span v-else>-</span></td>
                <td>
                  <code v-if="row.last_eval_run_id" class="clickable" @click="emit('openRun', row.last_eval_run_id)">{{ row.last_status || '-' }}</code>
                  <span v-else>{{ row.last_status || '-' }}</span>
                </td>
                <td>{{ row.last_score != null ? `${row.last_score}/${row.last_max_score ?? '-'}` : '-' }}</td>
                <td>{{ row.last_evaluated_at || '-' }}</td>
                <td>{{ row.recent_run_count ?? 0 }}</td>
                <td>{{ row.recent_failed_count ?? 0 }}</td>
                <td><Tag v-if="row.never_evaluated" value="统计窗口内未运行" class="p-tag--warning" /><span v-else>-</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.case_coverage.length" class="empty-state">暂无数据</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Node Coverage</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead>
              <tr>
                <th>agent_name</th><th>node_name</th><th>case_count</th>
                <th>enabled_case_count</th><th>judge_case_count</th>
                <th>recent_pass_rate</th><th>recent_failed_count</th><th>never_evaluated_case_count</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in nodeCoverageRows" :key="`${row.agent_name}-${row.node_name}`">
                <td><code class="clickable" @click="emit('filterAgent', row.agent_name)">{{ row.agent_name }}</code></td>
                <td><code class="clickable" @click="emit('filterNode', row.agent_name, row.node_name)">{{ row.node_name }}</code></td>
                <td>{{ row.case_count }}</td>
                <td>{{ row.enabled_case_count }}</td>
                <td>{{ row.judge_case_count }}</td>
                <td>{{ formatRate(row.recent_pass_rate) }}</td>
                <td>{{ row.recent_failed_count }}</td>
                <td>{{ row.never_evaluated_case_count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!nodeCoverageRows.length" class="empty-state">暂无 Node Eval 覆盖数据</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Coverage Gaps</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead>
              <tr>
                <th>gap_id</th><th>agent</th><th>node_name</th><th>gap_type</th><th>severity</th>
                <th>category</th><th>title</th><th>description</th><th>suggested_action</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="gap in coverage.gaps" :key="gap.gap_id">
                <td><code>{{ gap.gap_id }}</code></td>
                <td><code class="clickable" @click="emit('filterAgent', gap.agent_name)">{{ gap.agent_name }}</code></td>
                <td>{{ gapNodeName(gap as Record<string, unknown>) }}</td>
                <td><code>{{ gap.gap_type }}</code></td>
                <td><Tag :value="gap.severity" :class="severityClass(gap.severity)" /></td>
                <td>{{ gap.category }}</td>
                <td>{{ gap.title }}</td>
                <td>{{ gap.description }}</td>
                <td>{{ gap.suggested_action }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.gaps.length" class="empty-state">暂无覆盖缺口</div>
      </section>

      <section class="coverage-section">
        <h4 class="coverage-section__title">Recommendations</h4>
        <div class="table-shell">
          <table class="coverage-table">
            <thead>
              <tr>
                <th>recommendation_id</th><th>agent</th><th>node_name</th><th>priority</th>
                <th>action_type</th><th>title</th><th>description</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rec in coverage.recommendations" :key="rec.recommendation_id">
                <td><code>{{ rec.recommendation_id }}</code></td>
                <td><code class="clickable" @click="emit('filterAgent', rec.agent_name)">{{ rec.agent_name }}</code></td>
                <td>{{ recNodeName(rec as Record<string, unknown>) }}</td>
                <td><Tag :value="rec.priority" :class="severityClass(rec.priority)" /></td>
                <td><code>{{ rec.action_type }}</code></td>
                <td>{{ rec.title }}</td>
                <td>{{ rec.description }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="!coverage.recommendations.length" class="empty-state">暂无建议</div>
      </section>
    </template>

    <div v-else-if="!loading && !errorMessage" class="empty-state">暂无覆盖数据，点击"刷新覆盖矩阵"加载。</div>
  </div>
</template>

<style scoped>
.coverage-matrix {
  display: grid;
  gap: var(--space-4);
}

.coverage-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
}

.coverage-filters label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.8rem;
  color: var(--text-color-secondary, #aaa);
}

.coverage-filters label.checkbox-label {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}

.coverage-filters input,
.coverage-filters select {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--surface-border, #444);
  border-radius: 4px;
  background: var(--surface-ground, #111);
  color: var(--text-color, #eee);
  font-size: 0.85rem;
}

.coverage-filters input[type="number"] {
  width: 5rem;
}

.coverage-error {
  color: #f87171;
  font-size: 0.85rem;
}

.coverage-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.coverage-card {
  padding: 14px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-md, 8px);
  background: rgba(10, 18, 32, 0.46);
  display: grid;
  gap: 4px;
}

.coverage-card span {
  font-size: 0.78rem;
  color: var(--text-color-secondary, #aaa);
}

.coverage-card strong {
  font-size: 1.1rem;
}

.coverage-section {
  display: grid;
  gap: 10px;
}

.coverage-section__title {
  margin: 0;
  font-size: 1rem;
}

.coverage-warning {
  color: #fbbf24;
  font-weight: 600;
}

.coverage-danger {
  color: #f87171;
  font-weight: 600;
}

.coverage-table {
  width: 100%;
  min-width: 900px;
  border-collapse: collapse;
}

.coverage-table th,
.coverage-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.1);
  text-align: left;
  font-size: 0.82rem;
}

.coverage-table th {
  color: var(--text-color-secondary, #aaa);
  font-size: 0.75rem;
  text-transform: uppercase;
}

.clickable {
  cursor: pointer;
  color: var(--color-accent, #59c9a5);
}

.clickable:hover {
  text-decoration: underline;
}
</style>
