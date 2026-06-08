<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'

import { fetchEmailSettings, sendEmailTest, sendLatestAccountSnapshot, sendLatestDailyReview, updateEmailSettings } from '@/api/adminEmail'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type { EmailSendLatestResponse, EmailSettings, EmailTestResponse } from '@/types/adminEmail'

const router = useRouter()
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const sendingReview = ref(false)
const sendingSnapshot = ref(false)
const forceRefreshDailyReview = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const settings = ref<EmailSettings | null>(null)
const testResult = ref<EmailTestResponse | null>(null)
const reviewSendResult = ref<EmailSendLatestResponse | null>(null)
const snapshotSendResult = ref<EmailSendLatestResponse | null>(null)

const form = reactive({
  smtp_host: '',
  smtp_port: '465',
  smtp_username: '',
  smtp_password: '',
  smtp_use_ssl: true,
  smtp_use_starttls: false,
  email_from: '',
  daily_review_email_enabled: false,
  daily_review_email_to: '',
  daily_review_subject_prefix: 'IBKR每日持仓复盘',
  site_base_url: '',
  daily_snapshot_email_enabled: false,
  daily_snapshot_email_to: '',
  daily_snapshot_subject_prefix: 'IBKR Daily Snapshot',
})

const passwordPlaceholder = computed(() =>
  settings.value?.has_smtp_password ? `已保存：${settings.value.smtp_password_masked}，留空不修改` : '邮箱 SMTP 授权码',
)
const canSendDailyReview = computed(() =>
  form.daily_review_email_enabled && Boolean(form.daily_review_email_to.trim()) && !sendingReview.value,
)
const canSendAccountSnapshot = computed(() =>
  form.daily_snapshot_email_enabled && Boolean(form.daily_snapshot_email_to.trim()) && !sendingSnapshot.value,
)

function applySettings(value: EmailSettings): void {
  settings.value = value
  form.smtp_host = value.smtp_host
  form.smtp_port = String(value.smtp_port)
  form.smtp_username = value.smtp_username
  form.smtp_password = ''
  form.smtp_use_ssl = value.smtp_use_ssl
  form.smtp_use_starttls = value.smtp_use_starttls
  form.email_from = value.email_from
  form.daily_review_email_enabled = value.daily_review_email_enabled
  form.daily_review_email_to = value.daily_review_email_to
  form.daily_review_subject_prefix = value.daily_review_subject_prefix
  form.site_base_url = value.site_base_url || ''
  form.daily_snapshot_email_enabled = value.daily_snapshot_email_enabled
  form.daily_snapshot_email_to = value.daily_snapshot_email_to
  form.daily_snapshot_subject_prefix = value.daily_snapshot_subject_prefix
}

function normalizeTls(mode: 'ssl' | 'starttls'): void {
  if (mode === 'ssl' && form.smtp_use_ssl) {
    form.smtp_use_starttls = false
  }
  if (mode === 'starttls' && form.smtp_use_starttls) {
    form.smtp_use_ssl = false
  }
}

async function loadData(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    applySettings(await fetchEmailSettings())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载邮件配置失败'
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
    const response = await updateEmailSettings({
      smtp_host: form.smtp_host.trim(),
      smtp_port: Number(form.smtp_port),
      smtp_username: form.smtp_username.trim(),
      smtp_password: form.smtp_password.trim() || undefined,
      smtp_use_ssl: form.smtp_use_ssl,
      smtp_use_starttls: form.smtp_use_starttls,
      email_from: form.email_from.trim(),
      daily_review_email_enabled: form.daily_review_email_enabled,
      daily_review_email_to: form.daily_review_email_to.trim(),
      daily_review_subject_prefix: form.daily_review_subject_prefix.trim(),
      site_base_url: form.site_base_url.trim(),
      daily_snapshot_email_enabled: form.daily_snapshot_email_enabled,
      daily_snapshot_email_to: form.daily_snapshot_email_to.trim(),
      daily_snapshot_subject_prefix: form.daily_snapshot_subject_prefix.trim(),
    })
    applySettings(response.settings)
    noticeMessage.value = response.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存邮件配置失败'
  } finally {
    saving.value = false
  }
}

async function runTestSend(): Promise<void> {
  testing.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  testResult.value = null
  try {
    testResult.value = await sendEmailTest()
    noticeMessage.value = testResult.value.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测试邮件发送失败'
  } finally {
    testing.value = false
  }
}

async function runSendLatestDailyReview(): Promise<void> {
  if (sendingReview.value || !form.daily_review_email_enabled || !form.daily_review_email_to.trim()) {
    return
  }
  sendingReview.value = true
  errorMessage.value = ''
  reviewSendResult.value = null
  try {
    reviewSendResult.value = await sendLatestDailyReview({ force_refresh: forceRefreshDailyReview.value })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '每日复盘邮件发送失败'
  } finally {
    sendingReview.value = false
  }
}

async function runSendLatestAccountSnapshot(): Promise<void> {
  if (sendingSnapshot.value || !form.daily_snapshot_email_enabled || !form.daily_snapshot_email_to.trim()) {
    return
  }
  sendingSnapshot.value = true
  errorMessage.value = ''
  snapshotSendResult.value = null
  try {
    snapshotSendResult.value = await sendLatestAccountSnapshot()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '账户快照邮件发送失败'
  } finally {
    sendingSnapshot.value = false
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <section class="page-section admin-email-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header admin-email-page__header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-email-page__title">邮件发送配置</h2>
            <p class="panel-subtitle">SMTP 发件配置共用，两类邮件的收件人和启用开关分开。</p>
          </div>
          <div class="admin-email-page__tags">
            <Tag :value="settings?.daily_review_email_enabled ? 'DAILY REVIEW ON' : 'DAILY REVIEW OFF'" :class="settings?.daily_review_email_enabled ? 'p-tag--positive' : 'p-tag--secondary'" />
            <Tag :value="settings?.daily_snapshot_email_enabled ? 'GMAIL SNAPSHOT ON' : 'GMAIL SNAPSHOT OFF'" :class="settings?.daily_snapshot_email_enabled ? 'p-tag--positive' : 'p-tag--secondary'" />
          </div>
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button is-active" />
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
                <h3 class="panel-title">SMTP 发件配置</h3>
                <p class="panel-subtitle">两类邮件共用 SMTP 发件配置。密码/授权码不会回显明文。</p>
              </div>
            </div>

            <form class="email-settings-form" @submit.prevent="saveSettings">
              <div class="email-form-grid">
                <label class="field-stack">
                  <span class="field-stack__label">SMTP Host</span>
                  <InputText v-model="form.smtp_host" placeholder="smtp.example.com" />
                </label>
                <label class="field-stack">
                  <span class="field-stack__label">SMTP Port</span>
                  <InputText v-model.number="form.smtp_port" type="number" min="1" max="65535" />
                </label>
                <label class="field-stack">
                  <span class="field-stack__label">SMTP Username</span>
                  <InputText v-model="form.smtp_username" autocomplete="username" />
                </label>
                <label class="field-stack">
                  <span class="field-stack__label">SMTP Password/授权码</span>
                  <InputText v-model="form.smtp_password" type="password" autocomplete="new-password" :placeholder="passwordPlaceholder" />
                </label>
              </div>

              <div class="tls-options">
                <label class="check-row">
                  <input v-model="form.smtp_use_ssl" type="checkbox" @change="normalizeTls('ssl')" />
                  <span>SSL</span>
                </label>
                <label class="check-row">
                  <input v-model="form.smtp_use_starttls" type="checkbox" @change="normalizeTls('starttls')" />
                  <span>STARTTLS</span>
                </label>
              </div>

              <div class="email-form-grid">
                <label class="field-stack">
                  <span class="field-stack__label">Email From</span>
                  <InputText v-model="form.email_from" placeholder="IBKR Show <name@example.com>" />
                </label>
                <label class="field-stack">
                  <span class="field-stack__label">Site Base URL</span>
                  <InputText v-model="form.site_base_url" placeholder="https://example.com" />
                </label>
              </div>

              <dl class="email-meta">
                <div>
                  <dt>密码状态</dt>
                  <dd>{{ settings?.smtp_password_masked || '--' }}</dd>
                </div>
                <div>
                  <dt>配置文件</dt>
                  <dd>{{ settings?.config_file || '--' }}</dd>
                </div>
              </dl>
            </form>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">每日持仓复盘邮件</h3>
                <p class="panel-subtitle">每日复盘生成成功后发送给人阅读的摘要邮件。</p>
              </div>
              <label class="check-row">
                <input v-model="form.daily_review_email_enabled" type="checkbox" />
                <span>启用</span>
              </label>
            </div>

            <form class="email-settings-form" @submit.prevent="saveSettings">
              <div class="email-form-grid">
                <label class="field-stack">
                  <span class="field-stack__label">收件人</span>
                  <InputText v-model="form.daily_review_email_to" placeholder="me@example.com, other@example.com" />
                </label>
                <label class="field-stack">
                  <span class="field-stack__label">Subject Prefix</span>
                  <InputText v-model="form.daily_review_subject_prefix" />
                </label>
              </div>
            </form>

            <div class="email-action-row">
              <label class="check-row">
                <input v-model="forceRefreshDailyReview" type="checkbox" />
                <span>强制重新生成</span>
              </label>
              <Button
                label="重新生成并发送最近交易日复盘邮件"
                :icon="sendingReview ? 'pi pi-spin pi-spinner' : 'pi pi-send'"
                type="button"
                class="p-button p-button--accent email-send-button"
                :disabled="!canSendDailyReview"
                :aria-busy="sendingReview"
                @click="runSendLatestDailyReview"
              />
              <span v-if="reviewSendResult" class="terminal-note" :class="{ 'is-failed': !reviewSendResult.success }">
                {{ reviewSendResult.message }}
                <template v-if="reviewSendResult.report_date">({{ reviewSendResult.report_date }})</template>
                <template v-if="reviewSendResult.task_id"> 任务 ID: {{ reviewSendResult.task_id }}</template>
              </span>
            </div>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">ChatGPT / Gmail 快照邮件</h3>
                <p class="panel-subtitle">发送账户快照到 Gmail，供 ChatGPT 通过 Gmail connector 读取最新账户状态。邮件标题固定为 <code>[IBKR Daily Snapshot] {report_date}</code>，方便在 Gmail 中搜索。</p>
              </div>
              <label class="check-row">
                <input v-model="form.daily_snapshot_email_enabled" type="checkbox" />
                <span>启用</span>
              </label>
            </div>

            <form class="email-settings-form" @submit.prevent="saveSettings">
              <div class="email-form-grid">
                <label class="field-stack">
                  <span class="field-stack__label">Gmail 收件人</span>
                  <InputText v-model="form.daily_snapshot_email_to" placeholder="gmail@example.com" />
                </label>
                <label class="field-stack">
                  <span class="field-stack__label">Subject Prefix</span>
                  <InputText v-model="form.daily_snapshot_subject_prefix" />
                </label>
              </div>
              <p class="email-hint">
                快照邮件只包含 report_date 当天数据：当天账户快照、当天全部持仓、当天交易摘要（最多 50 条）、当天现金流摘要（最多 50 条）。<br />
                不发送历史全量交易、历史全量现金流、IBKR Flex Token、LLM API Key、SMTP Password。<br />
                在 Gmail 中搜索 <code>subject:"IBKR Daily Snapshot"</code> 可以找到最新账户快照。
              </p>
            </form>

            <div class="email-action-row">
              <Button
                label="发送最近交易日账户快照邮件"
                :icon="sendingSnapshot ? 'pi pi-spin pi-spinner' : 'pi pi-send'"
                type="button"
                class="p-button p-button--accent email-send-button"
                :disabled="!canSendAccountSnapshot"
                :aria-busy="sendingSnapshot"
                @click="runSendLatestAccountSnapshot"
              />
              <span v-if="snapshotSendResult" class="terminal-note" :class="{ 'is-failed': !snapshotSendResult.success }">
                {{ snapshotSendResult.message }}
                <template v-if="snapshotSendResult.report_date">({{ snapshotSendResult.report_date }})</template>
              </span>
            </div>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">发送状态</h3>
              </div>
            </div>

            <div class="email-status-list">
              <div class="result-card">
                <span class="terminal-note">每日复盘收件人</span>
                <strong>{{ settings?.daily_review_email_to || '--' }}</strong>
              </div>
              <div class="result-card">
                <span class="terminal-note">Gmail 快照收件人</span>
                <strong>{{ settings?.daily_snapshot_email_to || '--' }}</strong>
              </div>
              <div class="result-card">
                <span class="terminal-note">SMTP</span>
                <strong>{{ settings?.smtp_host || '--' }}:{{ settings?.smtp_port || '--' }}</strong>
              </div>
              <div v-if="testResult" class="result-card" :class="{ 'is-failed': !testResult.success }">
                <span class="terminal-note">测试邮件</span>
                <strong>{{ testResult.success ? '成功' : '失败' }}</strong>
                <p>{{ testResult.sent_to.join(', ') }}</p>
              </div>
            </div>

            <div class="admin-form-actions">
              <Button label="保存配置" icon="pi pi-save" type="submit" class="p-button p-button--accent" :loading="saving" @click="saveSettings" />
              <Button label="发送测试邮件" icon="pi pi-send" type="button" class="p-button p-button--ghost" :loading="testing" @click="runTestSend" />
            </div>
          </div>
        </section>
      </section>
    </template>
  </section>
</template>

<style scoped>
.admin-email-page__header {
  align-items: center;
}

.admin-email-page__tags {
  display: flex;
  gap: 8px;
}

.admin-email-page__title {
  font-size: 1.5rem;
}

.admin-tabs,
.admin-form-actions,
.tls-options {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.admin-layout {
  display: grid;
  gap: var(--space-4);
}

.email-settings-form,
.email-status-list {
  display: grid;
  gap: var(--space-3);
}

.email-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.email-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.check-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  color: var(--color-text-primary);
}

.check-row input {
  width: 18px;
  height: 18px;
  accent-color: var(--color-accent);
}

.email-meta div,
.result-card {
  min-width: 0;
  padding: 16px;
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.52);
  border: 1px solid rgba(129, 160, 207, 0.12);
}

.email-meta dt {
  color: var(--color-text-secondary);
  font-size: 0.8rem;
}

.email-meta dd {
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
  justify-content: flex-end;
  margin-top: var(--space-3);
}

.email-action-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-3);
  flex-wrap: wrap;
}

:deep(.email-send-button) {
  flex: 0 0 auto;
  inline-size: fit-content;
  min-inline-size: 280px;
  block-size: 44px;
  padding-block: 0;
  overflow: hidden;
  align-self: center;
}

:deep(.email-send-button .p-button-label),
:deep(.email-send-button [data-pc-section='label']) {
  flex: 0 1 auto;
  white-space: nowrap;
}

.result-card {
  display: grid;
  gap: 8px;
}

.result-card p {
  margin: 0;
  color: var(--color-text-secondary);
}

.result-card.is-failed {
  background: rgba(55, 18, 28, 0.5);
  border-color: rgba(255, 107, 125, 0.2);
}

.email-hint {
  margin: 0;
  padding: 12px;
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.3);
  border: 1px solid rgba(129, 160, 207, 0.08);
  color: var(--color-text-secondary);
  font-size: 0.875rem;
  line-height: 1.5;
}

.email-hint code {
  color: var(--color-accent);
}

@media (max-width: 980px) {
  .admin-layout,
  .email-form-grid,
  .email-meta {
    grid-template-columns: 1fr;
  }
}
</style>
