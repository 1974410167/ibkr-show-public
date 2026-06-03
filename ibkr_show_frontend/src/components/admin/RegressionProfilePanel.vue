<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import {
  buildRegressionPayloadFromProfile,
  disableRegressionProfile,
  listRegressionProfiles,
  upsertRegressionProfile,
} from '@/api/adminHarness'
import JsonBlock from '@/components/admin/JsonBlock.vue'
import type { RegressionProfile, RegressionProfileListResponse, RegressionProfileUpsertPayload } from '@/types/adminHarness'

const profiles = ref<RegressionProfile[]>([])
const summary = ref<{ profile_count: number; enabled_count: number }>({ profile_count: 0, enabled_count: 0 })
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')

const AGENT_OPTIONS = ['trade_decision', 'daily_position_review', 'trade_review', 'account_copilot']

const editorVisible = ref(false)
const editorMode = ref<'create' | 'edit'>('create')
const editorSaving = ref(false)
const editorError = ref('')

const form = reactive({
  agent_name: '',
  enabled: true,
  mode: 'static' as 'static' | 'live_mock',
  case_tag: 'regression',
  severity: '',
  category: '',
  include_disabled: false,
  include_judge: false,
  include_node_eval: false,
  node_name: '',
  limit: 100,
  gate_fail_on_critical: true,
  gate_fail_on_high: false,
  gate_min_pass_rate: 0.9,
  gate_max_failed: '' as number | '',
  trigger_policy_on_prompt_save: false,
  trigger_policy_on_code_change: false,
  trigger_policy_on_deploy: false,
  notes: '',
})

const payloadPreviewVisible = ref(false)
const payloadPreviewLoading = ref(false)
const payloadPreviewData = ref<Record<string, unknown> | null>(null)
const payloadPreviewAgent = ref('')

async function loadProfiles(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const data: RegressionProfileListResponse = await listRegressionProfiles({ limit: 100 })
    profiles.value = data.items
    summary.value = data.summary
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editorMode.value = 'create'
  editorError.value = ''
  resetForm()
  editorVisible.value = true
}

function openEdit(profile: RegressionProfile): void {
  editorMode.value = 'edit'
  editorError.value = ''
  form.agent_name = profile.agent_name
  form.enabled = profile.enabled
  form.mode = (profile.mode as 'static' | 'live_mock') || 'static'
  form.case_tag = profile.case_tag || ''
  form.severity = profile.severity || ''
  form.category = profile.category || ''
  form.include_disabled = profile.include_disabled
  form.include_judge = profile.include_judge
  form.include_node_eval = profile.include_node_eval
  form.node_name = profile.node_name || ''
  form.limit = profile.limit
  form.gate_fail_on_critical = profile.gate?.fail_on_critical ?? true
  form.gate_fail_on_high = profile.gate?.fail_on_high ?? false
  form.gate_min_pass_rate = profile.gate?.min_pass_rate ?? 0.9
  form.gate_max_failed = profile.gate?.max_failed ?? ''
  form.trigger_policy_on_prompt_save = profile.trigger_policy?.on_prompt_save ?? false
  form.trigger_policy_on_code_change = profile.trigger_policy?.on_code_change ?? false
  form.trigger_policy_on_deploy = profile.trigger_policy?.on_deploy ?? false
  form.notes = profile.notes || ''
  editorVisible.value = true
}

function resetForm(): void {
  form.agent_name = ''
  form.enabled = true
  form.mode = 'static'
  form.case_tag = 'regression'
  form.severity = ''
  form.category = ''
  form.include_disabled = false
  form.include_judge = false
  form.include_node_eval = false
  form.node_name = ''
  form.limit = 100
  form.gate_fail_on_critical = true
  form.gate_fail_on_high = false
  form.gate_min_pass_rate = 0.9
  form.gate_max_failed = ''
  form.trigger_policy_on_prompt_save = false
  form.trigger_policy_on_code_change = false
  form.trigger_policy_on_deploy = false
  form.notes = ''
}

function validate(): boolean {
  if (!form.agent_name) {
    editorError.value = '请选择 Agent'
    return false
  }
  if (form.limit < 1 || form.limit > 1000) {
    editorError.value = 'Limit 必须在 1-1000 之间'
    return false
  }
  if (form.gate_min_pass_rate < 0 || form.gate_min_pass_rate > 1) {
    editorError.value = '通过率必须在 0-1 之间'
    return false
  }
  if (form.gate_max_failed !== '' && form.gate_max_failed < 0) {
    editorError.value = '最大失败数不能为负'
    return false
  }
  editorError.value = ''
  return true
}

async function handleSave(): Promise<void> {
  if (!validate()) return
  editorSaving.value = true
  editorError.value = ''
  try {
    const payload: RegressionProfileUpsertPayload = {
      enabled: form.enabled,
      mode: form.mode,
      case_tag: form.case_tag || null,
      severity: form.severity || null,
      category: form.category || null,
      include_disabled: form.include_disabled,
      include_judge: form.include_judge,
      include_node_eval: form.include_node_eval,
      node_name: form.node_name.trim() || null,
      limit: form.limit,
      gate: {
        fail_on_critical: form.gate_fail_on_critical,
        fail_on_high: form.gate_fail_on_high,
        min_pass_rate: form.gate_min_pass_rate,
        max_failed: form.gate_max_failed === '' ? null : form.gate_max_failed,
      },
      trigger_policy: {
        on_prompt_save: form.trigger_policy_on_prompt_save,
        on_code_change: form.trigger_policy_on_code_change,
        on_deploy: form.trigger_policy_on_deploy,
      },
      notes: form.notes,
    }
    await upsertRegressionProfile(form.agent_name, payload)
    editorVisible.value = false
    noticeMessage.value = `Profile ${editorMode.value === 'create' ? '创建' : '更新'}成功`
    await loadProfiles()
  } catch (err: unknown) {
    editorError.value = err instanceof Error ? err.message : String(err)
  } finally {
    editorSaving.value = false
  }
}

async function handleDisable(profile: RegressionProfile): Promise<void> {
  if (!window.confirm(`确认禁用 ${profile.agent_name} 的回归配置？`)) return
  try {
    await disableRegressionProfile(profile.agent_name)
    noticeMessage.value = `${profile.agent_name} 已禁用`
    await loadProfiles()
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  }
}

async function handleBuildPayload(profile: RegressionProfile): Promise<void> {
  payloadPreviewAgent.value = profile.agent_name
  payloadPreviewLoading.value = true
  payloadPreviewVisible.value = true
  payloadPreviewData.value = null
  try {
    payloadPreviewData.value = await buildRegressionPayloadFromProfile(profile.agent_name)
  } catch (err: unknown) {
    payloadPreviewData.value = { error: err instanceof Error ? err.message : String(err) }
  } finally {
    payloadPreviewLoading.value = false
  }
}

function formatDateTime(iso: string | undefined): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

onMounted(() => {
  void loadProfiles()
})
</script>

<template>
  <div class="regression-profile-panel">
    <div class="regression-profile-panel__header">
      <div class="regression-profile-panel__summary">
        <span>共 {{ summary.profile_count }} 个配置</span>
        <span>启用 {{ summary.enabled_count }}</span>
      </div>
      <div class="regression-profile-panel__actions">
        <Button label="新增配置" icon="pi pi-plus" size="small" @click="openCreate" />
        <Button label="刷新" icon="pi pi-refresh" severity="secondary" size="small" :loading="loading" @click="loadProfiles" />
      </div>
    </div>

    <p v-if="noticeMessage" class="regression-profile-panel__notice">{{ noticeMessage }}</p>
    <p v-if="errorMessage" class="regression-profile-panel__error">{{ errorMessage }}</p>

    <div v-if="loading && !profiles.length" class="regression-profile-panel__empty">加载中...</div>
    <div v-else-if="!profiles.length" class="regression-profile-panel__empty">暂无回归配置，点击"新增配置"创建。</div>

    <table v-else class="harness-table regression-profile-panel__table">
      <thead>
        <tr>
          <th>Agent</th>
          <th>启用</th>
          <th>模式</th>
          <th>Include Node Eval</th>
          <th>Node Name</th>
          <th>Include Judge</th>
          <th>Case Tag</th>
          <th>Min Pass Rate</th>
          <th>Fail on Critical</th>
          <th>Fail on High</th>
          <th>Limit</th>
          <th>更新时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="profile in profiles" :key="profile.profile_id">
          <td><code>{{ profile.agent_name }}</code></td>
          <td><Tag :value="profile.enabled ? '启用' : '禁用'" :class="profile.enabled ? 'p-tag--positive' : 'p-tag--secondary'" /></td>
          <td>{{ profile.mode }}</td>
          <td>{{ profile.include_node_eval ? '是' : '否' }}</td>
          <td>{{ profile.node_name || '-' }}</td>
          <td>{{ profile.include_judge ? '是' : '否' }}</td>
          <td>{{ profile.case_tag || '-' }}</td>
          <td>{{ profile.gate?.min_pass_rate != null ? `${Math.round(profile.gate.min_pass_rate * 100)}%` : '-' }}</td>
          <td>{{ profile.gate?.fail_on_critical ? '是' : '否' }}</td>
          <td>{{ profile.gate?.fail_on_high ? '是' : '否' }}</td>
          <td>{{ profile.limit }}</td>
          <td>{{ formatDateTime(profile.updated_at) }}</td>
          <td class="regression-profile-panel__ops">
            <Button icon="pi pi-pencil" severity="secondary" size="small" text title="编辑" @click="openEdit(profile)" />
            <Button icon="pi pi-eye" severity="info" size="small" text title="预览回归参数" @click="handleBuildPayload(profile)" />
            <Button v-if="profile.enabled" icon="pi pi-ban" severity="warning" size="small" text title="禁用" @click="handleDisable(profile)" />
          </td>
        </tr>
      </tbody>
    </table>

    <Dialog
      v-model:visible="editorVisible"
      :header="editorMode === 'create' ? '新增回归配置' : '编辑回归配置'"
      :style="{ width: '640px' }"
      :modal="true"
    >
      <div class="profile-editor">
        <div class="profile-editor__row">
          <label>
            Agent
            <select v-model="form.agent_name" :disabled="editorMode === 'edit'">
              <option value="" disabled>请选择</option>
              <option v-for="agent in AGENT_OPTIONS" :key="agent" :value="agent">{{ agent }}</option>
            </select>
          </label>
          <label>
            模式
            <select v-model="form.mode">
              <option value="static">Static Eval</option>
              <option value="live_mock">Live Mock Eval</option>
            </select>
          </label>
          <label>
            Case Tag
            <input v-model="form.case_tag" placeholder="regression" />
          </label>
        </div>

        <div class="profile-editor__row">
          <label>
            Severity
            <select v-model="form.severity">
              <option value="">全部</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </label>
          <label>
            Category
            <input v-model="form.category" placeholder="可选" />
          </label>
          <label>
            Limit
            <input v-model.number="form.limit" type="number" min="1" max="1000" />
          </label>
        </div>

        <div class="profile-editor__row">
          <label class="checkbox-label">
            <input v-model="form.enabled" type="checkbox" />
            启用
          </label>
          <label class="checkbox-label">
            <input v-model="form.include_disabled" type="checkbox" />
            Include Disabled
          </label>
          <label class="checkbox-label">
            <input v-model="form.include_judge" type="checkbox" />
            Include Judge
          </label>
          <label class="checkbox-label">
            <input v-model="form.include_node_eval" type="checkbox" />
            Include Node Eval
          </label>
        </div>

        <div class="profile-editor__row">
          <label>
            Node Name
            <input v-model="form.node_name" placeholder="可选" :disabled="!form.include_node_eval" />
          </label>
          <label>
            Notes
            <input v-model="form.notes" placeholder="可选备注" />
          </label>
        </div>

        <fieldset class="profile-editor__fieldset">
          <legend>Gate 配置</legend>
          <div class="profile-editor__row">
            <label class="checkbox-label">
              <input v-model="form.gate_fail_on_critical" type="checkbox" />
              Fail on Critical
            </label>
            <label class="checkbox-label">
              <input v-model="form.gate_fail_on_high" type="checkbox" />
              Fail on High
            </label>
            <label>
              Min Pass Rate
              <input v-model.number="form.gate_min_pass_rate" type="number" min="0" max="1" step="0.01" />
            </label>
            <label>
              Max Failed
              <input v-model.number="form.gate_max_failed" type="number" min="0" placeholder="不限" />
            </label>
          </div>
        </fieldset>

        <fieldset class="profile-editor__fieldset">
          <legend>触发策略（仅存储，暂不自动执行）</legend>
          <div class="profile-editor__row">
            <label class="checkbox-label">
              <input v-model="form.trigger_policy_on_prompt_save" type="checkbox" />
              Prompt 保存时
            </label>
            <label class="checkbox-label">
              <input v-model="form.trigger_policy_on_code_change" type="checkbox" />
              代码变更时
            </label>
            <label class="checkbox-label">
              <input v-model="form.trigger_policy_on_deploy" type="checkbox" />
              部署前
            </label>
          </div>
        </fieldset>

        <p v-if="editorError" class="profile-editor__error">{{ editorError }}</p>
      </div>

      <template #footer>
        <Button label="取消" severity="secondary" @click="editorVisible = false" />
        <Button label="保存" icon="pi pi-check" :loading="editorSaving" @click="handleSave" />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="payloadPreviewVisible"
      :header="`回归参数预览 — ${payloadPreviewAgent}`"
      :style="{ width: '600px' }"
      :modal="true"
    >
      <div v-if="payloadPreviewLoading" class="regression-profile-panel__empty">生成中...</div>
      <JsonBlock v-else-if="payloadPreviewData" title="payload" :value="payloadPreviewData" />
    </Dialog>
  </div>
</template>

<style scoped>
.regression-profile-panel {
  display: grid;
  gap: var(--space-4);
}

.regression-profile-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.regression-profile-panel__summary {
  display: flex;
  gap: 1rem;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.regression-profile-panel__actions {
  display: flex;
  gap: 8px;
}

.regression-profile-panel__notice {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: rgba(88, 214, 161, 0.12);
  color: var(--color-positive);
  font-size: 0.85rem;
}

.regression-profile-panel__error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: rgba(255, 107, 122, 0.12);
  color: var(--color-negative);
  font-size: 0.85rem;
}

.regression-profile-panel__empty {
  padding: 2rem;
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}

.regression-profile-panel__table {
  font-size: 0.82rem;
}

.regression-profile-panel__ops {
  display: flex;
  gap: 4px;
  white-space: nowrap;
}

.profile-editor {
  display: grid;
  gap: 0.75rem;
}

.profile-editor__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
}

.profile-editor__row label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.profile-editor__row label.checkbox-label {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}

.profile-editor__row input,
.profile-editor__row select {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--surface-border, #444);
  border-radius: 4px;
  background: var(--surface-ground, #111);
  color: var(--text-color, #eee);
  font-size: 0.85rem;
}

.profile-editor__row input[type="number"] {
  width: 5rem;
}

.profile-editor__fieldset {
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  padding: 0.75rem;
}

.profile-editor__fieldset legend {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  padding: 0 0.4rem;
}

.profile-editor__error {
  color: #f87171;
  font-size: 0.8rem;
  margin: 0;
}
</style>
