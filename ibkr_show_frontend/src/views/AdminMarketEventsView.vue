<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import Tag from 'primevue/tag'

import {
  deleteAdminMarketEventCredential,
  getAdminMarketEventSources,
  saveAdminMarketEventCredential,
  testAdminMarketEventSource,
  updateAdminMarketEventSource,
} from '@/api/marketEvents'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type { MarketEventSourceConfig, MarketEventTestStatus } from '@/types/marketEvent'

const router = useRouter()
const loading = ref(false)
const actionSource = ref('')
const sources = ref<MarketEventSourceConfig[]>([])
const editingSource = ref<string | null>(null)
const credentialValue = ref('')
const errorMessage = ref('')
const noticeMessage = ref('')
const testResult = ref<{ source_code: string; status: MarketEventTestStatus; message: string } | null>(null)

const configuredCredentialCount = computed(() => sources.value.filter((source) => source.credential_configured).length)
const requiredCredentialCount = computed(() => sources.value.filter((source) => source.requires_api_key).length)

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

async function loadSources() {
  loading.value = true
  errorMessage.value = ''
  try {
    sources.value = await getAdminMarketEventSources()
  } catch (error) {
    sources.value = []
    errorMessage.value = errorText(error, '加载宏观数据源配置失败')
  } finally {
    loading.value = false
  }
}

async function toggleSource(src: MarketEventSourceConfig) {
  actionSource.value = `${src.source_code}:toggle`
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await updateAdminMarketEventSource(src.source_code, { enabled: !src.enabled })
    noticeMessage.value = `${src.source_code} 已${src.enabled ? '停用' : '启用'}`
    await loadSources()
  } catch (error) {
    errorMessage.value = errorText(error, `${src.source_code} 状态更新失败`)
  } finally {
    actionSource.value = ''
  }
}

async function testSource(sourceCode: string) {
  actionSource.value = `${sourceCode}:test`
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    testResult.value = await testAdminMarketEventSource(sourceCode)
    await loadSources()
  } catch (error) {
    testResult.value = { source_code: sourceCode, status: 'FAILED', message: errorText(error, '测试失败') }
  } finally {
    actionSource.value = ''
  }
}

function startEdit(sourceCode: string) {
  editingSource.value = sourceCode
  credentialValue.value = ''
  noticeMessage.value = ''
}

function cancelEdit() {
  editingSource.value = null
  credentialValue.value = ''
}

async function saveCredential(sourceCode: string, credentialKey: string) {
  if (!credentialValue.value.trim()) {
    errorMessage.value = 'API Key 不能为空'
    return
  }
  actionSource.value = `${sourceCode}:save`
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await saveAdminMarketEventCredential(sourceCode, {
      credential_key: credentialKey,
      value: credentialValue.value,
    })
    editingSource.value = null
    credentialValue.value = ''
    noticeMessage.value = `${sourceCode} Key 已保存`
    await loadSources()
  } catch (error) {
    errorMessage.value = errorText(error, `${sourceCode} Key 保存失败`)
  } finally {
    actionSource.value = ''
  }
}

async function deleteCredential(sourceCode: string) {
  if (!window.confirm(`确认删除 ${sourceCode} API Key？`)) {
    return
  }
  actionSource.value = `${sourceCode}:delete`
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await deleteAdminMarketEventCredential(sourceCode)
    noticeMessage.value = `${sourceCode} Key 已删除`
    await loadSources()
  } catch (error) {
    errorMessage.value = errorText(error, `${sourceCode} Key 删除失败`)
  } finally {
    actionSource.value = ''
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

function credentialStatus(source: MarketEventSourceConfig): string {
  if (!source.requires_api_key) return '无需 Key'
  return source.credential_configured ? '已配置' : '未配置'
}

function credentialTone(source: MarketEventSourceConfig): string {
  if (!source.requires_api_key) return 'p-tag--secondary'
  return source.credential_configured ? 'p-tag--positive' : 'p-tag--negative'
}

function checkTone(status?: MarketEventTestStatus | null): string {
  if (status === 'SUCCESS') return 'p-tag--positive'
  if (status === 'FAILED') return 'p-tag--negative'
  if (status === 'SKIPPED') return 'p-tag--secondary'
  return 'p-tag--secondary'
}

onMounted(loadSources)
</script>

<template>
  <section class="page-section admin-market-events-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header admin-market-events-page__header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-market-events-page__title">宏观数据源配置</h2>
            <p class="panel-subtitle">管理重点事件中台的数据源、API Key、连接测试与启用状态。</p>
          </div>
          <div class="admin-market-events-page__tags">
            <Tag :value="`${sources.length || 0} SOURCES`" class="p-tag--info" />
            <Tag :value="`${configuredCredentialCount}/${requiredCredentialCount} KEYS`" :class="configuredCredentialCount === requiredCredentialCount ? 'p-tag--positive' : 'p-tag--secondary'" />
          </div>
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="宏观数据源" icon="pi pi-calendar-clock" class="terminal-nav__button is-active" />
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

      <section v-if="sources.length" class="admin-market-events-page__grid">
        <article v-for="src in sources" :key="src.source_code" class="surface-panel admin-market-events-page__card">
          <div class="surface-panel__content">
            <div class="admin-market-events-page__card-header">
              <div>
                <span class="terminal-note">{{ src.source_code }}</span>
                <h3 class="panel-title admin-market-events-page__card-title">{{ src.source_name }}</h3>
              </div>
              <div class="admin-market-events-page__card-tags">
                <Tag :value="src.enabled ? 'ENABLED' : 'DISABLED'" :class="src.enabled ? 'p-tag--positive' : 'p-tag--secondary'" />
                <Tag :value="credentialStatus(src)" :class="credentialTone(src)" />
              </div>
            </div>

            <p class="admin-market-events-page__description">{{ src.description }}</p>

            <dl class="admin-market-events-page__details">
              <div>
                <dt>API Key</dt>
                <dd>{{ src.requires_api_key ? (src.credential_key_name || 'api_key') : '无需配置' }}</dd>
              </div>
              <div v-if="src.masked_value">
                <dt>脱敏值</dt>
                <dd><code>{{ src.masked_value }}</code></dd>
              </div>
              <div>
                <dt>最近测试</dt>
                <dd>
                  <Tag v-if="src.last_check_status" :value="src.last_check_status" :class="checkTone(src.last_check_status)" />
                  <span v-else>--</span>
                </dd>
              </div>
              <div v-if="src.last_check_at">
                <dt>测试时间</dt>
                <dd>{{ formatTime(src.last_check_at) }}</dd>
              </div>
              <div v-if="src.last_error" class="is-error">
                <dt>错误</dt>
                <dd>{{ src.last_error }}</dd>
              </div>
            </dl>

            <div class="admin-market-events-page__links">
              <a v-if="src.apply_url" :href="src.apply_url" target="_blank" rel="noopener">申请 Key</a>
              <a v-if="src.doc_url" :href="src.doc_url" target="_blank" rel="noopener">官方文档</a>
            </div>

            <div v-if="src.requires_api_key" class="admin-market-events-page__credential">
              <template v-if="editingSource === src.source_code">
                <label class="field-stack">
                  <span class="field-stack__label">{{ src.credential_key_name || 'API Key' }}</span>
                  <input
                    v-model="credentialValue"
                    class="admin-input"
                    type="password"
                    autocomplete="off"
                    :placeholder="src.credential_configured ? '留空不会保存；请输入新 Key' : '输入 API Key'"
                  />
                </label>
                <p class="admin-market-events-page__hint">Key 加密保存在后端配置存储中，前端只展示脱敏值。</p>
                <div class="admin-form-actions">
                  <Button label="保存" icon="pi pi-save" class="p-button p-button--accent" :loading="actionSource === `${src.source_code}:save`" @click="saveCredential(src.source_code, src.credential_key_name || 'api_key')" />
                  <Button label="取消" class="p-button p-button--ghost" @click="cancelEdit" />
                </div>
              </template>
              <div v-else class="admin-form-actions">
                <Button :label="src.credential_configured ? '更新 Key' : '填写 Key'" icon="pi pi-key" class="p-button p-button--ghost" @click="startEdit(src.source_code)" />
                <Button v-if="src.credential_configured" label="删除 Key" icon="pi pi-trash" class="p-button p-button--ghost danger-button" :loading="actionSource === `${src.source_code}:delete`" @click="deleteCredential(src.source_code)" />
              </div>
            </div>

            <div class="admin-market-events-page__actions">
              <Button :label="src.enabled ? '停用' : '启用'" :icon="src.enabled ? 'pi pi-pause' : 'pi pi-play'" class="p-button p-button--ghost" :loading="actionSource === `${src.source_code}:toggle`" @click="toggleSource(src)" />
              <Button label="测试连接" icon="pi pi-bolt" class="p-button p-button--accent" :loading="actionSource === `${src.source_code}:test`" @click="testSource(src.source_code)" />
            </div>
          </div>
        </article>
      </section>

      <section v-else class="surface-panel">
        <div class="surface-panel__content empty-state">
          暂无宏观数据源配置。请刷新或检查后端初始化状态。
        </div>
      </section>

      <section v-if="testResult" class="surface-panel admin-market-events-page__test-result">
        <div class="surface-panel__content">
          <span class="terminal-note">连接测试</span>
          <h3 class="panel-title">{{ testResult.source_code }}: {{ testResult.status }}</h3>
          <p>{{ testResult.message }}</p>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.admin-market-events-page__header {
  align-items: flex-start;
  gap: 1rem;
}

.admin-market-events-page__title {
  font-size: 1.5rem;
}

.admin-market-events-page__tags,
.admin-market-events-page__card-tags,
.admin-form-actions,
.admin-market-events-page__actions,
.admin-market-events-page__links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.admin-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}

.admin-market-events-page__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1rem;
}

.admin-market-events-page__card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.admin-market-events-page__card-title {
  margin-top: 0.25rem;
  font-size: 1.05rem;
}

.admin-market-events-page__description {
  min-height: 3.2rem;
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.admin-market-events-page__details {
  display: grid;
  gap: 0.55rem;
  margin: 1rem 0;
}

.admin-market-events-page__details div {
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: 0.75rem;
  align-items: center;
}

.admin-market-events-page__details dt {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.admin-market-events-page__details dd {
  margin: 0;
  min-width: 0;
}

.admin-market-events-page__details code {
  overflow-wrap: anywhere;
}

.admin-market-events-page__details .is-error dd {
  color: var(--color-danger);
}

.admin-market-events-page__links {
  margin-bottom: 1rem;
}

.admin-market-events-page__links a {
  color: var(--color-accent);
  font-size: 0.88rem;
  text-decoration: none;
}

.admin-market-events-page__links a:hover {
  text-decoration: underline;
}

.admin-market-events-page__credential {
  border-top: 1px solid var(--color-border-subtle);
  padding-top: 1rem;
}

.admin-market-events-page__hint {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
  margin: 0;
}

.admin-input {
  background: rgba(8, 20, 36, 0.55);
  border: 1px solid var(--color-border-subtle);
  border-radius: 6px;
  color: var(--color-text-primary);
  min-height: 2.4rem;
  padding: 0.55rem 0.7rem;
}

.admin-market-events-page__actions {
  justify-content: flex-end;
  margin-top: 1rem;
}

.admin-market-events-page__test-result {
  margin-top: 1rem;
}

@media (max-width: 720px) {
  .admin-market-events-page__card-header,
  .admin-market-events-page__header {
    flex-direction: column;
  }
}
</style>
