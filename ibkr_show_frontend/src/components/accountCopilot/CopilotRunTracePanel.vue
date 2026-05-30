<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Tag from 'primevue/tag'
import { getRunTrace } from '@/api/accountCopilot'
import type { CopilotEvent, CopilotRun, CopilotRunTraceResponse, CopilotTraceTimelineNode } from '@/types/accountCopilot'
import CopilotObservationList from './CopilotObservationList.vue'
import CopilotToolCallList from './CopilotToolCallList.vue'
import { sanitizeJsonValue } from '@/utils/sanitizeJson'

const props = defineProps<{
  run: CopilotRun | null
}>()

const trace = ref<CopilotRunTraceResponse | null>(null)
const traceLoading = ref(false)
const traceError = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const POLLABLE_STATUSES = new Set(['queued', 'running', 'awaiting_approval'])

const executionSummary = computed(() => {
  const run = props.run
  const toolCalls = run?.tool_calls || []
  const actions = run?.actions || []
  const approval = run?.pending_approval || null
  const usedTools = Array.from(new Set(toolCalls.map((call) => String(call.tool_name || '')).filter(Boolean)))
  const subagentObservations = (run?.observations || []).filter((obs) => obs.observation_type === 'subagent_result')
  return {
    round_count: Math.max(0, ...actions.map((action) => Number(action.round || 0))),
    tool_call_count: toolCalls.length,
    success_tool_count: toolCalls.filter((call) => call.ok).length,
    failed_tool_count: toolCalls.filter((call) => call.ok === false).length,
    used_ibkr_tools: usedTools.filter((name) => name.startsWith('ibkr_')),
    used_longbridge_tools: usedTools.filter((name) => name.startsWith('longbridge_')),
    subagent_count: subagentObservations.length,
    subagent_ok: subagentObservations.filter((obs) => obs.ok).length,
    skill_requested: Boolean(approval || run?.skill_requests?.length),
    approval_status: approval?.status || run?.skill_requests?.[0]?.status || '--',
    fallback_used: Boolean(run?.metadata?.fallback_used),
    cancelled: run?.status === 'cancelled' || Boolean(run?.metadata?.cancelled),
    timeout: Boolean(run?.metadata?.timeout),
  }
})

const hasTraceData = computed(() => (trace.value?.timeline?.length || 0) > 0)

async function fetchTrace() {
  if (!props.run || traceLoading.value) return
  traceLoading.value = true
  traceError.value = ''
  try {
    trace.value = await getRunTrace(props.run.id)
  } catch (e: any) {
    traceError.value = e?.message || 'Failed to load trace'
  } finally {
    traceLoading.value = false
  }
}

function startPolling() {
  stopPolling()
  if (props.run && POLLABLE_STATUSES.has(props.run.status)) {
    pollTimer = setInterval(() => {
      if (!traceLoading.value) {
        void fetchTrace()
      }
    }, 1000)
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(() => props.run?.id, () => {
  trace.value = null
  stopPolling()
  if (props.run?.id) {
    void fetchTrace()
    startPolling()
  }
}, { immediate: true })

watch(() => props.run?.status, (status) => {
  if (status && POLLABLE_STATUSES.has(status)) {
    startPolling()
  } else {
    stopPolling()
  }
})

onBeforeUnmount(() => {
  stopPolling()
})

function sanitizeJson(value: unknown): string {
  return JSON.stringify(sanitizeJsonValue(value ?? {}), null, 2)
}

function statusSeverity(status?: string): 'success' | 'info' | 'warn' | 'danger' | 'secondary' {
  if (status === 'completed' || status === 'ok') return 'success'
  if (status === 'awaiting_approval' || status === 'started') return 'warn'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'secondary'
  if (status === 'running') return 'info'
  return 'secondary'
}

function nodeTypeIcon(nodeType: string): string {
  const icons: Record<string, string> = {
    planner: '\u{1F9E0}',
    action: '\u{26A1}',
    tool: '\u{1F527}',
    subagent: '\u{1F916}',
    observation: '\u{1F441}',
    final_answer: '\u{2705}',
    error: '\u{274C}',
  }
  return icons[nodeType] || '\u{25CF}'
}

function eventLabel(event: CopilotEvent): string {
  const payload = event.payload || {}
  const labels: Record<string, string> = {
    run_started: '分析已开始',
    planner_started: `正在规划第 ${payload.round ?? '--'} 轮`,
    planner_finished: `已选择动作：${payload.action_type || payload.tool_name || payload.skill_name || 'final_answer'}`,
    planner_repair_started: '正在修复规划器输出',
    planner_repair_finished: '规划器输出已修复',
    action_selected: `动作已确认：${payload.action?.action_type || '--'}`,
    tool_started: `正在调用工具 ${payload.tool_name || '--'}`,
    tool_finished: `工具 ${payload.tool_name || '--'} 已完成`,
    tool_failed: `工具 ${payload.tool_name || '--'} 失败`,
    observation_created: '已生成观察结果',
    skill_approval_requested: '需要用户确认 Skill',
    skill_approval_approved: 'Skill 审批已同意',
    skill_approval_rejected: 'Skill 审批已拒绝或过期',
    skill_started: `正在执行 Skill ${payload.skill_name || '--'}`,
    skill_finished: `Skill ${payload.skill_name || '--'} 已完成`,
    skill_failed: `Skill ${payload.skill_name || '--'} 失败`,
    subagent_started: `子代理 ${payload.subagent_name || '--'} 开始执行`,
    subagent_finished: `子代理 ${payload.subagent_name || '--'} 完成`,
    subagent_failed: `子代理 ${payload.subagent_name || '--'} 失败`,
    final_answer: '已生成最终回答',
    memory_update_started: '正在更新会话记忆',
    memory_update_finished: '记忆更新完成',
    memory_update_failed: '记忆更新失败',
    run_completed: '分析完成',
    run_failed: '分析失败',
    run_cancelled: '用户已取消',
  }
  return labels[event.event_type] || event.event_type
}
</script>

<template>
  <section class="trace-panel">
    <div class="trace-panel__header">
      <div>
        <p class="trace-panel__eyebrow">Run Trace</p>
        <h3>{{ run ? run.id.slice(0, 8) : '未选择' }}</h3>
      </div>
      <Tag v-if="run" :value="run.status" :severity="statusSeverity(run.status)" />
    </div>

    <div v-if="!run" class="trace-panel__empty">点击一条 assistant 消息查看执行轨迹。</div>
    <template v-else>
      <section class="trace-section">
        <h4>执行摘要</h4>
        <div class="summary-grid">
          <span>rounds</span><strong>{{ executionSummary.round_count }}</strong>
          <span>tools</span><strong>{{ executionSummary.success_tool_count }}/{{ executionSummary.tool_call_count }} ok</strong>
          <span>failed</span><strong>{{ executionSummary.failed_tool_count }}</strong>
          <span>subagents</span><strong>{{ executionSummary.subagent_ok }}/{{ executionSummary.subagent_count }} ok</strong>
          <span>approval</span><strong>{{ executionSummary.approval_status }}</strong>
          <span>fallback</span><strong>{{ executionSummary.fallback_used }}</strong>
          <span>cancelled</span><strong>{{ executionSummary.cancelled }}</strong>
          <span>timeout</span><strong>{{ executionSummary.timeout }}</strong>
        </div>
        <div class="summary-tools">
          <small>IBKR</small>
          <code>{{ executionSummary.used_ibkr_tools.join(', ') || '--' }}</code>
          <small>Longbridge</small>
          <code>{{ executionSummary.used_longbridge_tools.join(', ') || '--' }}</code>
        </div>
      </section>

      <section class="trace-section">
        <h4>运行轨迹 Timeline</h4>
        <div v-if="traceLoading && !trace" class="trace-panel__empty">加载中...</div>
        <div v-else-if="traceError" class="trace-panel__empty trace-panel__error">{{ traceError }}</div>
        <div v-else-if="!hasTraceData" class="trace-panel__empty">无轨迹数据。</div>
        <div v-else class="timeline">
          <div
            v-for="(node, idx) in trace!.timeline"
            :key="`node-${idx}`"
            class="timeline__node"
            :class="`timeline__node--${node.node_type}`"
          >
            <div class="timeline__marker">
              <span class="timeline__icon">{{ nodeTypeIcon(node.node_type) }}</span>
              <span v-if="idx < (trace!.timeline.length - 1)" class="timeline__line" />
            </div>
            <div class="timeline__content">
              <div class="timeline__head">
                <strong>{{ node.label }}</strong>
                <Tag
                  :value="node.status"
                  :severity="statusSeverity(node.status)"
                  class="timeline__tag"
                />
              </div>
              <div class="timeline__meta">
                <span v-if="node.round != null">round {{ node.round }}</span>
                <span v-if="node.created_at">{{ node.created_at }}</span>
              </div>
              <details v-if="Object.keys(node.payload || {}).length > 0" class="timeline__details">
                <summary>详情</summary>
                <pre>{{ sanitizeJson(node.payload) }}</pre>
              </details>
            </div>
          </div>
        </div>
      </section>

      <section v-if="run._live_events?.length" class="trace-section">
        <h4>实时进度</h4>
        <article v-for="event in run._live_events" :key="`${event.seq}-${event.event_type}`" class="trace-mini-card">
          <strong>#{{ event.seq }} {{ eventLabel(event) }}</strong>
          <em>{{ event.event_type }}</em>
          <span>{{ event.created_at || 'streaming' }}</span>
          <details>
            <summary>payload</summary>
            <pre>{{ sanitizeJson(event.payload) }}</pre>
          </details>
        </article>
      </section>

      <section class="trace-section">
        <h4>Planner</h4>
        <div class="trace-kv">
          <span>repaired</span><strong>{{ run.planner_output?.repaired ?? '--' }}</strong>
          <span>latency</span><strong>{{ run.planner_output?.latency_ms ?? '--' }}ms</strong>
          <span>fallback</span><strong>{{ run.metadata?.fallback_used ?? false }}</strong>
        </div>
        <details>
          <summary>raw_action</summary>
          <pre>{{ sanitizeJson(run.planner_output?.raw_action || run.planner_output) }}</pre>
        </details>
      </section>

      <section class="trace-section">
        <h4>Actions</h4>
        <article v-for="action in run.actions" :key="action.id || `${action.round}-${action.action_type}`" class="trace-mini-card">
          <strong>{{ action.action_type }}</strong>
          <span>{{ action.tool_name || action.skill_name || action.subagent_name || 'final_answer' }}</span>
          <p>{{ action.thought_summary }}</p>
          <details>
            <summary>evidence_sufficiency</summary>
            <pre>{{ sanitizeJson(action.evidence_sufficiency) }}</pre>
          </details>
        </article>
      </section>

      <section class="trace-section">
        <h4>Tool Calls</h4>
        <CopilotToolCallList :tool-calls="run.tool_calls" />
      </section>

      <section class="trace-section">
        <h4>Observations</h4>
        <CopilotObservationList :observations="run.observations" />
      </section>

      <section class="trace-section">
        <h4>Approval</h4>
        <details open>
          <summary>pending_approval / skill_requests</summary>
          <pre>{{ sanitizeJson({ pending_approval: run.pending_approval, skill_requests: run.skill_requests }) }}</pre>
        </details>
      </section>

      <section class="trace-section">
        <h4>Memory</h4>
        <div class="trace-kv">
          <span>retrieved</span><strong>{{ run.memory_snapshot?.retrieved_memory_count ?? 0 }}</strong>
          <span>constraints</span><strong>{{ run.memory_snapshot?.non_compressible_constraint_count ?? 0 }}</strong>
          <span>compressed until</span><strong>{{ run.memory_snapshot?.compressed_until_message_id ?? '--' }}</strong>
        </div>
        <details>
          <summary>memory_snapshot</summary>
          <pre>{{ sanitizeJson(run.memory_snapshot) }}</pre>
        </details>
      </section>
    </template>
  </section>
</template>

<style scoped>
.trace-panel {
  display: grid;
  gap: 14px;
}

.trace-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.trace-panel__header h3 {
  margin: 0;
}

.trace-panel__eyebrow {
  margin: 0 0 4px;
  color: #22d3ee;
  font-size: 0.72rem;
  text-transform: uppercase;
}

.trace-panel__empty,
.trace-section {
  padding: 12px;
  border: 1px solid rgba(125, 211, 252, 0.14);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.58);
}

.trace-panel__error {
  color: #fca5a5;
}

.trace-section h4 {
  margin: 0 0 10px;
  color: #dff7ff;
}

.trace-kv {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px;
  color: #94a3b8;
  font-size: 0.78rem;
}

.trace-kv strong {
  color: #e2e8f0;
  word-break: break-word;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  color: #94a3b8;
  font-size: 0.78rem;
}

.summary-grid strong {
  color: #e2e8f0;
}

.summary-tools {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.summary-tools small {
  color: #38bdf8;
}

.summary-tools code {
  color: #bae6fd;
  white-space: pre-wrap;
  word-break: break-word;
}

.trace-mini-card {
  margin-bottom: 8px;
  padding: 10px;
  border-radius: 12px;
  background: rgba(2, 8, 23, 0.42);
}

.trace-mini-card span,
.trace-mini-card em,
.trace-mini-card p,
summary {
  color: #94a3b8;
  font-size: 0.78rem;
}

.trace-mini-card em {
  display: block;
  margin-top: 2px;
  font-style: normal;
  color: #38bdf8;
}

pre {
  max-height: 220px;
  overflow: auto;
  color: #bae6fd;
  font-size: 0.72rem;
}

/* Timeline styles */
.timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.timeline__node {
  display: flex;
  gap: 10px;
}

.timeline__marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 28px;
}

.timeline__icon {
  font-size: 1rem;
  line-height: 1;
  z-index: 1;
}

.timeline__line {
  flex: 1;
  width: 2px;
  background: rgba(125, 211, 252, 0.2);
  min-height: 16px;
}

.timeline__content {
  flex: 1;
  min-width: 0;
  padding: 4px 0 14px;
}

.timeline__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.timeline__head strong {
  color: #e2e8f0;
  font-size: 0.82rem;
}

.timeline__tag {
  font-size: 0.65rem;
}

.timeline__meta {
  display: flex;
  gap: 12px;
  margin-top: 2px;
  color: #64748b;
  font-size: 0.7rem;
}

.timeline__details {
  margin-top: 6px;
}

.timeline__details summary {
  cursor: pointer;
  color: #38bdf8;
  font-size: 0.72rem;
}

.timeline__details pre {
  margin-top: 4px;
  padding: 8px;
  border-radius: 8px;
  background: rgba(2, 8, 23, 0.5);
}

.timeline__node--error .timeline__head strong {
  color: #fca5a5;
}

.timeline__node--final_answer .timeline__head strong {
  color: #86efac;
}
</style>
