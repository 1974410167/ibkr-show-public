<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'

import {
  activateLlmProvider,
  createLlmProvider,
  deleteLlmProvider,
  fetchLlmHealth,
  fetchLlmProviders,
  testActiveLlmChat,
  testLlmProvider,
  updateLlmProvider,
} from '@/api/adminLlm'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type { LlmChatTestResponse, LlmHealth, LlmProvider, LlmProviderPayload, LlmProviderTestResponse } from '@/types/adminLlm'

const router = useRouter()

type ProviderForm = {
  id: string
  name: string
  provider_type: string
  base_url: string
  api_key: string
  default_model: string
  available_models_text: string
  temperature: number
  context_window_tokens: number
  input_token_limit: number
  output_token_limit: number
  timeout_seconds: number
  enabled: boolean
  enable_thinking: boolean
  reasoning_effort: string
}

const loading = ref(true)
const saving = ref(false)
const testingId = ref('')
const deletingId = ref('')
const activatingId = ref('')
const errorMessage = ref('')
const noticeMessage = ref('')
const health = ref<LlmHealth | null>(null)
const providers = ref<LlmProvider[]>([])
const showForm = ref(false)
const editingProvider = ref<LlmProvider | null>(null)
const testPrompt = ref('请只回复 OK')
const activeChatMessage = ref('用一句话介绍你自己')
const activeChatModel = ref('')
const providerTestResult = ref<LlmProviderTestResponse | null>(null)
const chatTestResult = ref<LlmChatTestResponse | null>(null)

const form = reactive<ProviderForm>({
  id: '',
  name: '',
  provider_type: 'openai_compatible',
  base_url: '',
  api_key: '',
  default_model: '',
  available_models_text: '',
  temperature: 0.2,
  context_window_tokens: 200000,
  input_token_limit: 150000,
  output_token_limit: 10000,
  timeout_seconds: 60,
  enabled: true,
  enable_thinking: false,
  reasoning_effort: 'high',
})

const activeProvider = computed(() => health.value?.active_provider ?? providers.value.find((provider) => provider.is_active) ?? null)

function splitModels(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function resetForm(provider?: LlmProvider): void {
  editingProvider.value = provider ?? null
  form.id = provider?.id ?? ''
  form.name = provider?.name ?? ''
  form.provider_type = provider?.provider_type ?? 'openai_compatible'
  form.base_url = provider?.base_url ?? ''
  form.api_key = ''
  form.default_model = provider?.default_model ?? ''
  form.available_models_text = provider?.available_models.join(', ') ?? ''
  form.temperature = provider?.temperature ?? 0.2
  form.context_window_tokens = provider?.context_window_tokens ?? 200000
  form.input_token_limit = provider?.input_token_limit ?? 150000
  form.output_token_limit = provider?.output_token_limit ?? 10000
  form.timeout_seconds = provider?.timeout_seconds ?? 60
  form.enabled = provider?.enabled ?? true
  form.enable_thinking = provider?.enable_thinking ?? false
  form.reasoning_effort = provider?.reasoning_effort ?? 'high'
}

async function loadData(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [healthResponse, providerItems] = await Promise.all([fetchLlmHealth(), fetchLlmProviders()])
    health.value = healthResponse
    providers.value = providerItems
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 LLM 配置失败'
  } finally {
    loading.value = false
  }
}

function openCreateForm(): void {
  resetForm()
  showForm.value = true
}

function openEditForm(provider: LlmProvider): void {
  resetForm(provider)
  showForm.value = true
}

function closeForm(): void {
  showForm.value = false
  resetForm()
}

function buildPayload(includeApiKey: boolean): LlmProviderPayload {
  const payload: LlmProviderPayload = {
    name: form.name.trim(),
    provider_type: form.provider_type,
    base_url: form.base_url.trim(),
    default_model: form.default_model.trim(),
    available_models: splitModels(form.available_models_text),
    enabled: form.enabled,
    enable_thinking: form.enable_thinking,
    reasoning_effort: form.reasoning_effort,
    timeout_seconds: Number(form.timeout_seconds),
    temperature: Number(form.temperature),
    context_window_tokens: Number(form.context_window_tokens),
    input_token_limit: Number(form.input_token_limit),
    output_token_limit: Number(form.output_token_limit),
  }
  if (includeApiKey && form.api_key.trim()) {
    payload.api_key = form.api_key.trim()
  }
  return payload
}

async function saveProvider(): Promise<void> {
  saving.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    if (editingProvider.value) {
      await updateLlmProvider(editingProvider.value.id, buildPayload(Boolean(form.api_key.trim())))
      noticeMessage.value = 'Provider 已更新'
    } else {
      await createLlmProvider(buildPayload(true))
      noticeMessage.value = 'Provider 已创建'
    }
    closeForm()
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function activateProvider(provider: LlmProvider): Promise<void> {
  activatingId.value = provider.id
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await activateLlmProvider(provider.id)
    noticeMessage.value = `${provider.name} 已设为默认 Provider`
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '激活失败'
  } finally {
    activatingId.value = ''
  }
}

async function removeProvider(provider: LlmProvider): Promise<void> {
  if (!window.confirm(`确认删除 ${provider.name}？`)) {
    return
  }
  deletingId.value = provider.id
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await deleteLlmProvider(provider.id)
    noticeMessage.value = response.message
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除失败'
  } finally {
    deletingId.value = ''
  }
}

async function runProviderTest(provider: LlmProvider): Promise<void> {
  testingId.value = provider.id
  providerTestResult.value = null
  errorMessage.value = ''
  try {
    providerTestResult.value = await testLlmProvider(provider.id, testPrompt.value.trim() || '请只回复 OK')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测试失败'
  } finally {
    testingId.value = ''
  }
}

async function runActiveChatTest(): Promise<void> {
  testingId.value = 'active-chat'
  chatTestResult.value = null
  errorMessage.value = ''
  try {
    chatTestResult.value = await testActiveLlmChat(activeChatMessage.value.trim(), activeChatModel.value.trim())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '对话测试失败'
  } finally {
    testingId.value = ''
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <section class="page-section admin-llm-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header admin-llm-page__header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-llm-page__title">LLM 配置管理</h2>
            <p class="panel-subtitle">统一管理 OpenAI-compatible Provider，后续 Agent 只读取当前 active 配置。</p>
          </div>
          <Button label="新增 Provider" icon="pi pi-plus" class="p-button p-button--accent" @click="openCreateForm" />
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button is-active" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="投资策略" icon="pi pi-sliders-h" class="terminal-nav__button" @click="router.push('/admin/investment-policy')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="宏观数据源" icon="pi pi-calendar-clock" class="terminal-nav__button" @click="router.push('/admin/market-events')" />
          <Button label="系统状态" icon="pi pi-heart" class="terminal-nav__button" @click="router.push('/admin/system')" />
          <Button label="Agent 监控" icon="pi pi-chart-line" class="terminal-nav__button" @click="router.push('/admin/agent-monitoring')" />
          <Button label="Prompt 管理" icon="pi pi-file-edit" class="terminal-nav__button" @click="router.push('/admin/prompts')" />
          <Button label="Harness 控制台" icon="pi pi-sitemap" class="terminal-nav__button" @click="router.push('/admin/harness')" />
        </nav>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage" :message="errorMessage" />

    <template v-else>
      <p v-if="noticeMessage" class="admin-notice">{{ noticeMessage }}</p>

      <section class="admin-layout">
        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">当前启用模型</h3>
                <p class="panel-subtitle">后台测试与后续 Agent 默认走这个 Provider。</p>
              </div>
              <Tag :value="health?.enabled ? 'LLM ON' : 'LLM OFF'" :class="health?.enabled ? 'p-tag--positive' : 'p-tag--negative'" />
            </div>

            <div v-if="activeProvider" class="active-provider">
              <div class="active-provider__main">
                <span class="terminal-note">Provider</span>
                <strong>{{ activeProvider.name }}</strong>
              </div>
              <dl class="provider-meta">
                <div>
                  <dt>Base URL</dt>
                  <dd>{{ activeProvider.base_url }}</dd>
                </div>
                <div>
                  <dt>当前模型</dt>
                  <dd>{{ activeProvider.default_model }}</dd>
                </div>
                <div>
                  <dt>API Key</dt>
                  <dd>{{ activeProvider.api_key_masked || '--' }}</dd>
                </div>
                <div>
                  <dt>状态</dt>
                  <dd>{{ activeProvider.enabled ? 'Enabled' : 'Disabled' }}</dd>
                </div>
                <div>
                  <dt>思考模式</dt>
                  <dd>{{ activeProvider.enable_thinking ? '开启' : '关闭' }}</dd>
                </div>
                <div v-if="activeProvider.enable_thinking">
                  <dt>推理强度</dt>
                  <dd>{{ activeProvider.reasoning_effort }}</dd>
                </div>
              </dl>
              <Button
                label="测试连接"
                icon="pi pi-bolt"
                class="p-button p-button--accent"
                :loading="testingId === activeProvider.id"
                @click="runProviderTest(activeProvider)"
              />
            </div>
            <div v-else class="empty-state admin-empty">尚未配置 active Provider</div>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">测试区</h3>
                <p class="panel-subtitle">可测试单个 Provider 或当前 active Provider。</p>
              </div>
            </div>
            <div class="test-panel">
              <label class="field-stack">
                <span class="field-stack__label">Provider 测试 prompt</span>
                <textarea v-model="testPrompt" class="admin-textarea" rows="3"></textarea>
              </label>
              <label class="field-stack">
                <span class="field-stack__label">Active 对话测试</span>
                <textarea v-model="activeChatMessage" class="admin-textarea" rows="3"></textarea>
              </label>
              <label class="field-stack">
                <span class="field-stack__label">可选模型覆盖</span>
                <InputText v-model="activeChatModel" placeholder="留空则使用默认模型" />
              </label>
              <Button
                label="测试 Active Chat"
                icon="pi pi-send"
                class="p-button p-button--accent"
                :disabled="!activeProvider"
                :loading="testingId === 'active-chat'"
                @click="runActiveChatTest"
              />
            </div>
          </div>
        </section>
      </section>

      <section v-if="providerTestResult || chatTestResult" class="surface-panel">
        <div class="surface-panel__content">
          <h3 class="panel-title">测试结果</h3>
          <div class="test-result-grid">
            <div v-if="providerTestResult" class="test-result" :class="{ 'is-failed': !providerTestResult.success }">
              <span class="terminal-note">Provider 测试</span>
              <strong>{{ providerTestResult.success ? '成功' : providerTestResult.error_code }}</strong>
              <p>{{ providerTestResult.content || providerTestResult.message }}</p>
              <small v-if="providerTestResult.latency_ms !== null">{{ providerTestResult.latency_ms }} ms · {{ providerTestResult.model }}</small>
            </div>
            <div v-if="chatTestResult" class="test-result" :class="{ 'is-failed': !chatTestResult.success }">
              <span class="terminal-note">Active Chat</span>
              <strong>{{ chatTestResult.success ? '成功' : chatTestResult.error_code }}</strong>
              <p>{{ chatTestResult.content || chatTestResult.message }}</p>
              <small v-if="chatTestResult.model">{{ chatTestResult.model }}</small>
            </div>
          </div>
        </div>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">Provider 列表</h3>
              <p class="panel-subtitle">同一时间只能有一个 Active Provider。</p>
            </div>
          </div>
          <div v-if="providers.length" class="table-shell">
            <table class="admin-provider-table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>类型</th>
                  <th>Base URL</th>
                  <th>默认模型</th>
                  <th>Token Profile</th>
                  <th>API Key</th>
                  <th>Enabled</th>
                  <th>思考模式</th>
                  <th>推理强度</th>
                  <th>Active</th>
                  <th class="cell-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="provider in providers" :key="provider.id">
                  <td>{{ provider.name }}</td>
                  <td>{{ provider.provider_type }}</td>
                  <td class="cell-url">{{ provider.base_url }}</td>
                  <td>{{ provider.default_model }}</td>
                  <td class="cell-token-profile">
                    {{ provider.context_window_tokens.toLocaleString() }} /
                    {{ provider.input_token_limit.toLocaleString() }} /
                    {{ provider.output_token_limit.toLocaleString() }}
                  </td>
                  <td>{{ provider.api_key_masked || '--' }}</td>
                  <td><Tag :value="provider.enabled ? 'YES' : 'NO'" :class="provider.enabled ? 'p-tag--positive' : 'p-tag--negative'" /></td>
                  <td>{{ provider.enable_thinking ? '开启' : '关闭' }}</td>
                  <td>{{ provider.enable_thinking ? provider.reasoning_effort : '--' }}</td>
                  <td><Tag :value="provider.is_active ? 'ACTIVE' : 'STANDBY'" :class="provider.is_active ? 'p-tag--accent' : ''" /></td>
                  <td class="cell-actions">
                    <div class="row-actions">
                      <Button label="编辑" icon="pi pi-pencil" class="p-button p-button--ghost" @click="openEditForm(provider)" />
                      <Button
                        label="激活"
                        icon="pi pi-check-circle"
                        class="p-button p-button--ghost"
                        :disabled="provider.is_active || !provider.enabled"
                        :loading="activatingId === provider.id"
                        @click="activateProvider(provider)"
                      />
                      <Button
                        label="测试"
                        icon="pi pi-bolt"
                        class="p-button p-button--ghost"
                        :loading="testingId === provider.id"
                        @click="runProviderTest(provider)"
                      />
                      <Button
                        label="删除"
                        icon="pi pi-trash"
                        class="p-button p-button--ghost danger-button"
                        :loading="deletingId === provider.id"
                        @click="removeProvider(provider)"
                      />
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-state">暂无 Provider 配置</div>
        </div>
      </section>
    </template>

    <div v-if="showForm" class="admin-dialog-backdrop" @click.self="closeForm">
      <section class="surface-panel admin-dialog">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <p class="eyebrow">{{ editingProvider ? 'EDIT' : 'CREATE' }}</p>
              <h3 class="panel-title">{{ editingProvider ? '编辑 Provider' : '新增 Provider' }}</h3>
            </div>
            <Button icon="pi pi-times" class="p-button p-button--ghost" aria-label="关闭" @click="closeForm" />
          </div>

          <form class="admin-provider-form" @submit.prevent="saveProvider">
            <label class="field-stack">
              <span class="field-stack__label">Provider 名称</span>
              <InputText v-model="form.name" required placeholder="Bailian / Xiaomi / OpenAI" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">Provider 类型</span>
              <select v-model="form.provider_type" class="admin-select">
                <option value="openai_compatible">openai_compatible</option>
              </select>
            </label>
            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">Base URL</span>
              <InputText v-model="form.base_url" required placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">API Key</span>
              <InputText
                v-model="form.api_key"
                type="password"
                :required="!editingProvider"
                :placeholder="editingProvider ? '留空则不修改' : '仅保存到后端配置文件'"
              />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">默认模型</span>
              <InputText v-model="form.default_model" required placeholder="deepseek-v4-pro" />
            </label>
            <label class="field-stack field-stack--wide">
              <span class="field-stack__label">可选模型列表</span>
              <InputText v-model="form.available_models_text" placeholder="model-a, model-b" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">Temperature</span>
              <input v-model.number="form.temperature" class="admin-input" type="number" min="0" max="2" step="0.1" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">上下文窗口 Token</span>
              <input v-model.number="form.context_window_tokens" class="admin-input" type="number" min="1" step="1000" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">输入 Token 上限</span>
              <input v-model.number="form.input_token_limit" class="admin-input" type="number" min="1" step="1000" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">输出 Token 上限</span>
              <input v-model.number="form.output_token_limit" class="admin-input" type="number" min="1" step="100" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">Timeout 秒</span>
              <input v-model.number="form.timeout_seconds" class="admin-input" type="number" min="1" max="300" />
            </label>
            <p class="admin-provider-form__hint field-stack--wide">
              输出 Token 上限会作为 max_tokens 发送给模型；输入 Token 上限用于本系统控制工具结果和证据包大小；上下文窗口必须大于或等于输入 + 输出。
              Daily Review 当前建议最低：Context 120K / Input 100K / Output 8K；MiniMax 2.7 推荐：200K / 150K / 10K。
            </p>
            <label class="admin-checkbox">
              <input v-model="form.enabled" type="checkbox" />
              <span>Enabled</span>
            </label>
            <label class="admin-checkbox">
              <input v-model="form.enable_thinking" type="checkbox" />
              <span>开启思考模式</span>
              <p class="admin-provider-form__hint" style="margin: 4px 0 0 28px; font-size: 0.82rem; color: var(--color-text-secondary);">
                开启后模型可能返回 reasoning_content。工具调用和结构化 JSON 场景建议关闭。
              </p>
            </label>
            <label v-if="form.enable_thinking" class="field-stack">
              <span class="field-stack__label">推理强度 (reasoning_effort)</span>
              <select v-model="form.reasoning_effort" class="admin-select">
                <option value="high">high</option>
                <option value="max">max</option>
              </select>
            </label>
            <div class="admin-form-actions">
              <Button label="取消" type="button" class="p-button p-button--ghost" @click="closeForm" />
              <Button label="保存" icon="pi pi-save" type="submit" class="p-button p-button--accent" :loading="saving" />
            </div>
          </form>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.admin-llm-page__header {
  align-items: center;
}

.admin-llm-page__title {
  font-size: 1.5rem;
}

.admin-tabs {
  display: flex;
  gap: 12px;
}

.admin-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr);
  gap: var(--space-4);
}

.active-provider,
.test-panel,
.provider-meta,
.test-result-grid {
  display: grid;
  gap: var(--space-3);
}

.active-provider__main {
  display: grid;
  gap: 4px;
  padding: 16px;
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.72);
  border: 1px solid rgba(129, 160, 207, 0.12);
}

.provider-meta {
  margin: 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.provider-meta div {
  min-width: 0;
  padding: 14px;
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.52);
}

.provider-meta dt {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.provider-meta dd {
  margin: 6px 0 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}

.admin-input,
.admin-textarea,
.admin-select {
  width: 100%;
  border: 1px solid rgba(129, 160, 207, 0.16);
  border-radius: 12px;
  background: rgba(10, 18, 32, 0.85);
  color: var(--color-text-primary);
  outline: none;
}

.admin-input {
  min-height: 44px;
  padding: 0.8rem 0.95rem;
}

.admin-textarea {
  resize: vertical;
  min-height: 96px;
  padding: 0.85rem 0.95rem;
}

.admin-select {
  min-height: 44px;
  padding: 0 0.95rem;
}

.admin-notice {
  margin: 0;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  color: var(--color-positive);
  background: rgba(9, 47, 39, 0.48);
  border: 1px solid rgba(52, 210, 163, 0.18);
}

.test-result-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: var(--space-3);
}

.test-result {
  display: grid;
  gap: 8px;
  padding: 16px;
  border-radius: var(--radius-md);
  background: rgba(9, 47, 39, 0.42);
  border: 1px solid rgba(52, 210, 163, 0.18);
}

.test-result.is-failed {
  background: rgba(55, 18, 28, 0.5);
  border-color: rgba(255, 107, 125, 0.2);
}

.test-result p {
  margin: 0;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
}

.admin-provider-table {
  width: 100%;
  min-width: 1720px;
  border-collapse: collapse;
}

.admin-provider-table th,
.admin-provider-table td {
  padding: 0.9rem 1rem;
  border-bottom: 1px solid rgba(129, 160, 207, 0.12);
  text-align: left;
  vertical-align: top;
}

.admin-provider-table th {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: rgba(14, 24, 41, 0.94);
}

.cell-url {
  max-width: 260px;
  overflow-wrap: anywhere;
}

.cell-token-profile {
  min-width: 180px;
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}

.cell-actions {
  min-width: 500px;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.row-actions :deep(.p-button) {
  flex: 0 1 auto;
  width: auto;
  min-width: max-content;
}

.danger-button {
  color: var(--color-negative);
}

.admin-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(5, 12, 24, 0.72);
  backdrop-filter: blur(12px);
}

.admin-dialog {
  width: min(880px, 100%);
  max-height: min(86vh, 920px);
  overflow: auto;
}

.admin-provider-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.field-stack--wide,
.admin-form-actions {
  grid-column: 1 / -1;
}

.admin-provider-form__hint {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 0.88rem;
  line-height: 1.6;
}

.admin-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  align-self: end;
  color: var(--color-text-secondary);
}

.admin-checkbox input {
  width: 18px;
  height: 18px;
  accent-color: var(--color-accent);
}

.admin-form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.admin-empty {
  min-height: 180px;
}

@media (max-width: 980px) {
  .admin-layout,
  .test-result-grid,
  .provider-meta,
  .admin-provider-form {
    grid-template-columns: 1fr;
  }
}
</style>
