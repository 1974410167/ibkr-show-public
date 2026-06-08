<script setup lang="ts">
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import AgentMonitoringPanel from '@/components/admin/AgentMonitoringPanel.vue'

const router = useRouter()
</script>

<template>
  <section class="page-section admin-agent-monitoring-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title" style="font-size: 1.5rem">Agent 监控中心</h2>
            <p class="panel-subtitle">监控 Account Copilot 的 LLM 调用、IBKR 工具、Longbridge MCP 工具和运行失败情况。</p>
          </div>
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="宏观数据源" icon="pi pi-calendar-clock" class="terminal-nav__button" @click="router.push('/admin/market-events')" />
          <Button label="系统状态" icon="pi pi-heart" class="terminal-nav__button" @click="router.push('/admin/system')" />
          <Button label="Agent 监控" icon="pi pi-chart-line" class="terminal-nav__button is-active" />
          <Button label="Prompt 管理" icon="pi pi-file-edit" class="terminal-nav__button" @click="router.push('/admin/prompts')" />
          <Button label="Harness 控制台" icon="pi pi-sitemap" class="terminal-nav__button" @click="router.push('/admin/harness')" />
        </nav>
      </div>
    </section>

    <AgentMonitoringPanel />
  </section>
</template>

<style scoped>
.admin-agent-monitoring-page {
  display: grid;
  gap: var(--space-4);
}

.admin-tabs {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
