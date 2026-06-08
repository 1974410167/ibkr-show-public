<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'

import {
  activateAdminPromptVersion,
  createAdminPromptVersion,
  createAdminPromptVersionFromCodeDefault,
  fetchAdminPromptDetail,
  fetchAdminPrompts,
  fetchAdminRuntimePrompt,
  seedDefaultAdminPrompts,
  syncCodeDefaultAdminPrompts,
} from '@/api/adminPrompts'
import { buildRegressionPayloadFromProfile, getRegressionProfile, runAgentRegressionEval } from '@/api/adminHarness'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type { PromptDetailResponse, PromptListItem, PromptRuntimeResponse, PromptStatus, PromptVersion } from '@/types/adminPrompts'
import type { AgentRegressionRunPayload, AgentRegressionRunResponse, RegressionProfile } from '@/types/adminHarness'

const router = useRouter()

const loading = ref(true)
const detailLoading = ref(false)
const saving = ref(false)
const seeding = ref(false)
const syncing = ref(false)
const syncingSingle = ref(false)
const runtimeLoading = ref(false)
const activatingVersion = ref('')
const errorMessage = ref('')
const noticeMessage = ref('')
const prompts = ref<PromptListItem[]>([])
const selectedKey = ref('')
const detail = ref<PromptDetailResponse | null>(null)
const runtimePrompt = ref<PromptRuntimeResponse | null>(null)
const selectedVersion = ref<PromptVersion | null>(null)
const showDefaultContent = ref(false)
const draftContent = ref('')
const changeNote = ref('')
const regressionRunning = ref(false)
const regressionResult = ref<AgentRegressionRunResponse | null>(null)

function inferRegressionAgentName(promptKey: string): string | null {
  if (promptKey.startsWith('trade_decision_')) return 'trade_decision'
  if (promptKey.startsWith('trade_review_')) return 'trade_review'
  if (promptKey.startsWith('daily_position_review_')) return 'daily_position_review'
  if (promptKey.startsWith('account_copilot_')) return 'account_copilot'
  return null
}

function getRegressionAgentName(): string | null {
  return (
    (detail.value?.definition?.agent_name as string | undefined) ??
    selectedPrompt.value?.agent_name ??
    inferRegressionAgentName(selectedKey.value)
  )
}

const selectedPrompt = computed(() => prompts.value.find((item) => item.prompt_key === selectedKey.value) ?? null)
const versions = computed(() => detail.value?.versions ?? [])
const activeVersion = computed(() => detail.value?.active ?? null)
const canSaveDraft = computed(() => Boolean(selectedKey.value && draftContent.value.trim() && !saving.value))
const selectedMatchesCodeDefault = computed(() => Boolean(selectedPrompt.value?.matches_code_default))
const selectedCodeDefaultOutdated = computed(() => Boolean(selectedPrompt.value?.is_code_default_outdated))

const groupedPrompts = computed(() => {
  const groups = new Map<string, PromptListItem[]>()
  for (const item of prompts.value) {
    const key = item.module_name || 'other'
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  return Array.from(groups.entries()).map(([moduleName, items]) => ({ moduleName, items }))
})

function shortHash(value: string | null | undefined, length = 8): string {
  return value ? value.slice(0, length) : '--'
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return '--'
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function statusClass(status: PromptStatus): string {
  if (status === 'active') {
    return 'p-tag--positive'
  }
  if (status === 'archived') {
    return 'p-tag--negative'
  }
  return 'p-tag--accent'
}

async function loadPrompts(nextSelectedKey?: string): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    prompts.value = await fetchAdminPrompts()
    const nextKey = nextSelectedKey || selectedKey.value || prompts.value[0]?.prompt_key || ''
    if (nextKey) {
      await selectPrompt(nextKey)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 Prompt 列表失败'
  } finally {
    loading.value = false
  }
}

async function selectPrompt(promptKey: string): Promise<void> {
  selectedKey.value = promptKey
  detailLoading.value = true
  runtimePrompt.value = null
  selectedVersion.value = null
  errorMessage.value = ''
  try {
    detail.value = await fetchAdminPromptDetail(promptKey)
    draftContent.value = detail.value.active?.content ?? detail.value.definition.default_content
    changeNote.value = ''
  } catch (error) {
    detail.value = null
    errorMessage.value = error instanceof Error ? error.message : '加载 Prompt 详情失败'
  } finally {
    detailLoading.value = false
  }
}

async function seedDefaults(): Promise<void> {
  seeding.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await seedDefaultAdminPrompts()
    noticeMessage.value = response.message
    await loadPrompts(selectedKey.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '初始化默认 Prompt 失败'
  } finally {
    seeding.value = false
  }
}

async function syncAllCodeDefaults(): Promise<void> {
  syncing.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await syncCodeDefaultAdminPrompts()
    noticeMessage.value = response.message
    await loadPrompts(selectedKey.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '同步代码默认 Prompt 失败'
  } finally {
    syncing.value = false
  }
}

async function createFromCodeDefault(): Promise<void> {
  if (!selectedKey.value) {
    return
  }
  syncingSingle.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await createAdminPromptVersionFromCodeDefault(selectedKey.value)
    noticeMessage.value = response.message
    await loadPrompts(selectedKey.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '从代码默认创建版本失败'
  } finally {
    syncingSingle.value = false
  }
}

function copyFromActive(): void {
  draftContent.value = activeVersion.value?.content ?? ''
}

function copyFromDefault(): void {
  draftContent.value = detail.value?.definition.default_content ?? ''
}

async function saveNewVersion(): Promise<void> {
  if (!selectedKey.value || !draftContent.value.trim()) {
    return
  }
  saving.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  regressionResult.value = null
  try {
    const response = await createAdminPromptVersion(selectedKey.value, {
      content: draftContent.value.trim(),
      change_note: changeNote.value.trim() || undefined,
    })
    noticeMessage.value = response.message
    await loadPrompts(selectedKey.value)

    const agentName = getRegressionAgentName()
    if (!agentName) {
      noticeMessage.value = response.message + '（无法识别所属 Agent，未触发回归评测）'
      return
    }
    if (!response.prompt) return

    const promptVersion = response.prompt
    try {
      const profile = await getRegressionProfile(agentName)
      if (!profile.enabled) {
        noticeMessage.value = response.message + `（${agentName} 回归配置已禁用，未触发回归评测）`
        return
      }
      if (!profile.trigger_policy?.on_prompt_save) {
        noticeMessage.value = response.message + `（${agentName} 回归配置未启用 Prompt 保存触发）`
        return
      }
      const confirmLines = [
        `Prompt 已保存。是否立即运行 ${agentName} 的回归评测？`,
        '',
        '本次回归将使用「回归评测配置」中的默认策略。回归失败不会回滚 Prompt 保存，但会提示 Gate 结果。',
        '',
        `Agent：${agentName}`,
        `模式：${profile.mode === 'live_mock' ? 'Live Mock Eval' : 'Static Eval'}`,
        `Include Node Eval：${profile.include_node_eval ? '是' : '否'}`,
      ]
      if (profile.node_name) confirmLines.push(`Node Name：${profile.node_name}`)
      confirmLines.push(`Include Judge：${profile.include_judge ? '是' : '否'}`)
      if (profile.case_tag) confirmLines.push(`Case Tag：${profile.case_tag}`)
      if (profile.severity) confirmLines.push(`Severity：${profile.severity}`)
      if (profile.category) confirmLines.push(`Category：${profile.category}`)
      confirmLines.push(`Limit：${profile.limit}`)
      const gateDesc: string[] = []
      if (profile.gate?.fail_on_critical) gateDesc.push('critical 失败阻断')
      if (profile.gate?.fail_on_high) gateDesc.push('high 失败阻断')
      if (profile.gate?.min_pass_rate != null) gateDesc.push(`通过率要求 ${Math.round(profile.gate.min_pass_rate * 100)}%`)
      if (profile.gate?.max_failed != null) gateDesc.push(`最大失败数 ${profile.gate.max_failed}`)
      if (gateDesc.length) confirmLines.push(`Gate：${gateDesc.join('，')}`)

      if (window.confirm(confirmLines.join('\n'))) {
        await triggerRegression(agentName, promptVersion)
      }
    } catch (profileError: unknown) {
      if (profileError instanceof Error && profileError.message.includes('404')) {
        noticeMessage.value = response.message + `（${agentName} 未配置回归评测配置）`
      } else {
        noticeMessage.value = response.message + `（读取回归配置失败，未触发回归评测）`
      }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存新版本失败'
  } finally {
    saving.value = false
  }
}

async function triggerRegression(agentName: string, promptVersion: PromptVersion): Promise<void> {
  regressionRunning.value = true
  regressionResult.value = null
  errorMessage.value = ''
  try {
    const builtPayload = await buildRegressionPayloadFromProfile(agentName, {
      trigger: 'prompt_save',
      name: `Prompt regression - ${agentName} - ${promptVersion.prompt_key}`,
      prompt: {
        prompt_key: promptVersion.prompt_key,
        prompt_version: promptVersion.version,
        prompt_hash: promptVersion.content_hash,
        saved_at: new Date().toISOString(),
        source: 'admin_prompt_save',
      },
    })
    const payload = builtPayload as unknown as AgentRegressionRunPayload
    const result = await runAgentRegressionEval(payload)
    regressionResult.value = result
    if (result.gate_result?.passed) {
      noticeMessage.value = `Prompt 已保存，Agent 回归评测通过。Eval Run: ${result.eval_run.eval_run_id}`
    } else {
      noticeMessage.value = `Prompt 已保存，但 Agent 回归评测未通过，请查看失败用例。Eval Run: ${result.eval_run.eval_run_id}`
    }
  } catch (error) {
    errorMessage.value = `Prompt 已保存，但回归评测运行失败：${error instanceof Error ? error.message : String(error)}`
  } finally {
    regressionRunning.value = false
  }
}

async function activateVersion(version: PromptVersion): Promise<void> {
  if (version.status === 'active' || !selectedKey.value) {
    return
  }
  if (!window.confirm(`确认激活 ${version.version}？当前 active 版本会自动归档。`)) {
    return
  }
  const note = window.prompt('可选：填写本次激活说明', version.change_note ?? '') ?? ''
  activatingVersion.value = version.version
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await activateAdminPromptVersion(selectedKey.value, version.version, {
      change_note: note.trim() || undefined,
    })
    noticeMessage.value = response.message
    await loadPrompts(selectedKey.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '激活版本失败'
  } finally {
    activatingVersion.value = ''
  }
}

async function viewRuntimePrompt(): Promise<void> {
  if (!selectedKey.value) {
    return
  }
  runtimeLoading.value = true
  runtimePrompt.value = null
  errorMessage.value = ''
  try {
    runtimePrompt.value = await fetchAdminRuntimePrompt(selectedKey.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载运行时 Prompt 失败'
  } finally {
    runtimeLoading.value = false
  }
}

onMounted(() => {
  void loadPrompts()
})
</script>

<template>
  <section class="page-section admin-prompts-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header admin-prompts-page__header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-prompts-page__title">Agent Prompt 管理</h2>
            <p class="panel-subtitle">统一管理 10 个 Agent / 子 Agent 的 system prompt。</p>
          </div>
          <div class="row-actions">
            <Button label="初始化默认 Prompt" icon="pi pi-sync" class="p-button p-button--ghost" :loading="seeding" @click="seedDefaults" />
            <Button label="同步全部代码默认 Prompt" icon="pi pi-refresh" class="p-button p-button--accent" :loading="syncing" @click="syncAllCodeDefaults" />
          </div>
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="宏观数据源" icon="pi pi-calendar-clock" class="terminal-nav__button" @click="router.push('/admin/market-events')" />
          <Button label="系统状态" icon="pi pi-heart" class="terminal-nav__button" @click="router.push('/admin/system')" />
          <Button label="Agent 监控" icon="pi pi-chart-line" class="terminal-nav__button" @click="router.push('/admin/agent-monitoring')" />
          <Button label="Prompt 管理" icon="pi pi-file-edit" class="terminal-nav__button is-active" />
          <Button label="Harness 控制台" icon="pi pi-sitemap" class="terminal-nav__button" @click="router.push('/admin/harness')" />
        </nav>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage && !prompts.length" :message="errorMessage" />

    <template v-else>
      <p v-if="noticeMessage" class="admin-notice">{{ noticeMessage }}</p>
      <ErrorBlock v-if="errorMessage" :message="errorMessage" />

      <section class="admin-prompt-layout">
        <section class="surface-panel prompt-list-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">Prompt 列表</h3>
                <p class="panel-subtitle">点击左侧项查看版本和运行时内容。</p>
              </div>
            </div>

            <div class="prompt-groups">
              <section v-for="group in groupedPrompts" :key="group.moduleName" class="prompt-group">
                <h4>{{ group.moduleName }}</h4>
                <button
                  v-for="item in group.items"
                  :key="item.prompt_key"
                  class="prompt-list-item"
                  :class="{ 'is-selected': item.prompt_key === selectedKey }"
                  type="button"
                  @click="selectPrompt(item.prompt_key)"
                >
                  <span class="prompt-list-item__main">
                    <strong>{{ item.display_name }}</strong>
                    <small>{{ item.module_name }} / {{ item.agent_name }}</small>
                    <code>{{ item.prompt_key }}</code>
                  </span>
                  <span class="prompt-list-item__meta">
                    <Tag :value="item.has_active ? item.active_version || 'ACTIVE' : 'NO ACTIVE'" :class="item.has_active ? 'p-tag--positive' : 'p-tag--negative'" />
                    <Tag v-if="item.matches_code_default" value="MATCHES CODE" class="p-tag--positive" />
                    <Tag v-if="item.is_code_default_outdated" value="OUTDATED" class="p-tag--negative" />
                    <Tag v-if="item.is_default_active" value="HISTORICAL DEFAULT" class="p-tag--accent" />
                    <span>active #{{ shortHash(item.active_content_hash) }}</span>
                    <span>code #{{ shortHash(item.code_default_hash) }}</span>
                    <span>{{ formatDate(item.active_updated_at) }}</span>
                  </span>
                </button>
              </section>
            </div>
          </div>
        </section>

        <section class="surface-panel prompt-detail-panel">
          <div class="surface-panel__content">
            <LoadingBlock v-if="detailLoading" />
            <div v-else-if="detail" class="prompt-detail">
              <div class="section-header">
                <div>
                  <h3 class="panel-title">{{ detail.definition.display_name }}</h3>
                  <p class="panel-subtitle">{{ detail.definition.description }}</p>
                </div>
                <div class="row-actions">
                  <Button label="查看运行时 Prompt" icon="pi pi-eye" class="p-button p-button--ghost" :loading="runtimeLoading" @click="viewRuntimePrompt" />
                </div>
              </div>

              <dl class="prompt-meta-grid">
                <div><dt>prompt_key</dt><dd>{{ detail.definition.prompt_key }}</dd></div>
                <div><dt>module</dt><dd>{{ detail.definition.module_name }}</dd></div>
                <div><dt>agent</dt><dd>{{ detail.definition.agent_name }}</dd></div>
                <div><dt>active</dt><dd>{{ activeVersion?.version ?? '无 active 版本' }}</dd></div>
                <div><dt>active hash</dt><dd><code>{{ shortHash(activeVersion?.content_hash, 12) }}</code></dd></div>
                <div><dt>code default hash</dt><dd><code>{{ shortHash(selectedPrompt?.code_default_hash, 12) }}</code></dd></div>
                <div><dt>匹配代码默认</dt><dd>{{ selectedMatchesCodeDefault ? '是' : '否' }}</dd></div>
                <div><dt>历史默认版本</dt><dd>{{ selectedPrompt?.is_default_active ? '是' : '否' }}</dd></div>
              </dl>

              <p v-if="selectedCodeDefaultOutdated" class="prompt-warning">
                当前 active prompt 与代码默认 prompt 不一致。可以点击“从代码默认创建新版本”，查看后手动激活。
              </p>

              <section class="prompt-block">
                <div class="prompt-block__header">
                  <h4>Code Default</h4>
                  <Button :label="showDefaultContent ? '收起' : '展开'" class="p-button p-button--ghost" @click="showDefaultContent = !showDefaultContent" />
                </div>
                <pre v-if="showDefaultContent" class="prompt-content">{{ detail.definition.default_content }}</pre>
              </section>

              <section v-if="runtimePrompt" class="prompt-block runtime-block">
                <div class="prompt-block__header">
                  <h4>Runtime Prompt</h4>
                  <div class="runtime-tags">
                    <Tag :value="runtimePrompt.metadata.source" class="p-tag--accent" />
                    <Tag :value="runtimePrompt.metadata.version || 'code'" />
                    <code>#{{ shortHash(runtimePrompt.metadata.content_hash, 12) }}</code>
                  </div>
                </div>
                <pre class="prompt-content">{{ runtimePrompt.content }}</pre>
              </section>

              <section class="prompt-block">
                <div class="prompt-block__header">
                  <h4>创建新版本</h4>
                  <div class="row-actions">
                    <Button label="从代码默认创建新版本" icon="pi pi-refresh" class="p-button p-button--ghost" :loading="syncingSingle" @click="createFromCodeDefault" />
                    <Button label="从 active 复制" icon="pi pi-copy" class="p-button p-button--ghost" :disabled="!activeVersion" @click="copyFromActive" />
                    <Button label="从 code default 复制" icon="pi pi-code" class="p-button p-button--ghost" @click="copyFromDefault" />
                  </div>
                </div>
                <textarea v-model="draftContent" class="admin-textarea prompt-editor" rows="14" placeholder="输入新版本 prompt content"></textarea>
                <div class="prompt-version-form">
                  <InputText v-model="changeNote" placeholder="change_note，可选" />
                  <Button
                    label="保存为新版本"
                    icon="pi pi-save"
                    class="p-button p-button--accent"
                    :disabled="!canSaveDraft || regressionRunning"
                    :loading="saving || regressionRunning"
                    @click="saveNewVersion"
                  />
                </div>
                <div v-if="regressionRunning" class="prompt-regression-status">
                  正在运行 Agent 回归评测...
                </div>
                <div v-if="regressionResult" class="prompt-regression-result">
                  <div class="prompt-regression-result__header">
                    <span>Gate：</span>
                    <Tag :value="regressionResult.gate_result?.passed ? '通过' : '未通过'" :class="regressionResult.gate_result?.passed ? 'p-tag--positive' : 'p-tag--negative'" />
                    <span>通过率：{{ ((regressionResult.gate_result?.pass_rate ?? 0) * 100).toFixed(1) }}%</span>
                    <span>Case 数：{{ regressionResult.selected_case_count ?? '-' }}</span>
                    <span v-if="regressionResult.eval_run?.summary?.failed_count != null">失败：{{ regressionResult.eval_run.summary.failed_count }}</span>
                    <span v-if="regressionResult.eval_run?.summary?.error_count != null">错误：{{ regressionResult.eval_run.summary.error_count }}</span>
                    <span v-if="regressionResult.eval_run?.summary?.critical_failure_count != null">Critical：{{ regressionResult.eval_run.summary.critical_failure_count }}</span>
                    <span v-if="regressionResult.eval_run?.summary?.high_priority_failure_count != null">High：{{ regressionResult.eval_run.summary.high_priority_failure_count }}</span>
                    <Button label="查看用例运行记录" icon="pi pi-external-link" class="p-button p-button--ghost" @click="router.push('/admin/harness')" />
                  </div>
                  <div v-if="regressionResult.gate_result?.reasons?.length" class="prompt-regression-result__reasons">
                    <div v-for="reason in regressionResult.gate_result.reasons" :key="reason">- {{ reason }}</div>
                  </div>
                </div>
              </section>

              <section class="prompt-block">
                <div class="prompt-block__header">
                  <h4>版本列表</h4>
                  <Tag :value="`${versions.length} versions`" />
                </div>
                <div v-if="versions.length" class="table-shell">
                  <table class="prompt-version-table">
                    <thead>
                      <tr>
                        <th>版本</th>
                        <th>状态</th>
                        <th>默认</th>
                        <th>Hash</th>
                        <th>创建人</th>
                        <th>创建时间</th>
                        <th>更新时间</th>
                        <th>备注</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="version in versions" :key="version.id">
                        <td>{{ version.version }}</td>
                        <td><Tag :value="version.status.toUpperCase()" :class="statusClass(version.status)" /></td>
                        <td>{{ version.is_default ? 'YES' : 'NO' }}</td>
                        <td><code>{{ shortHash(version.content_hash, 12) }}</code></td>
                        <td>{{ version.created_by || '--' }}</td>
                        <td>{{ formatDate(version.created_at) }}</td>
                        <td>{{ formatDate(version.updated_at) }}</td>
                        <td class="cell-note">{{ version.change_note || '--' }}</td>
                        <td>
                          <div class="row-actions">
                            <Button label="查看" icon="pi pi-eye" class="p-button p-button--ghost" @click="selectedVersion = version" />
                            <Button
                              label="激活"
                              icon="pi pi-check-circle"
                              class="p-button p-button--ghost"
                              :disabled="version.status === 'active'"
                              :loading="activatingVersion === version.version"
                              @click="activateVersion(version)"
                            />
                          </div>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-else class="empty-state">暂无版本，先初始化默认 Prompt。</div>
              </section>
            </div>
            <div v-else class="empty-state">请选择一个 Prompt。</div>
          </div>
        </section>
      </section>
    </template>

    <div v-if="selectedVersion" class="admin-dialog-backdrop" @click.self="selectedVersion = null">
      <section class="surface-panel admin-dialog prompt-content-dialog">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <p class="eyebrow">{{ selectedVersion.version }}</p>
              <h3 class="panel-title">{{ selectedVersion.display_name }}</h3>
            </div>
            <Button icon="pi pi-times" class="p-button p-button--ghost" aria-label="关闭" @click="selectedVersion = null" />
          </div>
          <pre class="prompt-content">{{ selectedVersion.content }}</pre>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.admin-prompts-page {
  display: grid;
  gap: var(--space-4);
}

.admin-prompts-page__header {
  align-items: center;
}

.admin-prompts-page__title {
  font-size: 1.5rem;
}

.admin-tabs {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.admin-prompt-layout {
  display: grid;
  grid-template-columns: minmax(320px, 0.78fr) minmax(0, 1.45fr);
  gap: var(--space-4);
  align-items: start;
}

.prompt-groups,
.prompt-detail,
.prompt-block {
  display: grid;
  gap: var(--space-3);
}

.prompt-group {
  display: grid;
  gap: 10px;
}

.prompt-group h4,
.prompt-block h4 {
  margin: 0;
  color: var(--color-text-primary);
}

.prompt-list-item {
  width: 100%;
  display: grid;
  gap: 10px;
  padding: 14px;
  text-align: left;
  color: var(--color-text-primary);
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.5);
  cursor: pointer;
}

.prompt-list-item.is-selected {
  border-color: rgba(89, 201, 165, 0.45);
  background: rgba(89, 201, 165, 0.08);
}

.prompt-list-item__main,
.prompt-list-item__meta {
  display: grid;
  gap: 6px;
}

.prompt-list-item__main small,
.prompt-list-item__meta {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.prompt-list-item__meta {
  grid-template-columns: repeat(2, minmax(0, max-content));
  align-items: center;
}

.prompt-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}

.prompt-meta-grid div,
.prompt-block {
  padding: 14px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.46);
}

.prompt-meta-grid dt {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.prompt-meta-grid dd {
  margin: 6px 0 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}

.prompt-warning {
  margin: 0;
  padding: 12px 14px;
  border: 1px solid rgba(255, 193, 7, 0.3);
  border-radius: var(--radius-md);
  background: rgba(255, 193, 7, 0.1);
  color: var(--color-text-primary);
}

.prompt-block__header,
.prompt-version-form,
.row-actions,
.runtime-tags {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.prompt-block__header {
  justify-content: space-between;
}

.prompt-version-form {
  align-items: stretch;
}

.prompt-version-form :deep(.p-inputtext) {
  flex: 1;
  min-width: 220px;
}

.admin-textarea,
.prompt-content {
  width: 100%;
  border: 1px solid rgba(129, 160, 207, 0.16);
  border-radius: 12px;
  background: rgba(10, 18, 32, 0.85);
  color: var(--color-text-primary);
}

.admin-textarea {
  resize: vertical;
  padding: 0.85rem 0.95rem;
  outline: none;
}

.prompt-editor {
  min-height: 320px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  line-height: 1.55;
}

.prompt-content {
  max-height: 520px;
  overflow: auto;
  padding: 14px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.55;
}

.prompt-version-table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
}

.prompt-version-table th,
.prompt-version-table td {
  padding: 12px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.1);
  text-align: left;
  vertical-align: top;
}

.prompt-version-table th {
  color: var(--color-text-secondary);
  font-size: 0.78rem;
  text-transform: uppercase;
}

.cell-note {
  max-width: 260px;
}

.prompt-content-dialog {
  width: min(980px, calc(100vw - 32px));
}

code {
  color: var(--color-accent);
  overflow-wrap: anywhere;
}

.prompt-regression-status {
  padding: 10px 14px;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.prompt-regression-result {
  padding: 12px 14px;
  border: 1px solid rgba(129, 160, 207, 0.16);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.46);
  font-size: 0.85rem;
}

.prompt-regression-result__header {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.prompt-regression-result__reasons {
  margin-top: 0.5rem;
  color: #f87171;
  font-size: 0.8rem;
}

@media (max-width: 1180px) {
  .admin-prompt-layout,
  .prompt-meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
