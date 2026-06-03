<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import { getRegressionGateReport, listRegressionGateReports } from '@/api/adminHarness'
import HarnessDetailDialog from '@/components/admin/HarnessDetailDialog.vue'
import JsonBlock from '@/components/admin/JsonBlock.vue'
import type { RegressionGateReport, RegressionGateReportListResponse } from '@/api/adminHarness'

const reports = ref<RegressionGateReport[]>([])
const summary = ref<RegressionGateReportListResponse['summary']>({ report_count: 0, passed_count: 0, failed_count: 0, dry_run_count: 0, error_count: 0 })
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')

const filters = reactive({
  status: '',
  trigger: '',
  ok: '' as '' | 'true' | 'false',
  dry_run: '' as '' | 'true' | 'false',
  agent_name: '',
  hours: 24 * 30,
  limit: 100,
})

const selectedReport = ref<RegressionGateReport | null>(null)
const detailLoading = ref(false)

async function loadReports(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const params: Record<string, unknown> = { hours: filters.hours, limit: filters.limit }
    if (filters.status) params.status = filters.status
    if (filters.trigger) params.trigger = filters.trigger
    if (filters.ok) params.ok = filters.ok === 'true'
    if (filters.dry_run) params.dry_run = filters.dry_run === 'true'
    if (filters.agent_name) params.agent_name = filters.agent_name
    const data: RegressionGateReportListResponse = await listRegressionGateReports(params as Parameters<typeof listRegressionGateReports>[0])
    reports.value = data.items
    summary.value = data.summary
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function openReport(reportId: string): Promise<void> {
  detailLoading.value = true
  try {
    selectedReport.value = await getRegressionGateReport(reportId)
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  } finally {
    detailLoading.value = false
  }
}

function formatDateTime(iso: string | undefined): string {
  if (!iso) return '-'
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

function statusClass(status: string): string {
  if (status === 'passed') return 'p-tag--positive'
  if (status === 'failed') return 'p-tag--negative'
  if (status === 'error') return 'p-tag--negative'
  if (status === 'dry_run') return 'p-tag--accent'
  return ''
}

onMounted(() => { void loadReports() })
</script>

<template>
  <div class="gate-reports-panel">
    <div class="gate-reports-panel__header">
      <div class="gate-reports-panel__summary">
        <span>共 {{ summary.report_count }} 份报告</span>
        <span>通过 {{ summary.passed_count }}</span>
        <span>失败 {{ summary.failed_count }}</span>
        <span>Dry Run {{ summary.dry_run_count }}</span>
      </div>
      <Button label="刷新" icon="pi pi-refresh" severity="secondary" size="small" :loading="loading" @click="loadReports" />
    </div>

    <div class="gate-reports-panel__filters">
      <select v-model="filters.status">
        <option value="">全部状态</option>
        <option value="passed">passed</option>
        <option value="failed">failed</option>
        <option value="dry_run">dry_run</option>
        <option value="error">error</option>
      </select>
      <select v-model="filters.trigger">
        <option value="">全部触发源</option>
        <option value="cli">cli</option>
        <option value="api_dry_run">api_dry_run</option>
      </select>
      <select v-model="filters.ok">
        <option value="">全部 ok</option>
        <option value="true">ok=true</option>
        <option value="false">ok=false</option>
      </select>
      <select v-model="filters.dry_run">
        <option value="">全部</option>
        <option value="true">dry_run=true</option>
        <option value="false">dry_run=false</option>
      </select>
      <input v-model="filters.agent_name" placeholder="agent_name" />
      <Button label="搜索" icon="pi pi-search" severity="secondary" size="small" @click="loadReports" />
    </div>

    <p v-if="noticeMessage" class="gate-reports-panel__notice">{{ noticeMessage }}</p>
    <p v-if="errorMessage" class="gate-reports-panel__error">{{ errorMessage }}</p>

    <div v-if="loading && !reports.length" class="gate-reports-panel__empty">加载中...</div>
    <div v-else-if="!reports.length" class="gate-reports-panel__empty">暂无 Gate 报告。</div>

    <table v-else class="harness-table gate-reports-panel__table">
      <thead>
        <tr>
          <th>时间</th>
          <th>状态</th>
          <th>OK</th>
          <th>Dry Run</th>
          <th>Trigger</th>
          <th>Impacted</th>
          <th>Recommended</th>
          <th>Executed</th>
          <th>Failed</th>
          <th>Base</th>
          <th>Head</th>
          <th>Report ID</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="report in reports" :key="report.report_id" @click="openReport(report.report_id)">
          <td>{{ formatDateTime(report.created_at) }}</td>
          <td><Tag :value="report.status" :class="statusClass(report.status)" /></td>
          <td><Tag :value="report.ok ? '是' : '否'" :class="report.ok ? 'p-tag--positive' : 'p-tag--negative'" /></td>
          <td>{{ report.dry_run ? '是' : '否' }}</td>
          <td>{{ report.trigger }}</td>
          <td>{{ report.summary?.impacted_agent_count ?? '-' }}</td>
          <td>{{ report.summary?.recommended_run_count ?? '-' }}</td>
          <td>{{ report.summary?.executed_run_count ?? '-' }}</td>
          <td>{{ report.summary?.failed_run_count ?? '-' }}</td>
          <td>{{ report.base_ref || '-' }}</td>
          <td>{{ report.head_ref || '-' }}</td>
          <td><code>{{ report.report_id }}</code></td>
        </tr>
      </tbody>
    </table>

    <HarnessDetailDialog :visible="Boolean(selectedReport)" header="Gate Report 详情" @update:visible="selectedReport = null">
      <template #default="{ registerBlock }">
        <template v-if="selectedReport">
          <div class="gate-reports-panel__detail-header">
            <Tag :value="selectedReport.status" :class="statusClass(selectedReport.status)" />
            <span>Trigger: {{ selectedReport.trigger }}</span>
            <span>Created: {{ formatDateTime(selectedReport.created_at) }}</span>
            <span v-if="selectedReport.created_by">By: {{ selectedReport.created_by }}</span>
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="summary" :value="selectedReport.summary" />
          <div v-if="selectedReport.reasons.length" class="gate-reports-panel__reasons">
            <h4>Reasons</h4>
            <div v-for="reason in selectedReport.reasons" :key="reason">- {{ reason }}</div>
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="impacted_agents" :value="selectedReport.impacted_agents" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="runs" :value="selectedReport.runs" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="impact_analysis" :value="selectedReport.impact_analysis" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="full report" :value="selectedReport" collapsed />
        </template>
      </template>
    </HarnessDetailDialog>
  </div>
</template>

<style scoped>
.gate-reports-panel {
  display: grid;
  gap: var(--space-4);
}

.gate-reports-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.gate-reports-panel__summary {
  display: flex;
  gap: 1rem;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.gate-reports-panel__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}

.gate-reports-panel__filters select,
.gate-reports-panel__filters input {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--surface-border, #444);
  border-radius: 4px;
  background: var(--surface-ground, #111);
  color: var(--text-color, #eee);
  font-size: 0.82rem;
}

.gate-reports-panel__notice {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: rgba(88, 214, 161, 0.12);
  color: var(--color-positive);
  font-size: 0.85rem;
}

.gate-reports-panel__error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: rgba(255, 107, 122, 0.12);
  color: var(--color-negative);
  font-size: 0.85rem;
}

.gate-reports-panel__empty {
  padding: 2rem;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}

.gate-reports-panel__table {
  font-size: 0.82rem;
}

.gate-reports-panel__detail-header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 0.75rem;
  font-size: 0.85rem;
}

.gate-reports-panel__reasons {
  margin: 0.5rem 0;
  padding: 0.75rem;
  border: 1px solid rgba(255, 107, 122, 0.2);
  border-radius: var(--radius-sm);
  background: rgba(255, 107, 122, 0.05);
  font-size: 0.82rem;
}

.gate-reports-panel__reasons h4 {
  margin: 0 0 0.3rem;
  font-size: 0.85rem;
}
</style>
