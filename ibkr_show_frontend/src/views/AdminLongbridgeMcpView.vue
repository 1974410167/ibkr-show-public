<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'

import {
  completeLongbridgeOpenApiOauth,
  disconnectLongbridgeOpenApiOauth,
  fetchLongbridgeOpenApiHealth,
  fetchLongbridgeOpenApiStatus,
  fetchLongbridgeUnifiedHealth,
  fetchLongbridgeUnifiedStatus,
  refreshLongbridgeUnifiedOauth,
  startLongbridgeOpenApiOauth,
  testLongbridgeMcp,
} from '@/api/adminLongbridgeMcp'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type {
  LongbridgeMcpTestResponse,
  LongbridgeOpenApiHealth,
  LongbridgeOpenApiOauthStartResponse,
  LongbridgeOpenApiStatus,
  LongbridgeUnifiedOAuthStatus,
} from '@/types/adminLongbridgeMcp'

const router = useRouter()
const loading = ref(true)
const starting = ref(false)
const completing = ref(false)
const refreshing = ref(false)
const disconnecting = ref(false)
const checking = ref(false)
const testing = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')
const unifiedStatus = ref<LongbridgeUnifiedOAuthStatus | null>(null)
const openApiStatus = ref<LongbridgeOpenApiStatus | null>(null)
const oauthStart = ref<LongbridgeOpenApiOauthStartResponse | null>(null)
const openApiHealth = ref<LongbridgeOpenApiHealth | null>(null)
const mcpTestResult = ref<LongbridgeMcpTestResponse | null>(null)

const form = reactive({
  scope: '',
  code: '',
  state: '',
})

const statusLabel = computed(() => {
  if (unifiedStatus.value?.openapi_connected && unifiedStatus.value?.mcp_effective_connected) return 'UNIFIED OAUTH CONNECTED'
  return 'AUTH REQUIRED'
})

const statusClass = computed(() => (unifiedStatus.value?.openapi_connected ? 'p-tag--positive' : 'p-tag--negative'))

function callbackUrl(): string {
  return `${window.location.origin}/api/admin/longbridge/openapi/oauth/callback`
}

async function loadData(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [unified, openapi] = await Promise.all([fetchLongbridgeUnifiedStatus(), fetchLongbridgeOpenApiStatus()])
    unifiedStatus.value = unified
    openApiStatus.value = openapi
    if (openapi.scope) form.scope = openapi.scope
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 LongBridge 状态失败'
  } finally {
    loading.value = false
  }
}

async function startOauth(): Promise<void> {
  starting.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  oauthStart.value = null
  try {
    oauthStart.value = await startLongbridgeOpenApiOauth({
      redirect_uri: callbackUrl(),
      scope: form.scope.trim() || undefined,
    })
    form.state = oauthStart.value.state
    window.open(oauthStart.value.authorization_url, '_blank', 'noopener,noreferrer')
    noticeMessage.value = '已打开 LongBridge 授权页。完成一次授权后，OpenAPI / SDK 和 MCP 都会复用该授权。'
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '启动 LongBridge OAuth 授权失败'
  } finally {
    starting.value = false
  }
}

async function completeOauth(): Promise<void> {
  completing.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await completeLongbridgeOpenApiOauth({
      code: form.code.trim(),
      state: form.state.trim(),
    })
    if (response.status) openApiStatus.value = response.status
    form.code = ''
    noticeMessage.value = response.message
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '完成 LongBridge OAuth 授权失败'
  } finally {
    completing.value = false
  }
}

async function refreshOauth(): Promise<void> {
  refreshing.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await refreshLongbridgeUnifiedOauth()
    unifiedStatus.value = response.status
    noticeMessage.value = response.message
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新 LongBridge OAuth token 失败'
  } finally {
    refreshing.value = false
  }
}

async function disconnectOauth(): Promise<void> {
  disconnecting.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  mcpTestResult.value = null
  openApiHealth.value = null
  try {
    const response = await disconnectLongbridgeOpenApiOauth()
    if (response.status) openApiStatus.value = response.status
    noticeMessage.value = response.message
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '断开 LongBridge OAuth 授权失败'
  } finally {
    disconnecting.value = false
  }
}

async function checkHealth(): Promise<void> {
  checking.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const [openapiHealth, unifiedHealth] = await Promise.all([fetchLongbridgeOpenApiHealth(), fetchLongbridgeUnifiedHealth()])
    openApiHealth.value = openapiHealth
    openApiStatus.value = openapiHealth.oauth_status
    unifiedStatus.value = unifiedHealth
    noticeMessage.value = unifiedHealth.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查 LongBridge 健康状态失败'
  } finally {
    checking.value = false
  }
}

async function runMcpTest(): Promise<void> {
  testing.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  mcpTestResult.value = null
  try {
    mcpTestResult.value = await testLongbridgeMcp()
    noticeMessage.value = mcpTestResult.value.message
    await loadData()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测试 LongBridge MCP 失败'
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <section class="page-section admin-longbridge-mcp-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title">LongBridge 统一授权</h2>
            <p class="panel-subtitle">OpenAPI OAuth 是唯一授权源；OpenAPI / SDK 和 hosted MCP 复用同一套 token。</p>
          </div>
          <Tag :value="statusLabel" :class="statusClass" />
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="LongBridge" icon="pi pi-link" class="terminal-nav__button is-active" />
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
                <h3 class="panel-title">统一授权状态</h3>
                <p class="panel-subtitle">MCP token 来源固定为 OpenAPI OAuth Store，不再读取旧的 MCP 独立授权文件。</p>
              </div>
            </div>

            <dl class="mcp-meta">
              <div>
                <dt>授权模式</dt>
                <dd>OpenAPI OAuth 单授权</dd>
              </div>
              <div>
                <dt>Token 来源</dt>
                <dd>{{ unifiedStatus?.token_source === 'openapi_oauth_store' ? 'OpenAPI OAuth Store' : '--' }}</dd>
              </div>
              <div>
                <dt>OpenAPI / SDK</dt>
                <dd>{{ unifiedStatus?.openapi_connected ? '已连接' : '未连接' }}</dd>
              </div>
              <div>
                <dt>MCP</dt>
                <dd>{{ unifiedStatus?.mcp_effective_connected ? '已连接' : '未连接' }}</dd>
              </div>
              <div>
                <dt>Client ID</dt>
                <dd>{{ unifiedStatus?.client_id_masked || '--' }}</dd>
              </div>
              <div>
                <dt>Refresh</dt>
                <dd>{{ unifiedStatus?.refresh_available ? '可用' : '不可用' }}</dd>
              </div>
              <div>
                <dt>过期倒计时</dt>
                <dd>{{ unifiedStatus?.expires_in_seconds ?? '--' }} 秒</dd>
              </div>
              <div>
                <dt>健康状态</dt>
                <dd>{{ unifiedStatus?.message || '--' }}</dd>
              </div>
            </dl>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">LongBridge OAuth 授权</h3>
                <p class="panel-subtitle">完成一次 LongBridge OAuth 授权后，OpenAPI / SDK 和 MCP 都会复用该授权。</p>
              </div>
            </div>

            <dl class="mcp-meta">
              <div>
                <dt>Client ID</dt>
                <dd>{{ openApiStatus?.client_id_configured ? openApiStatus.client_id : '未初始化（点击开始授权将自动注册）' }}</dd>
              </div>
              <div v-if="openApiStatus?.auto_registered">
                <dt>注册方式</dt>
                <dd>自动注册</dd>
              </div>
              <div>
                <dt>Access Token</dt>
                <dd>{{ openApiStatus?.access_token_masked || '--' }}</dd>
              </div>
              <div>
                <dt>Refresh Token</dt>
                <dd>{{ openApiStatus?.has_refresh_token ? '存在' : '不存在' }} <span v-if="openApiStatus?.refresh_token_masked">({{ openApiStatus.refresh_token_masked }})</span></dd>
              </div>
              <div>
                <dt>配置文件</dt>
                <dd>{{ openApiStatus?.config_file || '--' }}</dd>
              </div>
            </dl>

            <p v-if="!openApiStatus?.client_id_configured" class="admin-notice">首次授权时会自动向 LongBridge 注册 OAuth Client，无需手动配置 Client ID。</p>
            <p v-if="openApiStatus?.last_error" class="admin-warning">最近错误：{{ openApiStatus.last_error }}</p>

            <div class="openapi-oauth-grid">
              <label class="field-stack">
                <span class="field-stack__label">Scope</span>
                <InputText v-model="form.scope" placeholder="留空使用默认 LongBridge OAuth scope" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">授权 Code</span>
                <InputText v-model="form.code" placeholder="如使用手动回填，在这里粘贴 code" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">State</span>
                <InputText v-model="form.state" placeholder="开始授权后自动填入" />
              </label>
            </div>

            <div class="admin-form-actions">
              <Button label="开始授权" icon="pi pi-external-link" class="p-button p-button--accent" :loading="starting" @click="startOauth" />
              <Button label="完成授权" icon="pi pi-check" class="p-button p-button--ghost" :loading="completing" :disabled="!form.code.trim() || !form.state.trim()" @click="completeOauth" />
              <Button label="刷新 Token" icon="pi pi-sync" class="p-button p-button--ghost" :loading="refreshing" :disabled="!openApiStatus?.refresh_available" @click="refreshOauth" />
              <Button label="断开授权" icon="pi pi-times" class="p-button p-button--ghost" :loading="disconnecting" :disabled="!openApiStatus?.has_access_token" @click="disconnectOauth" />
              <Button label="健康检查" icon="pi pi-heart" class="p-button p-button--ghost" :loading="checking" @click="checkHealth" />
            </div>

            <div v-if="oauthStart" class="mcp-oauth-box">
              <p>授权链接已生成，若浏览器没有自动打开，可以手动打开下面的链接。</p>
              <a :href="oauthStart.authorization_url" target="_blank" rel="noreferrer">{{ oauthStart.authorization_url }}</a>
            </div>

            <dl v-if="openApiHealth" class="mcp-meta openapi-health">
              <div>
                <dt>SDK 已安装</dt>
                <dd>{{ openApiHealth.sdk_loaded ? '是' : '否' }}</dd>
              </div>
              <div>
                <dt>SDK OAuth 支持</dt>
                <dd>{{ openApiHealth.sdk_oauth_supported ? '是' : '否' }}</dd>
              </div>
              <div>
                <dt>可初始化 Config</dt>
                <dd>{{ openApiHealth.can_initialize_config ? '是' : '否' }}</dd>
              </div>
              <div>
                <dt>消息</dt>
                <dd>{{ openApiHealth.message }}</dd>
              </div>
            </dl>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">MCP 工具健康状态</h3>
                <p class="panel-subtitle">MCP 只允许公开市场只读工具，授权来自 OpenAPI OAuth Store。</p>
              </div>
            </div>

            <dl class="mcp-meta">
              <div>
                <dt>MCP Endpoint</dt>
                <dd>{{ unifiedStatus?.mcp_endpoint || '--' }}</dd>
              </div>
              <div>
                <dt>MCP Enabled</dt>
                <dd>{{ unifiedStatus?.mcp_endpoint ? '已配置' : '未配置' }}</dd>
              </div>
              <div>
                <dt>Auth Mode</dt>
                <dd>{{ unifiedStatus?.auth_mode || '--' }}</dd>
              </div>
              <div>
                <dt>Token Source</dt>
                <dd>{{ unifiedStatus?.token_source || '--' }}</dd>
              </div>
            </dl>

            <div class="admin-form-actions">
              <Button label="测试 MCP" icon="pi pi-bolt" class="p-button p-button--accent" :loading="testing" @click="runMcpTest" />
            </div>

            <dl v-if="mcpTestResult" class="mcp-meta openapi-health">
              <div>
                <dt>tools/list</dt>
                <dd>{{ mcpTestResult.success ? '可用' : '不可用' }}</dd>
              </div>
              <div>
                <dt>工具数量</dt>
                <dd>{{ mcpTestResult.tool_count ?? '--' }}</dd>
              </div>
              <div>
                <dt>错误码</dt>
                <dd>{{ mcpTestResult.error_code || '--' }}</dd>
              </div>
              <div>
                <dt>消息</dt>
                <dd>{{ mcpTestResult.message }}</dd>
              </div>
            </dl>

            <pre v-if="mcpTestResult?.quote_sample" class="mcp-json">{{ JSON.stringify(mcpTestResult.quote_sample, null, 2) }}</pre>
            <ul v-if="mcpTestResult?.data_limitations?.length" class="mcp-limitations">
              <li v-for="item in mcpTestResult.data_limitations" :key="item">{{ item }}</li>
            </ul>
          </div>
        </section>
      </section>
    </template>
  </section>
</template>

<style scoped>
.admin-longbridge-mcp-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.admin-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.admin-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
}

.mcp-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 0;
}

.mcp-meta div {
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.42);
}

.mcp-meta dt {
  margin-bottom: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.mcp-meta dd {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--text-primary);
}

.mcp-oauth-box,
.admin-warning {
  margin-top: 16px;
  padding: 12px;
  border-radius: 8px;
  background: rgba(14, 165, 233, 0.1);
  color: var(--text-primary);
  overflow-wrap: anywhere;
}

.admin-warning {
  background: rgba(248, 113, 113, 0.12);
}

.openapi-oauth-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.openapi-health {
  margin-top: 16px;
}

.mcp-json {
  margin: 16px 0 0;
  padding: 12px;
  max-height: 280px;
  overflow: auto;
  border-radius: 8px;
  background: rgba(2, 6, 23, 0.5);
  color: var(--text-primary);
}

.mcp-limitations {
  margin: 12px 0 0;
  color: var(--text-muted);
}
</style>
