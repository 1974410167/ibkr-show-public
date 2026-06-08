<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import Tag from 'primevue/tag'

import { fetchSystemStatus } from '@/api/adminSystem'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type { AdminSystemStatus, SystemComponentStatus, SystemComponentStatusLevel } from '@/types/adminSystem'

const router = useRouter()
const loading = ref(true)
const refreshing = ref(false)
const errorMessage = ref('')
const status = ref<AdminSystemStatus | null>(null)

function statusTagClass(level: SystemComponentStatusLevel): string {
  switch (level) {
    case 'ok':
      return 'p-tag--positive'
    case 'error':
      return 'p-tag--negative'
    default:
      return 'p-tag--warning'
  }
}

function statusLabel(level: SystemComponentStatusLevel): string {
  switch (level) {
    case 'ok':
      return '正常'
    case 'warning':
      return '警告'
    case 'error':
      return '异常'
    case 'disabled':
      return '已禁用'
    case 'unknown':
      return '未知'
    default:
      return level
  }
}

function overallTagClass(level: string): string {
  switch (level) {
    case 'ok':
      return 'p-tag--positive'
    case 'error':
      return 'p-tag--negative'
    default:
      return 'p-tag--warning'
  }
}

function overallLabel(level: string): string {
  switch (level) {
    case 'ok':
      return '系统正常'
    case 'warning':
      return '部分异常'
    case 'error':
      return '系统异常'
    default:
      return level
  }
}

function componentRoute(name: string): string | null {
  switch (name) {
    case 'ibkr':
      return '/admin/ibkr'
    case 'llm':
      return '/admin/llm'
    case 'email':
      return '/admin/email'
    case 'longbridge':
      return '/admin/longbridge-mcp'
    default:
      return null
  }
}

async function loadData(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    status.value = await fetchSystemStatus()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载系统状态失败'
  } finally {
    loading.value = false
  }
}

async function refresh(): Promise<void> {
  refreshing.value = true
  errorMessage.value = ''
  try {
    status.value = await fetchSystemStatus()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新系统状态失败'
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  void loadData()
})
</script>

<template>
  <section class="page-section admin-system-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header admin-system-page__header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-system-page__title">系统状态</h2>
            <p class="panel-subtitle">聚合各组件配置与连接状态，快速定位未配置项。</p>
          </div>
          <Tag
            v-if="status"
            :value="overallLabel(status.overall_status)"
            :class="overallTagClass(status.overall_status)"
          />
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="宏观数据源" icon="pi pi-calendar-clock" class="terminal-nav__button" @click="router.push('/admin/market-events')" />
          <Button label="系统状态" icon="pi pi-heart" class="terminal-nav__button is-active" />
          <Button label="Agent 监控" icon="pi pi-chart-line" class="terminal-nav__button" @click="router.push('/admin/agent-monitoring')" />
          <Button label="Prompt 管理" icon="pi pi-file-edit" class="terminal-nav__button" @click="router.push('/admin/prompts')" />
          <Button label="Harness 控制台" icon="pi pi-sitemap" class="terminal-nav__button" @click="router.push('/admin/harness')" />
        </nav>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage" :message="errorMessage" />

    <template v-else-if="status">
      <div class="admin-system-page__toolbar">
        <Button label="刷新" icon="pi pi-refresh" class="p-button p-button--ghost" :loading="refreshing" @click="refresh" />
        <span class="terminal-note">生成时间：{{ status.generated_at }}</span>
      </div>

      <div class="admin-system-page__grid">
        <section
          v-for="comp in status.components"
          :key="comp.name"
          class="surface-panel admin-system-page__card"
        >
          <div class="surface-panel__content">
            <div class="admin-system-page__card-header">
              <h3 class="panel-title admin-system-page__card-title">{{ comp.label }}</h3>
              <Tag :value="statusLabel(comp.status)" :class="statusTagClass(comp.status)" />
            </div>

            <p class="admin-system-page__message">{{ comp.message }}</p>

            <dl v-if="Object.keys(comp.details).length > 0" class="admin-system-page__details">
              <div v-for="(value, key) in comp.details" :key="key">
                <dt>{{ key }}</dt>
                <dd>{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd>
              </div>
            </dl>

            <div v-if="componentRoute(comp.name)" class="admin-system-page__card-action">
              <Button
                label="前往配置"
                icon="pi pi-arrow-right"
                class="p-button p-button--ghost p-button--sm"
                @click="router.push(componentRoute(comp.name) as string)"
              />
            </div>
          </div>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.admin-system-page__header {
  align-items: center;
}

.admin-system-page__title {
  font-size: 1.5rem;
}

.admin-tabs {
  display: flex;
  gap: 12px;
}

.admin-system-page__toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.admin-system-page__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--space-4);
}

.admin-system-page__card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.admin-system-page__card-title {
  font-size: 1.1rem;
  margin: 0;
}

.admin-system-page__message {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}

.admin-system-page__details {
  display: grid;
  gap: 6px;
  margin: 12px 0 0;
  padding: 12px;
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.52);
  border: 1px solid rgba(129, 160, 207, 0.12);
}

.admin-system-page__details dt {
  color: var(--color-text-secondary);
  font-size: 0.75rem;
  letter-spacing: 0.05em;
}

.admin-system-page__details dd {
  margin: 2px 0 0;
  font-size: 0.85rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.admin-system-page__card-action {
  margin-top: 12px;
}
</style>
