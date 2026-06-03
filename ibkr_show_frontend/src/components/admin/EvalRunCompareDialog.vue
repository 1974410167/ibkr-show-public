<script setup lang="ts">
import { computed } from 'vue'
import Tag from 'primevue/tag'
import HarnessDetailDialog from './HarnessDetailDialog.vue'

const props = defineProps<{
  visible: boolean
  result: Record<string, unknown> | null
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:visible': [visible: boolean]
}>()

const summary = computed(() => (props.result?.summary as Record<string, unknown>) ?? {})
const newFailures = computed(() => (props.result?.new_failures as Array<Record<string, unknown>>) ?? [])
const fixedCases = computed(() => (props.result?.fixed_cases as Array<Record<string, unknown>>) ?? [])
const stillFailing = computed(() => (props.result?.still_failing as Array<Record<string, unknown>>) ?? [])
const missingInCandidate = computed(() => (props.result?.missing_in_candidate as Array<Record<string, unknown>>) ?? [])
const newCasesInCandidate = computed(() => (props.result?.new_cases_in_candidate as Array<Record<string, unknown>>) ?? [])
const statusChanges = computed(() => (props.result?.status_changes as Array<Record<string, unknown>>) ?? [])
const checkRegressions = computed(() => (props.result?.check_regressions as Array<Record<string, unknown>>) ?? [])

function formatRate(value?: unknown): string {
  if (value === null || value === undefined || typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function formatDelta(value?: unknown): string {
  if (value === null || value === undefined || typeof value !== 'number' || Number.isNaN(value)) return '-'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(1)}%`
}

function deltaClass(value?: unknown): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return ''
  return value > 0 ? 'eval-run-compare__delta-positive' : value < 0 ? 'eval-run-compare__delta-negative' : ''
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

function closeDialog(visible: boolean): void {
  emit('update:visible', visible)
}
</script>

<template>
  <HarnessDetailDialog :visible="visible" header="Eval Run 对比" @update:visible="closeDialog">
    <template #default>
      <div v-if="loading" class="empty-state">加载中...</div>
      <div v-else-if="!result" class="empty-state">暂无对比数据</div>
      <div v-else class="eval-run-compare">
        <section class="eval-run-compare__section">
          <h4 class="eval-run-compare__title">总览</h4>
          <div class="eval-run-compare__cards">
            <article class="eval-run-compare__card">
              <span>Baseline 通过率</span>
              <strong>{{ formatRate(summary.baseline_pass_rate) }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>Candidate 通过率</span>
              <strong>{{ formatRate(summary.candidate_pass_rate) }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>通过率变化</span>
              <strong :class="deltaClass(summary.pass_rate_delta)">{{ formatDelta(summary.pass_rate_delta) }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>分数率变化</span>
              <strong :class="deltaClass(summary.score_rate_delta)">{{ formatDelta(summary.score_rate_delta) }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>新增失败</span>
              <strong class="color-negative">{{ summary.new_failure_count ?? 0 }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>修复成功</span>
              <strong class="color-positive">{{ summary.fixed_case_count ?? 0 }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>High/Critical 回归</span>
              <strong class="color-negative">{{ summary.high_priority_regression_count ?? 0 }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>Candidate 缺失</span>
              <strong class="color-negative">{{ summary.missing_in_candidate_count ?? 0 }}</strong>
            </article>
            <article class="eval-run-compare__card">
              <span>Candidate 新增</span>
              <strong class="color-positive">{{ summary.new_case_in_candidate_count ?? 0 }}</strong>
            </article>
          </div>
        </section>

        <section v-if="newFailures.length" class="eval-run-compare__section">
          <h4 class="eval-run-compare__title">新增失败</h4>
          <table class="eval-run-compare__table">
            <thead><tr><th>case_id</th><th>severity</th><th>category</th><th>baseline</th><th>candidate</th><th>new_failed_checks</th><th>message</th></tr></thead>
            <tbody>
              <tr v-for="item in newFailures" :key="String(item.case_id)">
                <td><code>{{ item.case_id }}</code></td>
                <td><Tag :value="String(item.severity)" :class="severityClass(String(item.severity))" /></td>
                <td>{{ item.category || '-' }}</td>
                <td><Tag :value="String(item.baseline_status)" :class="statusClass(String(item.baseline_status))" /></td>
                <td><Tag :value="String(item.candidate_status)" :class="statusClass(String(item.candidate_status))" /></td>
                <td>{{ (item.new_failed_checks as string[])?.join(', ') || '-' }}</td>
                <td>{{ item.message || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <div v-else class="empty-state">暂无新增失败</div>

        <section v-if="fixedCases.length" class="eval-run-compare__section">
          <h4 class="eval-run-compare__title">修复成功</h4>
          <table class="eval-run-compare__table">
            <thead><tr><th>case_id</th><th>severity</th><th>category</th><th>baseline</th><th>candidate</th><th>fixed_failed_checks</th></tr></thead>
            <tbody>
              <tr v-for="item in fixedCases" :key="String(item.case_id)">
                <td><code>{{ item.case_id }}</code></td>
                <td><Tag :value="String(item.severity)" :class="severityClass(String(item.severity))" /></td>
                <td>{{ item.category || '-' }}</td>
                <td><Tag :value="String(item.baseline_status)" :class="statusClass(String(item.baseline_status))" /></td>
                <td><Tag :value="String(item.candidate_status)" :class="statusClass(String(item.candidate_status))" /></td>
                <td>{{ (item.fixed_failed_checks as string[])?.join(', ') || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <div v-else class="empty-state">暂无修复成功 case</div>

        <section v-if="stillFailing.length" class="eval-run-compare__section">
          <h4 class="eval-run-compare__title">仍然失败</h4>
          <table class="eval-run-compare__table">
            <thead><tr><th>case_id</th><th>severity</th><th>category</th><th>candidate_failed_checks</th><th>message</th></tr></thead>
            <tbody>
              <tr v-for="item in stillFailing" :key="String(item.case_id)">
                <td><code>{{ item.case_id }}</code></td>
                <td><Tag :value="String(item.severity)" :class="severityClass(String(item.severity))" /></td>
                <td>{{ item.category || '-' }}</td>
                <td>{{ (item.candidate_failed_checks as string[])?.join(', ') || '-' }}</td>
                <td>{{ item.message || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <div v-else class="empty-state">暂无仍然失败 case</div>

        <section v-if="missingInCandidate.length" class="eval-run-compare__section">
          <h4 class="eval-run-compare__title">Candidate 缺失的 Case</h4>
          <table class="eval-run-compare__table">
            <thead><tr><th>case_id</th><th>severity</th><th>category</th><th>baseline_status</th><th>score</th></tr></thead>
            <tbody>
              <tr v-for="item in missingInCandidate" :key="String(item.case_id)">
                <td><code>{{ item.case_id }}</code></td>
                <td><Tag :value="String(item.severity)" :class="severityClass(String(item.severity))" /></td>
                <td>{{ item.category || '-' }}</td>
                <td><Tag :value="String(item.baseline_status)" :class="statusClass(String(item.baseline_status))" /></td>
                <td>{{ item.baseline_score ?? 0 }}/{{ item.baseline_max_score ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-if="newCasesInCandidate.length" class="eval-run-compare__section">
          <h4 class="eval-run-compare__title">Candidate 新增的 Case</h4>
          <table class="eval-run-compare__table">
            <thead><tr><th>case_id</th><th>severity</th><th>category</th><th>candidate_status</th><th>score</th></tr></thead>
            <tbody>
              <tr v-for="item in newCasesInCandidate" :key="String(item.case_id)">
                <td><code>{{ item.case_id }}</code></td>
                <td><Tag :value="String(item.severity)" :class="severityClass(String(item.severity))" /></td>
                <td>{{ item.category || '-' }}</td>
                <td><Tag :value="String(item.candidate_status)" :class="statusClass(String(item.candidate_status))" /></td>
                <td>{{ item.candidate_score ?? 0 }}/{{ item.candidate_max_score ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </template>
  </HarnessDetailDialog>
</template>

<style scoped>
.eval-run-compare {
  display: grid;
  gap: var(--space-4);
}

.eval-run-compare__section {
  display: grid;
  gap: 8px;
}

.eval-run-compare__title {
  margin: 0;
  font-size: 0.9rem;
  color: var(--color-text-secondary);
}

.eval-run-compare__cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
}

.eval-run-compare__card {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
}

.eval-run-compare__card span {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
}

.eval-run-compare__card strong {
  font-size: 1.1rem;
}

.eval-run-compare__delta-positive {
  color: var(--color-positive);
}

.eval-run-compare__delta-negative {
  color: var(--color-negative);
}

.eval-run-compare__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}

.eval-run-compare__table th,
.eval-run-compare__table td {
  padding: 8px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.1);
  text-align: left;
}

.eval-run-compare__table th {
  color: var(--color-text-secondary);
  font-weight: 700;
}

.color-positive {
  color: var(--color-positive);
}

.color-negative {
  color: var(--color-negative);
}
</style>
