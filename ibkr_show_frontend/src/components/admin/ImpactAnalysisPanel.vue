<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import { analyzeImpactChangedFiles, analyzeImpactGitDiff, regressionGateDryRun, runAgentRegressionEval } from '@/api/adminHarness'
import type { RegressionGateResult } from '@/api/adminHarness'
import JsonBlock from '@/components/admin/JsonBlock.vue'
import type { AgentRegressionRunPayload, AgentRegressionRunResponse, ImpactAnalysisResult } from '@/types/adminHarness'

const changedFilesInput = ref('')
const baseRef = ref('origin/main')
const headRef = ref('HEAD')
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const result = ref<ImpactAnalysisResult | null>(null)
const expandedPayloads = ref<Set<string>>(new Set())

const regressionRunning = ref('')
const regressionResults = ref<Map<string, AgentRegressionRunResponse>>(new Map())
const gateDryRunLoading = ref(false)
const gateDryRunResult = ref<RegressionGateResult | null>(null)

function togglePayload(agentName: string): void {
  if (expandedPayloads.value.has(agentName)) {
    expandedPayloads.value.delete(agentName)
  } else {
    expandedPayloads.value.add(agentName)
  }
}

async function analyzeChangedFiles(): Promise<void> {
  const files = changedFilesInput.value.split('\n').map((l) => l.trim()).filter(Boolean)
  if (!files.length) {
    errorMessage.value = '请输入至少一个 changed file'
    return
  }
  loading.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  result.value = null
  try {
    result.value = await analyzeImpactChangedFiles({
      changed_files: files,
      base_ref: baseRef.value || undefined,
      head_ref: headRef.value || undefined,
    })
    noticeMessage.value = `分析完成：${result.value.summary.impacted_agent_count} 个 Agent 受影响，${result.value.summary.recommended_run_count} 个建议运行回归`
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function analyzeGitDiff(): Promise<void> {
  if (!baseRef.value || !headRef.value) {
    errorMessage.value = '请输入 base_ref 和 head_ref'
    return
  }
  loading.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  result.value = null
  try {
    result.value = await analyzeImpactGitDiff({
      base_ref: baseRef.value,
      head_ref: headRef.value,
    })
    noticeMessage.value = `分析完成：${result.value.summary.impacted_agent_count} 个 Agent 受影响，${result.value.summary.recommended_run_count} 个建议运行回归`
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function runRegression(agentName: string, payload: Record<string, unknown>): Promise<void> {
  const confirmMsg = `确认运行 ${agentName} 的回归评测？\n\n本次回归基于代码变更影响分析结果。`
  if (!window.confirm(confirmMsg)) return

  regressionRunning.value = agentName
  regressionResults.value.delete(agentName)
  try {
    const runPayload = payload as unknown as AgentRegressionRunPayload
    const runResult = await runAgentRegressionEval(runPayload)
    regressionResults.value.set(agentName, runResult)
    if (runResult.gate_result?.passed) {
      noticeMessage.value = `${agentName} 回归评测通过。Eval Run: ${runResult.eval_run.eval_run_id}`
    } else {
      noticeMessage.value = `${agentName} 回归评测未通过。Eval Run: ${runResult.eval_run.eval_run_id}`
    }
  } catch (err: unknown) {
    errorMessage.value = `${agentName} 回归评测运行失败：${err instanceof Error ? err.message : String(err)}`
  } finally {
    regressionRunning.value = ''
  }
}

async function runGateDryRun(): Promise<void> {
  const files = changedFilesInput.value.split('\n').map((l) => l.trim()).filter(Boolean)
  if (!files.length && !(baseRef.value && headRef.value)) {
    errorMessage.value = '请输入 changed files 或 base_ref + head_ref'
    return
  }
  gateDryRunLoading.value = true
  gateDryRunResult.value = null
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    gateDryRunResult.value = await regressionGateDryRun({
      changed_files: files.length ? files : undefined,
      base_ref: baseRef.value || undefined,
      head_ref: headRef.value || undefined,
    })
    const summary = gateDryRunResult.value.summary
    if (summary.recommended_run_count === 0) {
      noticeMessage.value = '无需回归，Gate 将通过'
    } else {
      noticeMessage.value = `Gate Dry Run：${summary.recommended_run_count} 个 Agent 需要运行回归`
    }
  } catch (err: unknown) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  } finally {
    gateDryRunLoading.value = false
  }
}
</script>

<template>
  <div class="impact-panel">
    <div class="impact-panel__form">
      <div class="impact-panel__row">
        <label class="impact-panel__field">
          Changed Files（一行一个）
          <textarea
            v-model="changedFilesInput"
            class="impact-panel__textarea"
            rows="4"
            placeholder="ibkr_show_backend/app/agents/trade_decision_graph/nodes.py&#10;ibkr_show_backend/app/prompts/trade_decision/risk_control.md"
          />
        </label>
      </div>
      <div class="impact-panel__row">
        <label class="impact-panel__field-sm">
          Base Ref
          <input v-model="baseRef" placeholder="origin/main" />
        </label>
        <label class="impact-panel__field-sm">
          Head Ref
          <input v-model="headRef" placeholder="HEAD" />
        </label>
      </div>
      <div class="impact-panel__actions">
        <Button label="分析 Changed Files" icon="pi pi-search" :loading="loading" @click="analyzeChangedFiles" />
        <Button label="分析 Git Diff" icon="pi pi-code" severity="secondary" :loading="loading" @click="analyzeGitDiff" />
        <Button label="部署 Gate Dry Run" icon="pi pi-shield" severity="warning" :loading="gateDryRunLoading" @click="runGateDryRun" />
      </div>
    </div>

    <p v-if="noticeMessage" class="impact-panel__notice">{{ noticeMessage }}</p>
    <p v-if="errorMessage" class="impact-panel__error">{{ errorMessage }}</p>

    <div v-if="result" class="impact-panel__result">
      <div class="impact-panel__summary">
        <article class="impact-panel__card">
          <span>Changed Files</span>
          <strong>{{ result.summary.changed_file_count }}</strong>
        </article>
        <article class="impact-panel__card">
          <span>Impacted Agents</span>
          <strong>{{ result.summary.impacted_agent_count }}</strong>
        </article>
        <article class="impact-panel__card">
          <span>Recommended Runs</span>
          <strong>{{ result.summary.recommended_run_count }}</strong>
        </article>
      </div>

      <div v-if="result.impacted_agents.length" class="impact-panel__agents">
        <h4>Impacted Agents</h4>
        <table class="harness-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Confidence</th>
              <th>Recommended</th>
              <th>Profile</th>
              <th>on_code_change</th>
              <th>Nodes</th>
              <th>Reason</th>
              <th>Payload</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="agent in result.impacted_agents" :key="agent.agent_name">
              <td><code>{{ agent.agent_name }}</code></td>
              <td><Tag :value="agent.confidence" :class="agent.confidence === 'high' ? 'p-tag--positive' : 'p-tag--accent'" /></td>
              <td><Tag :value="agent.recommended ? '是' : '否'" :class="agent.recommended ? 'p-tag--positive' : 'p-tag--secondary'" /></td>
              <td>
                <span v-if="!agent.profile_exists" class="impact-panel__muted">未配置</span>
                <span v-else-if="!agent.profile_enabled" class="impact-panel__muted">已禁用</span>
                <Tag v-else value="启用" class="p-tag--positive" />
              </td>
              <td>{{ agent.trigger_policy_on_code_change ? '是' : '否' }}</td>
              <td>{{ agent.impacted_nodes.length ? agent.impacted_nodes.join(', ') : '-' }}</td>
              <td class="impact-panel__reason">{{ agent.reason }}</td>
              <td>
                <Button
                  v-if="agent.regression_payload"
                  :label="expandedPayloads.has(agent.agent_name) ? '收起' : '展开'"
                  size="small"
                  text
                  @click="togglePayload(agent.agent_name)"
                />
                <span v-else class="impact-panel__muted">-</span>
              </td>
              <td>
                <Button
                  v-if="agent.recommended && agent.regression_payload"
                  label="运行回归"
                  icon="pi pi-play"
                  size="small"
                  :loading="regressionRunning === agent.agent_name"
                  :disabled="!!regressionRunning"
                  @click="runRegression(agent.agent_name, agent.regression_payload!)"
                />
              </td>
            </tr>
          </tbody>
        </table>

        <div v-for="agent in result.impacted_agents" :key="`payload-${agent.agent_name}`">
          <div v-if="expandedPayloads.has(agent.agent_name) && agent.regression_payload" class="impact-panel__payload">
            <JsonBlock :title="`${agent.agent_name} payload`" :value="agent.regression_payload" />
          </div>
        </div>
      </div>

      <div v-if="result.unmatched_files.length" class="impact-panel__unmatched">
        <h4>Unmatched Files ({{ result.unmatched_files.length }})</h4>
        <ul>
          <li v-for="file in result.unmatched_files" :key="file"><code>{{ file }}</code></li>
        </ul>
      </div>

      <div v-for="[agentName, runResult] in regressionResults" :key="`reg-${agentName}`" class="impact-panel__regression-result">
        <h4>{{ agentName }} 回归结果</h4>
        <div class="impact-panel__regression-header">
          <Tag :value="runResult.gate_result?.passed ? '通过' : '未通过'" :class="runResult.gate_result?.passed ? 'p-tag--positive' : 'p-tag--negative'" />
          <span>通过率：{{ ((runResult.gate_result?.pass_rate ?? 0) * 100).toFixed(1) }}%</span>
          <span>Case 数：{{ runResult.selected_case_count ?? '-' }}</span>
          <span v-if="runResult.eval_run?.summary?.failed_count != null">失败：{{ runResult.eval_run.summary.failed_count }}</span>
          <span v-if="runResult.eval_run?.summary?.critical_failure_count != null">Critical：{{ runResult.eval_run.summary.critical_failure_count }}</span>
          <span>Eval Run: <code>{{ runResult.eval_run?.eval_run_id }}</code></span>
        </div>
        <div v-if="runResult.gate_result?.reasons?.length" class="impact-panel__regression-reasons">
          <div v-for="reason in runResult.gate_result.reasons" :key="reason">- {{ reason }}</div>
        </div>
      </div>

      <div v-if="gateDryRunResult" class="impact-panel__gate-result">
        <h4>部署 Gate Dry Run</h4>
        <div class="impact-panel__summary">
          <article class="impact-panel__card">
            <span>Gate 状态</span>
            <strong>{{ gateDryRunResult.ok ? '将通过' : '将阻断' }}</strong>
          </article>
          <article class="impact-panel__card">
            <span>需要运行</span>
            <strong>{{ gateDryRunResult.summary.recommended_run_count }}</strong>
          </article>
          <article class="impact-panel__card">
            <span>受影响 Agent</span>
            <strong>{{ gateDryRunResult.summary.impacted_agent_count }}</strong>
          </article>
        </div>
        <div v-if="gateDryRunResult.runs.length" class="impact-panel__gate-runs">
          <h5>将运行的回归</h5>
          <table class="harness-table">
            <thead>
              <tr><th>Agent</th><th>Payload</th></tr>
            </thead>
            <tbody>
              <tr v-for="run in gateDryRunResult.runs" :key="run.agent_name">
                <td><code>{{ run.agent_name }}</code></td>
                <td>
                  <Button label="展开" size="small" text @click="togglePayload(`gate-${run.agent_name}`)" />
                  <div v-if="expandedPayloads.has(`gate-${run.agent_name}`) && run.regression_payload" class="impact-panel__payload">
                    <JsonBlock :title="run.agent_name" :value="run.regression_payload" />
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="gateDryRunResult.reasons.length" class="impact-panel__gate-reasons">
          <div v-for="reason in gateDryRunResult.reasons" :key="reason">- {{ reason }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.impact-panel {
  display: grid;
  gap: var(--space-4);
}

.impact-panel__form {
  display: grid;
  gap: 0.75rem;
}

.impact-panel__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.impact-panel__field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex: 1;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.impact-panel__field-sm {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  min-width: 180px;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.impact-panel__textarea {
  width: 100%;
  min-height: 80px;
  padding: 0.5rem;
  border: 1px solid var(--surface-border, #444);
  border-radius: 4px;
  background: var(--surface-ground, #111);
  color: var(--text-color, #eee);
  font-size: 0.85rem;
  font-family: monospace;
  resize: vertical;
}

.impact-panel__field input,
.impact-panel__field-sm input {
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--surface-border, #444);
  border-radius: 4px;
  background: var(--surface-ground, #111);
  color: var(--text-color, #eee);
  font-size: 0.85rem;
}

.impact-panel__actions {
  display: flex;
  gap: 8px;
}

.impact-panel__notice {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: rgba(88, 214, 161, 0.12);
  color: var(--color-positive);
  font-size: 0.85rem;
}

.impact-panel__error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: rgba(255, 107, 122, 0.12);
  color: var(--color-negative);
  font-size: 0.85rem;
}

.impact-panel__result {
  display: grid;
  gap: var(--space-4);
}

.impact-panel__summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--space-3);
}

.impact-panel__card {
  display: grid;
  gap: 6px;
  padding: 14px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.42);
}

.impact-panel__card span {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.impact-panel__card strong {
  font-size: 1.2rem;
}

.impact-panel__agents h4,
.impact-panel__unmatched h4,
.impact-panel__regression-result h4 {
  margin: 0 0 0.5rem;
  font-size: 0.95rem;
}

.impact-panel__reason {
  max-width: 200px;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}

.impact-panel__muted {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.impact-panel__payload {
  margin-top: 0.5rem;
  padding: 0.75rem;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.3);
}

.impact-panel__unmatched ul {
  margin: 0;
  padding-left: 1.5rem;
  font-size: 0.82rem;
  color: var(--color-text-secondary);
}

.impact-panel__unmatched li {
  margin-bottom: 0.2rem;
}

.impact-panel__regression-result {
  padding: 1rem;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.3);
}

.impact-panel__regression-header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  font-size: 0.85rem;
}

.impact-panel__regression-reasons {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.impact-panel__gate-result {
  padding: 1rem;
  border: 1px solid rgba(255, 183, 77, 0.25);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.3);
}

.impact-panel__gate-result h4 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
}

.impact-panel__gate-runs {
  margin-top: 0.75rem;
}

.impact-panel__gate-runs h5 {
  margin: 0 0 0.5rem;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.impact-panel__gate-reasons {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}
</style>
