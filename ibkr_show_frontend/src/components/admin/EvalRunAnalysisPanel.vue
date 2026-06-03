<script setup lang="ts">
import { computed } from 'vue'
import Tag from 'primevue/tag'
import type { EvalCaseResult, EvalRun } from '@/types/adminHarness'

const props = defineProps<{
  run: EvalRun
}>()

const summary = computed(() => props.run.summary ?? {})
const results = computed(() => props.run.results ?? [])

const statusCounts = computed(() => summary.value.status_counts as Record<string, number> ?? {})
const severityCounts = computed(() => summary.value.severity_counts as Record<string, number> ?? {})
const categoryCounts = computed(() => summary.value.category_counts as Record<string, number> ?? {})
const failedCheckCounts = computed(() => summary.value.failed_check_counts as Record<string, number> ?? {})
const failedCases = computed(() => summary.value.failed_cases as Array<Record<string, unknown>> ?? [])

const topFailedChecks = computed(() => {
  return Object.entries(failedCheckCounts.value)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
})

function formatRate(value?: unknown): string {
  if (value === null || value === undefined || typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function formatNumber(value?: unknown): string {
  if (value === null || value === undefined || typeof value !== 'number' || Number.isNaN(value)) return '-'
  return new Intl.NumberFormat('zh-CN').format(value)
}

function statusClass(status?: string | null): string {
  if (status === 'passed') return 'p-tag--positive'
  if (status === 'warning') return 'p-tag--warning'
  if (status === 'failed' || status === 'error') return 'p-tag--negative'
  return 'p-tag--accent'
}

function severityClass(severity?: string | null): string {
  if (severity === 'critical') return 'p-tag--negative'
  if (severity === 'high') return 'p-tag--warning'
  if (severity === 'low') return 'p-tag--info'
  return 'p-tag--accent'
}

function failedChecksForResult(result: EvalCaseResult): string[] {
  return (result.checks ?? [])
    .filter((c) => c.passed === false)
    .map((c) => c.check_name ?? 'unknown')
}

function resultMetadata(result: EvalCaseResult): Record<string, unknown> {
  return (result.metadata ?? {}) as Record<string, unknown>
}

function resultScope(result: EvalCaseResult): string {
  const meta = resultMetadata(result)
  return String(meta.eval_scope ?? 'agent')
}

function resultNodeName(result: EvalCaseResult): string {
  const meta = resultMetadata(result)
  const value = meta.node_name
  return value ? String(value) : '-'
}

const nodeSummary = computed(() => {
  let nodeCaseCount = 0
  const nodeNames: string[] = []
  for (const r of results.value as EvalCaseResult[]) {
    if (resultScope(r) === 'node') {
      nodeCaseCount += 1
      const name = resultNodeName(r)
      if (name && name !== '-' && !nodeNames.includes(name)) {
        nodeNames.push(name)
      }
    }
  }
  return {
    node_case_count: nodeCaseCount,
    nodes: nodeNames,
    has_node_cases: nodeCaseCount > 0,
  }
})
</script>

<template>
  <div class="eval-run-analysis">
    <section class="eval-run-analysis__section">
      <h4 class="eval-run-analysis__title">总览</h4>
      <div class="eval-run-analysis__cards">
        <article class="eval-run-analysis__card">
          <span>总 Case</span>
          <strong>{{ formatNumber(summary.case_count) }}</strong>
        </article>
        <article class="eval-run-analysis__card">
          <span>通过率</span>
          <strong>{{ formatRate(summary.pass_rate) }}</strong>
        </article>
        <article class="eval-run-analysis__card">
          <span>分数率</span>
          <strong>{{ formatRate(summary.score_rate) }}</strong>
        </article>
        <article class="eval-run-analysis__card">
          <span>Passed</span>
          <strong class="color-positive">{{ formatNumber(summary.passed_count) }}</strong>
        </article>
        <article class="eval-run-analysis__card">
          <span>Warning</span>
          <strong class="color-warning">{{ formatNumber(summary.warning_count) }}</strong>
        </article>
        <article class="eval-run-analysis__card">
          <span>Failed</span>
          <strong class="color-negative">{{ formatNumber(summary.failed_count) }}</strong>
        </article>
        <article class="eval-run-analysis__card">
          <span>Error</span>
          <strong class="color-negative">{{ formatNumber(summary.error_count) }}</strong>
        </article>
        <article class="eval-run-analysis__card">
          <span>High/Critical 失败</span>
          <strong class="color-negative">{{ formatNumber(summary.high_priority_failure_count) }}</strong>
        </article>
      </div>
    </section>

    <section v-if="Object.keys(severityCounts).length" class="eval-run-analysis__section">
      <h4 class="eval-run-analysis__title">按 Severity 统计</h4>
      <div class="eval-run-analysis__tags">
        <Tag v-for="(count, severity) in severityCounts" :key="severity" :value="`${severity}: ${count}`" :class="severityClass(severity)" />
      </div>
    </section>

    <section v-if="Object.keys(categoryCounts).length" class="eval-run-analysis__section">
      <h4 class="eval-run-analysis__title">按 Category 统计</h4>
      <div class="eval-run-analysis__tags">
        <Tag v-for="(count, category) in categoryCounts" :key="category" :value="`${category === 'uncategorized' ? '未分类' : category}: ${count}`" />
      </div>
    </section>

    <section v-if="topFailedChecks.length" class="eval-run-analysis__section">
      <h4 class="eval-run-analysis__title">失败检查项 Top</h4>
      <table class="eval-run-analysis__table">
        <thead><tr><th>Check</th><th>失败次数</th></tr></thead>
        <tbody>
          <tr v-for="[name, count] in topFailedChecks" :key="name">
            <td><code>{{ name }}</code></td>
            <td>{{ count }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!topFailedChecks.length" class="empty-state">暂无失败检查项</div>
    </section>

    <section v-if="failedCases.length" class="eval-run-analysis__section">
      <h4 class="eval-run-analysis__title">失败 Case 列表</h4>
      <table class="eval-run-analysis__table">
        <thead><tr><th>case_id</th><th>status</th><th>severity</th><th>category</th><th>failed_checks</th><th>message</th></tr></thead>
        <tbody>
          <tr v-for="fc in failedCases" :key="String(fc.case_id)">
            <td><code>{{ fc.case_id }}</code></td>
            <td><Tag :value="String(fc.status)" :class="statusClass(String(fc.status))" /></td>
            <td><Tag :value="String(fc.severity)" :class="severityClass(String(fc.severity))" /></td>
            <td>{{ fc.category || '-' }}</td>
            <td>{{ (fc.failed_checks as string[])?.join(', ') || '-' }}</td>
            <td>{{ fc.message || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="nodeSummary.has_node_cases" class="eval-run-analysis__section">
      <h4 class="eval-run-analysis__title">Node Eval Summary</h4>
      <div class="eval-run-analysis__node-summary">
        <div><span>Node Cases</span><strong>{{ nodeSummary.node_case_count }}</strong></div>
        <div><span>Nodes</span><strong>{{ nodeSummary.nodes.join(', ') || '-' }}</strong></div>
      </div>
    </section>

    <section v-if="results.length" class="eval-run-analysis__section">
      <h4 class="eval-run-analysis__title">结果列表</h4>
      <table class="eval-run-analysis__table">
        <thead>
          <tr>
            <th>case_id</th>
            <th>agent</th>
            <th>scope</th>
            <th>node_name</th>
            <th>status</th>
            <th>severity</th>
            <th>category</th>
            <th>score</th>
            <th>failed_checks</th>
            <th>error</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in results" :key="String(r.case_id)">
            <td><code>{{ r.case_id }}</code></td>
            <td>{{ r.agent_name || '-' }}</td>
            <td>
              <Tag v-if="resultScope(r) === 'node'" value="NODE" class="p-tag--info" />
              <Tag v-else value="AGENT" class="p-tag--secondary" />
            </td>
            <td>{{ resultNodeName(r) }}</td>
            <td><Tag :value="r.status || '-'" :class="statusClass(r.status ?? null)" /></td>
            <td><Tag :value="String(resultMetadata(r).severity || 'medium')" :class="severityClass(String(resultMetadata(r).severity || 'medium'))" /></td>
            <td>{{ resultMetadata(r).category || '-' }}</td>
            <td>{{ r.score ?? 0 }} / {{ r.max_score ?? 0 }}</td>
            <td>{{ failedChecksForResult(r).join(', ') || '-' }}</td>
            <td>{{ r.error_code ? String(r.error_code) : '-' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.eval-run-analysis {
  display: grid;
  gap: var(--space-4);
}

.eval-run-analysis__section {
  display: grid;
  gap: 8px;
}

.eval-run-analysis__title {
  margin: 0;
  font-size: 0.9rem;
  color: var(--color-text-secondary);
}

.eval-run-analysis__cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}

.eval-run-analysis__card {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
}

.eval-run-analysis__card span {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}

.eval-run-analysis__card strong {
  font-size: 1.1rem;
}

.eval-run-analysis__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.eval-run-analysis__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}

.eval-run-analysis__table th,
.eval-run-analysis__table td {
  padding: 8px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.1);
  text-align: left;
}

.eval-run-analysis__table th {
  color: var(--color-text-secondary);
  font-weight: 700;
}

.color-positive {
  color: var(--color-positive);
}

.color-warning {
  color: var(--color-warning);
}

.color-negative {
  color: var(--color-negative);
}

.eval-run-analysis__node-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}

.eval-run-analysis__node-summary > div {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
}

.eval-run-analysis__node-summary span {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}
</style>
