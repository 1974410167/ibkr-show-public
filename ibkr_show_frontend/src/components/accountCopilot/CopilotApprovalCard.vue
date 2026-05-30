<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
import Tag from 'primevue/tag'

import type { CopilotApproval, CopilotRun } from '@/types/accountCopilot'
import { approvalButtonState, isApprovalPending } from './approvalStatus'
import { sanitizeJsonValue } from '@/utils/sanitizeJson'

const props = defineProps<{
  run: CopilotRun
  approving?: boolean
}>()

const emit = defineEmits<{
  approve: [run: CopilotRun, approved: boolean]
}>()

const expanded = ref(false)

function shortHash(value?: string): string {
  return value ? value.slice(0, 8) : '--'
}

function sanitizeJson(value: unknown): string {
  return JSON.stringify(sanitizeJsonValue(value ?? {}), null, 2)
}

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    pending: '等待审批',
    awaiting_approval: '等待审批',
    approved: '已同意',
    executed: '已同意',
    rejected: '已拒绝',
    expired: '已过期',
    failed: '审批失败',
  }
  return status ? labels[status] || status : '等待审批'
}

function statusSeverity(status?: string): 'success' | 'info' | 'warn' | 'danger' | 'secondary' {
  if (status === 'approved' || status === 'executed') return 'success'
  if (status === 'rejected' || status === 'failed') return 'danger'
  if (status === 'expired') return 'secondary'
  return 'warn'
}

function formatLocalDateTime(value?: string): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const getPart = (type: string) => parts.find((part) => part.type === type)?.value || ''
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const zoneLabel = timeZone === 'Asia/Shanghai' ? '北京时间' : '本地时间'
  return `${getPart('year')}-${getPart('month')}-${getPart('day')} ${getPart('hour')}:${getPart('minute')}，${zoneLabel}`
}

function displaySkillName(approval: CopilotApproval): string {
  return approval.skill_display_name || approval.skill_arguments?.display_name || approval.skill_name || '需要确认的能力'
}

function displayActionName(approval: CopilotApproval): string {
  const actionName = approval.skill_arguments?.action_name || approval.skill_arguments?.tool_name || approval.skill_arguments?.action
  return String(actionName || approval.skill_name || '--')
}

function displayDataScope(scope: string): string {
  const labels: Record<string, string> = {
    account_overview: 'IBKR 账户概览',
    ibkr_account_overview: 'IBKR 账户概览',
    positions: 'IBKR 当前持仓',
    ibkr_positions: 'IBKR 当前持仓',
    current_positions: 'IBKR 当前持仓',
    trades: 'IBKR 交易记录',
    ibkr_trades: 'IBKR 交易记录',
    cash: 'IBKR 现金与购买力',
    ibkr_cash: 'IBKR 现金与购买力',
    longbridge_market_data: '长桥公开市场数据',
    market_data: '长桥公开市场数据',
    public_market_data: '长桥公开市场数据',
    longbridge_news: '长桥公开新闻',
  }
  return labels[scope] || scope
}

function dataScopes(approval: CopilotApproval): string[] {
  return (approval.data_access || []).map(displayDataScope)
}

function isPending(approval: CopilotApproval): boolean {
  return isApprovalPending(approval)
}

function buttonState(approval: CopilotApproval) {
  return approvalButtonState(approval, props.approving)
}
</script>

<template>
  <section v-if="props.run.pending_approval" class="approval-card">
    <div class="approval-card__summary">
      <span class="approval-card__skill-name">Skill: {{ displaySkillName(props.run.pending_approval) }}</span>
      <Tag
        :value="statusLabel(props.run.pending_approval.status)"
        :severity="statusSeverity(props.run.pending_approval.status)"
        class="approval-card__status-tag"
      />
      <span class="approval-card__hint">需要确认后继续调用</span>
      <template v-if="isPending(props.run.pending_approval)">
        <Button
          label="同意"
          icon="pi pi-check"
          size="small"
          :loading="approving && isPending(props.run.pending_approval)"
          :disabled="buttonState(props.run.pending_approval).approveDisabled"
          @click="emit('approve', props.run, true)"
        />
        <Button
          label="拒绝"
          icon="pi pi-times"
          size="small"
          severity="secondary"
          class="approval-card__reject-btn"
          :disabled="buttonState(props.run.pending_approval).rejectDisabled"
          @click="emit('approve', props.run, false)"
        />
      </template>
      <button class="approval-card__expand-toggle" @click="expanded = !expanded">
        {{ expanded ? '收起详情' : '展开详情' }}
      </button>
    </div>

    <div v-if="expanded" class="approval-card__details">
      <div class="approval-card__field">
        <span>说明</span>
        <p>{{ props.run.pending_approval.approval_message || '我需要先获得你的确认，才会访问账户相关数据并调用该能力。' }}</p>
      </div>
      <div class="approval-card__field">
        <span>会访问的数据</span>
        <ul class="approval-card__scopes">
          <li v-for="scope in dataScopes(props.run.pending_approval)" :key="scope">{{ scope }}</li>
          <li v-if="dataScopes(props.run.pending_approval).length === 0">本次 Skill 声明的数据范围</li>
        </ul>
      </div>
      <div class="approval-card__field approval-card__field--inline">
        <span>过期时间</span>
        <strong>{{ formatLocalDateTime(props.run.pending_approval.expires_at) }}</strong>
      </div>
      <div class="approval-card__debug-grid">
        <span>skill name</span>
        <strong>{{ props.run.pending_approval.skill_name || '--' }}</strong>
        <span>tool/action name</span>
        <strong>{{ displayActionName(props.run.pending_approval) }}</strong>
        <span>data scopes</span>
        <strong>{{ (props.run.pending_approval.data_access || []).join(' / ') || '--' }}</strong>
        <span>expire time</span>
        <strong>{{ formatLocalDateTime(props.run.pending_approval.expires_at) }}</strong>
        <span>plan hash</span>
        <strong>{{ shortHash(props.run.pending_approval.plan_hash) }}</strong>
        <span>request id</span>
        <strong>{{ props.run.pending_approval.approval_id || '--' }}</strong>
      </div>
      <details class="approval-card__json">
        <summary>Skill 参数 JSON</summary>
        <pre>{{ sanitizeJson(props.run.pending_approval.skill_arguments) }}</pre>
      </details>
    </div>
  </section>
</template>

<style scoped>
.approval-card {
  width: min(720px, 100%);
  max-width: 84%;
  margin: 14px 0;
  padding: 12px 14px;
  border: 1px solid rgba(34, 211, 238, 0.24);
  border-radius: 14px;
  background: rgba(8, 20, 36, 0.92);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
}

.approval-card__summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.approval-card__skill-name {
  color: #e0f2fe;
  font-size: 0.88rem;
  font-weight: 600;
}

.approval-card__status-tag {
  transform: scale(0.88);
}

.approval-card__hint {
  color: #7dd3fc;
  font-size: 0.78rem;
}

.approval-card__reject-btn {
  color: #fecaca;
  border-color: rgba(248, 113, 113, 0.22);
}

.approval-card__expand-toggle {
  margin-left: auto;
  padding: 0;
  color: #38bdf8;
  font-size: 0.76rem;
  background: transparent;
  border: none;
  cursor: pointer;
}

.approval-card__expand-toggle:hover {
  text-decoration: underline;
}

.approval-card__details {
  display: grid;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(125, 211, 252, 0.12);
}

.approval-card__field {
  display: grid;
  gap: 4px;
}

.approval-card__field--inline {
  grid-template-columns: 88px 1fr;
  align-items: center;
}

.approval-card__field span,
.approval-card__debug-grid span {
  color: #7dd3fc;
  font-size: 0.76rem;
}

.approval-card__field strong,
.approval-card__debug-grid strong {
  color: #f8fafc;
  word-break: break-word;
}

.approval-card__field p {
  margin: 0;
  color: #dbeafe;
  line-height: 1.6;
}

.approval-card__scopes {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 18px;
  color: #dbeafe;
}

.approval-card__json {
  color: #bae6fd;
  font-size: 0.82rem;
}

.approval-card__json pre {
  margin: 8px 0 0;
  padding: 10px;
  max-height: 180px;
  overflow: auto;
  color: #dbeafe;
  font-size: 0.76rem;
  border: 1px solid rgba(125, 211, 252, 0.12);
  border-radius: 10px;
  background: rgba(2, 8, 23, 0.62);
}

.approval-card__debug-grid {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 6px 10px;
  padding: 10px;
  border: 1px solid rgba(125, 211, 252, 0.12);
  border-radius: 10px;
  background: rgba(2, 8, 23, 0.42);
}

@media (max-width: 720px) {
  .approval-card {
    width: 100%;
  }

  .approval-card__field--inline,
  .approval-card__debug-grid {
    grid-template-columns: 1fr;
  }
}
</style>
