<script setup lang="ts">
import { reactive, ref } from 'vue'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import type { AgentRegressionGatePayload, AgentRegressionRunPayload, EvalRun } from '@/types/adminHarness'

const props = defineProps<{
  evalRuns?: EvalRun[]
  loading?: boolean
}>()

const emit = defineEmits<{
  run: [payload: AgentRegressionRunPayload]
}>()

const AGENT_OPTIONS = [
  'trade_decision',
  'daily_position_review',
  'trade_review',
  'account_copilot',
]

const form = reactive({
  agent_name: 'trade_decision',
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
  gate_fail_on_high: true,
  gate_min_pass_rate: 0.95,
  gate_max_failed: 0,
  baseline_eval_run_id: '',
})

const validationError = ref('')

function normalizeNullableNumber(value: unknown): number | null {
  if (value === '' || value === null || value === undefined) return null
  const num = Number(value)
  if (Number.isNaN(num)) return null
  return num
}

function validate(): boolean {
  if (!form.agent_name) {
    validationError.value = '请选择 Agent'
    return false
  }
  if (form.mode !== 'static' && form.mode !== 'live_mock') {
    validationError.value = '评测模式无效'
    return false
  }
  if (form.limit < 1 || form.limit > 1000) {
    validationError.value = 'Limit 必须在 1-1000 之间'
    return false
  }
  const rawMinPassRate = form.gate_min_pass_rate as unknown
  const minPassRate = normalizeNullableNumber(rawMinPassRate)
  if (rawMinPassRate !== '' && rawMinPassRate !== null && rawMinPassRate !== undefined && minPassRate === null) {
    validationError.value = '通过率必须为数字'
    return false
  }
  if (minPassRate !== null && (minPassRate < 0 || minPassRate > 1)) {
    validationError.value = '通过率必须在 0-1 之间'
    return false
  }
  const rawMaxFailed = form.gate_max_failed as unknown
  const maxFailed = normalizeNullableNumber(rawMaxFailed)
  if (rawMaxFailed !== '' && rawMaxFailed !== null && rawMaxFailed !== undefined && maxFailed === null) {
    validationError.value = '最大失败数必须为数字'
    return false
  }
  if (maxFailed !== null && maxFailed < 0) {
    validationError.value = '最大失败数不能为负'
    return false
  }
  validationError.value = ''
  return true
}

function buildConfirmMessage(): string {
  const lines = [`确认运行 ${form.agent_name} 的 Agent 回归评测吗？`]
  lines.push(`模式：${form.mode === 'static' ? 'Static Eval' : 'Live Mock Eval'}`)
  if (form.case_tag) lines.push(`Case Tag：${form.case_tag}`)
  if (form.include_node_eval) {
    lines.push('本次将同时运行 Node Eval Case。Node Eval 失败也会计入 Gate 结果。')
    if (form.node_name) lines.push(`Node Name：${form.node_name}`)
  }
  const gateDesc: string[] = []
  if (form.gate_fail_on_critical) gateDesc.push('critical 失败阻断')
  if (form.gate_fail_on_high) gateDesc.push('high 失败阻断')
  if (form.gate_min_pass_rate) gateDesc.push(`通过率要求 ${Math.round(form.gate_min_pass_rate * 100)}%`)
  if (gateDesc.length) lines.push(`Gate：${gateDesc.join('，')}`)
  if (form.mode === 'live_mock') {
    lines.push('')
    lines.push('Live Mock 会基于 mock 数据用评测 Prompt 重新生成输出，不读取真实账户/行情；当前不是完整 Agent Graph 重跑。')
  }
  if (form.include_judge) {
    lines.push('')
    lines.push('所选回归评测启用了 LLM Judge，可能产生额外 token 成本。')
  }
  return lines.join('\n')
}

function handleRun() {
  if (!validate()) return
  const message = buildConfirmMessage()
  if (!window.confirm(message)) return

  const gate: AgentRegressionGatePayload = {
    fail_on_critical: form.gate_fail_on_critical,
    fail_on_high: form.gate_fail_on_high,
    min_pass_rate: normalizeNullableNumber(form.gate_min_pass_rate),
    max_failed: normalizeNullableNumber(form.gate_max_failed),
  }

  const payload: AgentRegressionRunPayload = {
    agent_name: form.agent_name,
    mode: form.mode,
    case_tag: form.case_tag || null,
    severity: form.severity || null,
    category: form.category || null,
    include_disabled: form.include_disabled,
    include_judge: form.include_judge,
    include_node_eval: form.include_node_eval,
    node_name: form.node_name.trim() || null,
    limit: form.limit,
    gate,
    trigger: 'manual',
    baseline_eval_run_id: form.baseline_eval_run_id || null,
  }

  emit('run', payload)
}
</script>

<template>
  <div class="agent-regression-panel">
    <h3 class="agent-regression-panel__title">Agent 回归评测</h3>
    <div class="agent-regression-panel__form">
      <div class="agent-regression-panel__row">
        <label>
          Agent
          <select v-model="form.agent_name">
            <option v-for="agent in AGENT_OPTIONS" :key="agent" :value="agent">{{ agent }}</option>
          </select>
        </label>
        <label>
          评测模式
          <select v-model="form.mode">
            <option value="static">Static Eval</option>
            <option value="live_mock">Live Mock Eval</option>
          </select>
        </label>
        <label>
          Case Tag
          <input v-model="form.case_tag" placeholder="regression" />
        </label>
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
          Limit
          <input v-model.number="form.limit" type="number" min="1" max="1000" />
        </label>
      </div>
      <div class="agent-regression-panel__row">
        <label class="checkbox-label">
          <input v-model="form.include_disabled" type="checkbox" />
          Include Disabled
        </label>
        <label class="checkbox-label">
          <input v-model="form.include_judge" type="checkbox" />
          Include Judge
        </label>
        <label class="checkbox-label" :title="form.include_node_eval ? '同时运行该 Agent 下的 Node Eval Case' : '默认只跑 Agent 级 Case'">
          <input v-model="form.include_node_eval" type="checkbox" data-testid="regression-include-node-eval" />
          Include Node Eval
        </label>
        <label>
          Node Name
          <input
            v-model="form.node_name"
            placeholder="可选，如 event_catalyst"
            :disabled="!form.include_node_eval"
            data-testid="regression-node-name"
          />
        </label>
        <label>
          Baseline Eval Run ID
          <input v-model="form.baseline_eval_run_id" placeholder="可选" />
        </label>
      </div>
      <div class="agent-regression-panel__row">
        <label>
          <input v-model="form.gate_fail_on_critical" type="checkbox" />
          Fail on Critical
        </label>
        <label>
          <input v-model="form.gate_fail_on_high" type="checkbox" />
          Fail on High
        </label>
        <label>
          Min Pass Rate
          <input v-model.number="form.gate_min_pass_rate" type="number" min="0" max="1" step="0.01" />
        </label>
        <label>
          Max Failed
          <input v-model.number="form.gate_max_failed" type="number" min="0" />
        </label>
      </div>
      <div v-if="validationError" class="agent-regression-panel__error">{{ validationError }}</div>
      <div class="agent-regression-panel__actions">
        <Button
          label="运行 Agent 回归评测"
          icon="pi pi-play"
          class="p-button--accent"
          :loading="loading"
          :disabled="!form.agent_name || loading"
          @click="handleRun"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-regression-panel {
  border: 1px solid var(--surface-border, #333);
  border-radius: 6px;
  padding: 1rem;
  margin-bottom: 1rem;
  background: var(--surface-card, #1e1e1e);
}

.agent-regression-panel__title {
  margin: 0 0 0.75rem;
  font-size: 1rem;
}

.agent-regression-panel__form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.agent-regression-panel__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
}

.agent-regression-panel__row label {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: 0.8rem;
  color: var(--text-color-secondary, #aaa);
}

.agent-regression-panel__row label.checkbox-label {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}

.agent-regression-panel__row input,
.agent-regression-panel__row select {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--surface-border, #444);
  border-radius: 4px;
  background: var(--surface-ground, #111);
  color: var(--text-color, #eee);
  font-size: 0.85rem;
}

.agent-regression-panel__row input[type="number"] {
  width: 5rem;
}

.agent-regression-panel__error {
  color: #f87171;
  font-size: 0.8rem;
}

.agent-regression-panel__actions {
  margin-top: 0.25rem;
}
</style>
