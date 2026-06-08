<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'

import {
  fetchIbkrSettings,
  importIbkrHistory,
  pullDailyFromIbkr,
  testIbkrConnection,
  updateIbkrSettings,
} from '@/api/adminIbkr'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type { IbkrFlexSettings, IbkrFlexTestResponse, IbkrImportResponse } from '@/types/adminIbkr'

const router = useRouter()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const pulling = ref(false)
const importing = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const settings = ref<IbkrFlexSettings | null>(null)
const testResult = ref<IbkrFlexTestResponse | null>(null)
const importResult = ref<IbkrImportResponse | null>(null)
const selectedFile = ref<File | null>(null)

const form = reactive({
  query_id: '',
  flex_token: '',
})

const importRows = computed(() => {
  if (!importResult.value) {
    return []
  }
  return Object.values(importResult.value.result)
})

function applySettings(value: IbkrFlexSettings): void {
  settings.value = value
  form.query_id = value.query_id
  form.flex_token = ''
}

async function loadData(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    applySettings(await fetchIbkrSettings())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 IBKR 配置失败'
  } finally {
    loading.value = false
  }
}

async function saveSettings(): Promise<void> {
  saving.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  testResult.value = null
  try {
    const response = await updateIbkrSettings({
      query_id: form.query_id.trim(),
      flex_token: form.flex_token.trim() || undefined,
    })
    applySettings(response.settings)
    noticeMessage.value = response.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存 IBKR 配置失败'
  } finally {
    saving.value = false
  }
}

async function runConnectionTest(): Promise<void> {
  testing.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  testResult.value = null
  try {
    testResult.value = await testIbkrConnection()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测试 IBKR 连接失败'
  } finally {
    testing.value = false
  }
}

async function runPullDaily(): Promise<void> {
  pulling.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  importResult.value = null
  try {
    importResult.value = await pullDailyFromIbkr()
    noticeMessage.value = importResult.value.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '从 IBKR 拉取失败'
  } finally {
    pulling.value = false
  }
}

function handleFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files?.[0] ?? null
  importResult.value = null
}

async function runImportHistory(): Promise<void> {
  if (!selectedFile.value) {
    errorMessage.value = '请先选择 IBKR Flex CSV 文件'
    return
  }

  importing.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  importResult.value = null
  try {
    importResult.value = await importIbkrHistory(selectedFile.value)
    noticeMessage.value = importResult.value.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '历史数据导入失败'
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <section class="page-section admin-ibkr-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header admin-ibkr-page__header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-ibkr-page__title">IBKR 数据源</h2>
            <p class="panel-subtitle">配置 Flex Web Service，并从后台导入 IBKR 历史数据。</p>
          </div>
          <Tag :value="settings?.has_flex_token ? 'TOKEN SAVED' : 'TOKEN MISSING'" :class="settings?.has_flex_token ? 'p-tag--positive' : 'p-tag--negative'" />
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button is-active" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="宏观数据源" icon="pi pi-calendar-clock" class="terminal-nav__button" title="重点事件数据源配置" @click="router.push('/admin/market-events')" />
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
                <h3 class="panel-title">Flex 配置</h3>
                <p class="panel-subtitle">Query ID 与 FLEX_TOKEN 保存到后端配置文件，worker 会优先读取这份配置。</p>
              </div>
            </div>

            <form class="ibkr-settings-form" @submit.prevent="saveSettings">
              <label class="field-stack">
                <span class="field-stack__label">Query ID</span>
                <InputText v-model="form.query_id" required placeholder="例如 1419985" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">FLEX_TOKEN</span>
                <InputText
                  v-model="form.flex_token"
                  type="password"
                  :placeholder="settings?.has_flex_token ? `已保存：${settings.flex_token_masked}，留空不修改` : '从 IBKR Flex Web Service 获取'"
                />
              </label>

              <dl class="ibkr-meta">
                <div>
                  <dt>当前 Query ID</dt>
                  <dd>{{ settings?.query_id || '--' }}</dd>
                </div>
                <div>
                  <dt>Token</dt>
                  <dd>{{ settings?.flex_token_masked || '--' }}</dd>
                </div>
              </dl>

              <div class="admin-form-actions">
                <Button label="保存配置" icon="pi pi-save" type="submit" class="p-button p-button--accent" :loading="saving" />
                <Button label="测试连接" icon="pi pi-bolt" type="button" class="p-button p-button--ghost" :loading="testing" @click="runConnectionTest" />
              </div>
            </form>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">历史数据导入</h3>
                <p class="panel-subtitle">上传 IBKR Flex CSV，后端复用现有 worker 导入链路写入 Elasticsearch。</p>
              </div>
            </div>

            <div class="upload-panel">
              <label class="file-drop">
                <input type="file" accept=".csv,text/csv,text/plain" @change="handleFileChange" />
                <span class="file-drop__icon pi pi-upload"></span>
                <strong>{{ selectedFile?.name || '选择历史 CSV 文件' }}</strong>
                <small v-if="selectedFile">{{ (selectedFile.size / 1024).toFixed(1) }} KB</small>
              </label>

              <div class="admin-form-actions">
                <Button
                  label="导入历史数据"
                  icon="pi pi-file-import"
                  class="p-button p-button--accent"
                  :disabled="!selectedFile"
                  :loading="importing"
                  @click="runImportHistory"
                />
                <Button label="从 IBKR 拉取最新" icon="pi pi-cloud-download" class="p-button p-button--ghost" :loading="pulling" @click="runPullDaily" />
              </div>
            </div>
          </div>
        </section>
      </section>

      <section v-if="testResult || importResult" class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">执行结果</h3>
              <p class="panel-subtitle">导入结果按 Elasticsearch index 汇总。</p>
            </div>
          </div>

          <div v-if="testResult" class="result-card" :class="{ 'is-failed': !testResult.success }">
            <span class="terminal-note">连接测试</span>
            <strong>{{ testResult.success ? '成功' : '失败' }}</strong>
            <p>{{ testResult.message || testResult.reference_code }}</p>
          </div>

          <div v-if="importResult" class="import-result">
            <div class="result-card">
              <span class="terminal-note">文件</span>
              <strong>{{ importResult.filename }}</strong>
              <p>{{ importResult.message }}</p>
            </div>
            <div class="table-shell">
              <table class="ibkr-result-table">
                <thead>
                  <tr>
                    <th>Index</th>
                    <th>Upserted</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in importRows" :key="row.index">
                    <td>{{ row.index }}</td>
                    <td>{{ row.upserted }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.admin-ibkr-page__header {
  align-items: center;
}

.admin-ibkr-page__title {
  font-size: 1.5rem;
}

.admin-tabs {
  display: flex;
  gap: 12px;
}

.admin-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.85fr);
  gap: var(--space-4);
}

.ibkr-settings-form,
.upload-panel,
.import-result {
  display: grid;
  gap: var(--space-3);
}

.ibkr-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.ibkr-meta div,
.result-card {
  min-width: 0;
  padding: 16px;
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.52);
  border: 1px solid rgba(129, 160, 207, 0.12);
}

.ibkr-meta dt {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.ibkr-meta dd {
  margin: 6px 0 0;
  overflow-wrap: anywhere;
  font-weight: 600;
}

.admin-notice {
  margin: 0;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  color: var(--color-positive);
  background: rgba(9, 47, 39, 0.48);
  border: 1px solid rgba(52, 210, 163, 0.18);
}

.admin-form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.file-drop {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 10px;
  min-height: 190px;
  padding: 28px;
  border: 1px dashed rgba(129, 160, 207, 0.28);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.48);
  color: var(--color-text-primary);
  cursor: pointer;
}

.file-drop input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.file-drop__icon {
  font-size: 2rem;
  color: var(--color-accent);
}

.file-drop small,
.result-card p {
  margin: 0;
  color: var(--color-text-secondary);
}

.result-card {
  display: grid;
  gap: 8px;
}

.result-card.is-failed {
  background: rgba(55, 18, 28, 0.5);
  border-color: rgba(255, 107, 125, 0.2);
}

.ibkr-result-table {
  width: 100%;
  min-width: 520px;
  border-collapse: collapse;
}

.ibkr-result-table th,
.ibkr-result-table td {
  padding: 0.9rem 1rem;
  border-bottom: 1px solid rgba(129, 160, 207, 0.12);
  text-align: left;
}

.ibkr-result-table th {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: rgba(14, 24, 41, 0.94);
}

@media (max-width: 980px) {
  .admin-layout,
  .ibkr-meta {
    grid-template-columns: 1fr;
  }
}
</style>
