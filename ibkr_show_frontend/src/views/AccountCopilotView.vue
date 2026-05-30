<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Tag from 'primevue/tag'

import {
  approveRun,
  cancelRun,
  createSession,
  getCopilotHealth,
  getRun,
  getSession,
  listRunEvents,
  listMessages,
  listSessionMemories,
  listSessions,
  rebuildSessionMemories,
  seedDemoSession,
  sendMessage,
  sendMessageStream,
  updateSession,
} from '@/api/accountCopilot'
import CopilotInputBox from '@/components/accountCopilot/CopilotInputBox.vue'
import CopilotMemoryPanel from '@/components/accountCopilot/CopilotMemoryPanel.vue'
import CopilotMessageList from '@/components/accountCopilot/CopilotMessageList.vue'
import CopilotRunTracePanel from '@/components/accountCopilot/CopilotRunTracePanel.vue'
import CopilotSessionSidebar from '@/components/accountCopilot/CopilotSessionSidebar.vue'
import { useCopilotRunStream } from '@/composables/useCopilotRunStream'
import type { CopilotHealthResponse, CopilotMemory, CopilotMessage, CopilotRun, CopilotSession } from '@/types/accountCopilot'

const sessions = ref<CopilotSession[]>([])
const activeSession = ref<CopilotSession | null>(null)
const messages = ref<CopilotMessage[]>([])
const runsById = ref<Record<string, CopilotRun>>({})
const selectedRun = ref<CopilotRun | null>(null)
const memories = ref<CopilotMemory[]>([])
const inputText = ref('')
const renameTitle = ref('')
const memoryType = ref('all')
const loadingSessions = ref(false)
const loadingMessages = ref(false)
const sending = ref(false)
const approving = ref(false)
const memoryLoading = ref(false)
const memoryRebuilding = ref(false)
const demoSeeding = ref(false)
const errorMessage = ref('')
const health = ref<CopilotHealthResponse | null>(null)
const healthOpen = ref(false)
const stream = useCopilotRunStream()
const pageRef = ref<HTMLElement | null>(null)
const messagesViewport = ref<HTMLElement | null>(null)
const shouldStickToBottom = ref(true)

const welcomeQuestionGroups = [
  {
    title: '账户事实',
    questions: ['我现在账户风险高不高？', '我最近亏损主要来自哪些股票？', '当前现金比例是否合理？'],
  },
  {
    title: '交易复盘',
    questions: ['我在 AMD 上的历史交易表现怎么样？', '我是不是经常卖飞？'],
  },
  {
    title: '市场公开信息',
    questions: ['AMD 最近为什么涨跌？', '小米最近有什么公开新闻？'],
  },
  {
    title: 'Skill 场景',
    questions: ['MU 现在适合建仓吗？', 'AMD 要不要继续持有？'],
  },
]

const hasMessages = computed(() => messages.value.length > 0)
const activeOpenRun = computed(() =>
  Object.values(runsById.value).find(
    (run) =>
      run.session_id === activeSession.value?.id &&
      (run._streaming || ['queued', 'running', 'awaiting_approval'].includes(run.status)),
  ) || null,
)
const activeStreamingRun = computed(() =>
  Object.values(runsById.value).find(
    (run) => run.session_id === activeSession.value?.id && (run._streaming || run.status === 'running'),
  ) || null,
)
const streamReconnecting = computed(() => stream.reconnecting.value)
const reconnectAttempts = computed(() => stream.reconnectAttempts.value)
const healthSeverity = computed(() => (health.value?.ok ? 'success' : 'warn'))
const healthLabel = computed(() => (health.value?.ok ? 'Copilot healthy' : 'Copilot degraded'))
const demoMode = computed(() => Boolean(health.value?.settings?.demo_mode))

async function loadHealth(): Promise<void> {
  try {
    health.value = await getCopilotHealth()
  } catch {
    health.value = {
      ok: false,
      checks: { api: { ok: false, message: 'health check failed' } },
      settings: { max_react_rounds: 0, run_timeout_seconds: 0, max_event_payload_chars: 0, demo_mode: false },
    }
  }
}

async function loadSessions(): Promise<void> {
  loadingSessions.value = true
  try {
    sessions.value = await listSessions(100)
    if (!activeSession.value && sessions.value.length > 0) {
      await selectSession(sessions.value[0].id)
    }
  } catch (error) {
    setError(error)
  } finally {
    loadingSessions.value = false
  }
}

async function createNewSession(): Promise<void> {
  try {
    const session = await createSession({ title: 'Account Copilot' })
    sessions.value = [session, ...sessions.value]
    await selectSession(session.id)
  } catch (error) {
    setError(error)
  }
}

async function loadDemoSession(): Promise<void> {
  demoSeeding.value = true
  errorMessage.value = ''
  try {
    const demo = await seedDemoSession()
    const runMap = Object.fromEntries(demo.runs.map((run) => [run.id, run]))
    sessions.value = [demo.session, ...sessions.value.filter((session) => session.id !== demo.session.id)]
    activeSession.value = demo.session
    renameTitle.value = demo.session.title
    messages.value = demo.messages
    runsById.value = runMap
    memories.value = demo.memories
    selectedRun.value = demo.runs[demo.runs.length - 1] || null
    if (selectedRun.value) {
      await restoreRunEvents(selectedRun.value)
    }
  } catch (error) {
    setError(error)
  } finally {
    demoSeeding.value = false
  }
}

async function selectSession(sessionId: string): Promise<void> {
  errorMessage.value = ''
  loadingMessages.value = true
  try {
    activeSession.value = await getSession(sessionId)
    renameTitle.value = activeSession.value.title
    messages.value = await listMessages(sessionId, 200)
    runsById.value = {}
    selectedRun.value = null
    await Promise.all([
      loadRunsForMessages(messages.value),
      loadMemories(sessionId),
    ])
  } catch (error) {
    setError(error)
  } finally {
    loadingMessages.value = false
  }
}

async function loadRunsForMessages(items: CopilotMessage[]): Promise<void> {
  const runIds = Array.from(new Set(items.map((message) => message.run_id).filter(Boolean))) as string[]
  await Promise.all(runIds.map((runId) => loadRun(runId)))
  const lastRunId = [...runIds].reverse().find((runId) => runsById.value[runId])
  selectedRun.value = lastRunId ? runsById.value[lastRunId] : null
  if (selectedRun.value) {
    await restoreRunEvents(selectedRun.value)
  }
}

async function loadRun(runId: string): Promise<CopilotRun | null> {
  try {
    const run = await getRun(runId)
    runsById.value = { ...runsById.value, [run.id]: run }
    if (selectedRun.value?.id === run.id) {
      selectedRun.value = run
    }
    return run
  } catch {
    return null
  }
}

async function selectRun(runId: string): Promise<void> {
  selectedRun.value = runsById.value[runId] || null
  if (!selectedRun.value) {
    selectedRun.value = await loadRun(runId)
  }
  if (selectedRun.value) {
    await restoreRunEvents(selectedRun.value)
  }
}

async function sendCurrentMessage(): Promise<void> {
  const content = inputText.value.trim()
  if (!content || sending.value) return
  if (activeOpenRun.value) {
    errorMessage.value = '当前会话已有分析在运行，请等待完成、审批或停止分析。'
    return
  }
  sending.value = true
  errorMessage.value = ''
  try {
    let session = activeSession.value
    if (!session) {
      session = await createSession({ title: content.slice(0, 24) })
      activeSession.value = session
      sessions.value = [session, ...sessions.value]
      renameTitle.value = session.title
    }
    try {
      const response = await sendMessageStream(session.id, content)
      const liveRun = { ...response.run, _streaming: true, _live_events: [] }
      const liveAssistant: CopilotMessage = {
        id: `live_${response.run.id}`,
        session_id: session.id,
        role: 'assistant',
        content: '正在分析...',
        created_at: new Date().toISOString(),
        run_id: response.run.id,
        metadata: { live: true },
      }
      messages.value = [...messages.value, response.user_message, liveAssistant]
      runsById.value = { ...runsById.value, [response.run.id]: liveRun }
      selectedRun.value = liveRun
      inputText.value = ''
      stream.connect(response.run.id, 0, { autoReconnect: true })
      await loadSessions()
    } catch {
      const response = await sendMessage(session.id, content)
      messages.value = [...messages.value, response.user_message, response.assistant_message]
      runsById.value = { ...runsById.value, [response.run.id]: response.run }
      selectedRun.value = response.run
      inputText.value = ''
      await Promise.all([loadSessions(), loadMemories(session.id)])
    }
  } catch (error) {
    setError(error)
  } finally {
    sending.value = false
  }
}

function applyLiveEvent(event: (typeof stream.events.value)[number]): void {
  const run = runsById.value[event.run_id]
  if (!run) return
  const liveEvents = [...(run._live_events || []), event]
  const nextRun: CopilotRun = { ...run, _live_events: liveEvents, _streaming: true }
  if (event.event_type === 'action_selected' && event.payload?.action) {
    nextRun.actions = [...(nextRun.actions || []), event.payload.action]
  }
  if ((event.event_type === 'tool_finished' || event.event_type === 'tool_failed') && event.payload) {
    nextRun.tool_calls = [
      ...(nextRun.tool_calls || []),
      {
        id: `live_tool_${event.seq}`,
        round: event.payload.round,
        tool_name: event.payload.tool_name,
        ok: event.payload.ok,
        latency_ms: event.payload.latency_ms,
        arguments: {},
      },
    ]
  }
  if (event.event_type === 'observation_created' && event.payload?.observation) {
    nextRun.observations = [...(nextRun.observations || []), event.payload.observation]
  }
  if (event.event_type === 'skill_approval_requested' && event.payload?.pending_approval) {
    nextRun.pending_approval = event.payload.pending_approval
    nextRun.status = 'awaiting_approval'
  }
  if (event.event_type === 'final_answer') {
    nextRun._live_final_answer = String(event.payload?.content || '')
    messages.value = messages.value.map((message) =>
      message.id === `live_${event.run_id}` ? { ...message, content: nextRun._live_final_answer || '正在整理最终回答...' } : message,
    )
  }
  if (event.event_type === 'run_failed') {
    nextRun.status = 'failed'
    nextRun._streaming = false
  }
  if (event.event_type === 'run_cancelled') {
    nextRun.status = 'cancelled'
    nextRun._streaming = false
  }
  runsById.value = { ...runsById.value, [event.run_id]: nextRun }
  if (selectedRun.value?.id === event.run_id) {
    selectedRun.value = nextRun
  }
  if ((event.event_type === 'run_completed' || event.event_type === 'run_cancelled') && activeSession.value) {
    void refreshAfterStream(event.run_id, activeSession.value.id)
  }
}

async function refreshAfterStream(runId: string, sessionId: string): Promise<void> {
  const run = await loadRun(runId)
  if (run) {
    runsById.value = { ...runsById.value, [run.id]: { ...run, _streaming: false, _live_events: runsById.value[run.id]?._live_events || [] } }
    selectedRun.value = runsById.value[run.id]
  }
  messages.value = await listMessages(sessionId, 200)
  await Promise.all([loadSessions(), loadMemories(sessionId)])
}

async function restoreRunEvents(run: CopilotRun): Promise<void> {
  try {
    const events = await listRunEvents(run.id, { limit: 500 })
    const lastSeq = events.reduce((max, event) => Math.max(max, Number(event.seq || 0)), 0)
    const nextRun: CopilotRun = {
      ...run,
      _live_events: events,
      _streaming: run.status === 'running',
    }
    runsById.value = { ...runsById.value, [run.id]: nextRun }
    if (selectedRun.value?.id === run.id) {
      selectedRun.value = nextRun
    }
    if (run.status === 'running') {
      stream.connect(run.id, lastSeq, { autoReconnect: true })
    }
  } catch {
    // Trace recovery is best-effort; persisted run details remain the source of truth.
  }
}

async function cancelSelectedRun(): Promise<void> {
  const run = selectedRun.value
  if (!run || !['queued', 'running', 'awaiting_approval'].includes(run.status)) return
  errorMessage.value = ''
  try {
    const cancelled = await cancelRun(run.id, 'User cancelled from Account Copilot UI')
    stream.disconnect()
    const nextRun: CopilotRun = {
      ...cancelled,
      _live_events: run._live_events || [],
      _streaming: false,
    }
    runsById.value = { ...runsById.value, [nextRun.id]: nextRun }
    selectedRun.value = nextRun
    if (activeSession.value) {
      messages.value = await listMessages(activeSession.value.id, 200)
      await loadSessions()
    }
  } catch (error) {
    setError(error)
  }
}

async function approveSkill(run: CopilotRun, approved: boolean): Promise<void> {
  const approval = run.pending_approval
  if (!approval || approving.value) return
  approving.value = true
  errorMessage.value = ''
  try {
    const response = await approveRun(run.id, {
      approval_id: approval.approval_id,
      approved,
      plan_hash: approval.plan_hash,
    })
    const updatedRun = { ...response.run, _streaming: response.run.status === 'running', _live_events: run._live_events || [] }
    runsById.value = { ...runsById.value, [response.run.id]: updatedRun }
    selectedRun.value = updatedRun
    if (response.run.status === 'running' && approved) {
      await restoreRunEvents(response.run)
    }
    if (activeSession.value) {
      messages.value = await listMessages(activeSession.value.id, 200)
      await loadMemories(activeSession.value.id)
      await loadSessions()
    }
  } catch (error) {
    setError(error)
  } finally {
    approving.value = false
  }
}

async function loadMemories(sessionId: string): Promise<void> {
  memoryLoading.value = true
  try {
    memories.value = await listSessionMemories(sessionId, {
      limit: 50,
      memory_type: memoryType.value === 'all' ? undefined : memoryType.value,
    })
  } catch {
    memories.value = []
  } finally {
    memoryLoading.value = false
  }
}

async function rebuildMemories(): Promise<void> {
  if (!activeSession.value) return
  memoryRebuilding.value = true
  try {
    await rebuildSessionMemories(activeSession.value.id)
    activeSession.value = await getSession(activeSession.value.id)
    await loadMemories(activeSession.value.id)
  } catch (error) {
    setError(error)
  } finally {
    memoryRebuilding.value = false
  }
}

async function renameSession(): Promise<void> {
  if (!activeSession.value || !renameTitle.value.trim()) return
  try {
    activeSession.value = await updateSession(activeSession.value.id, { title: renameTitle.value.trim() })
    await loadSessions()
  } catch (error) {
    setError(error)
  }
}

async function archiveSession(): Promise<void> {
  if (!activeSession.value) return
  try {
    activeSession.value = await updateSession(activeSession.value.id, { status: 'archived' })
    await loadSessions()
  } catch (error) {
    setError(error)
  }
}

function useQuestion(question: string): void {
  inputText.value = question
}

function updatePageHeight(): void {
  const page = pageRef.value
  if (!page) return
  const rect = page.getBoundingClientRect()
  const bottomGap = window.innerWidth <= 820 ? 32 : 40
  const availableHeight = Math.max(640, (window.innerHeight - rect.top - bottomGap) * 1.6)
  const cappedHeight = Math.min(availableHeight, window.innerHeight * 1.6)
  page.style.setProperty('--account-copilot-height', `${cappedHeight}px`)
}

function isMessagesNearBottom(): boolean {
  const viewport = messagesViewport.value
  if (!viewport) return true
  return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 80
}

function handleMessagesScroll(): void {
  shouldStickToBottom.value = isMessagesNearBottom()
}

async function scrollMessagesToBottom(force = false): Promise<void> {
  if (!force && !shouldStickToBottom.value) return
  await nextTick()
  const viewport = messagesViewport.value
  if (!viewport) return
  viewport.scrollTop = viewport.scrollHeight
}

function setError(error: unknown): void {
  errorMessage.value = error instanceof Error ? error.message : '请求失败'
}

watch(memoryType, () => {
  if (activeSession.value) {
    void loadMemories(activeSession.value.id)
  }
})

watch(
  () => stream.events.value.length,
  (length, previousLength) => {
    stream.events.value.slice(previousLength || 0, length).forEach(applyLiveEvent)
  },
)

watch(
  () => stream.error.value,
  (message) => {
    if (message) {
      errorMessage.value = message
    }
  },
)

watch(
  () => activeSession.value?.id,
  () => {
    shouldStickToBottom.value = true
    void scrollMessagesToBottom(true)
  },
)

watch(
  () => [
    messages.value.length,
    stream.events.value.length,
    selectedRun.value?.pending_approval?.approval_id,
    selectedRun.value?._live_final_answer,
  ],
  () => {
    void scrollMessagesToBottom()
  },
  { flush: 'post' },
)

onMounted(() => {
  void nextTick(() => {
    updatePageHeight()
    void scrollMessagesToBottom(true)
  })
  window.addEventListener('resize', updatePageHeight)
  void loadHealth()
  void loadSessions()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updatePageHeight)
})
</script>

<template>
  <main ref="pageRef" class="account-copilot-page">
    <CopilotSessionSidebar
      v-model:rename-title="renameTitle"
      :sessions="sessions"
      :active-session-id="activeSession?.id"
      :loading="loadingSessions"
      @create="createNewSession"
      @select="selectSession"
      @rename="renameSession"
      @archive="archiveSession"
    />

    <section class="copilot-chat">
      <header class="copilot-chat__header">
        <div>
          <p class="copilot-chat__eyebrow">ChatGPT-style account agent</p>
          <h1>{{ activeSession?.title || 'Account Copilot' }}</h1>
        </div>
        <div class="copilot-chat__badges">
          <Tag value="IBKR private facts" severity="info" />
          <Tag value="Longbridge public data" severity="success" />
          <Tag value="HITL Skills" severity="warn" />
          <button class="health-pill" @click="healthOpen = !healthOpen">
            <span :class="['health-dot', { 'is-ok': health?.ok }]" />
            <Tag :value="healthLabel" :severity="healthSeverity" />
          </button>
          <Button
            v-if="demoMode"
            label="加载 Demo 会话"
            icon="pi pi-play"
            severity="secondary"
            size="small"
            :loading="demoSeeding"
            @click="loadDemoSession"
          />
        </div>
      </header>

      <section v-if="healthOpen && health" class="health-panel">
        <div v-for="(check, name) in health.checks" :key="name" class="health-panel__item">
          <span :class="['health-dot', { 'is-ok': check.ok }]" />
          <strong>{{ name }}</strong>
          <span>{{ check.count !== undefined ? check.count : check.message || (check.ok ? 'ok' : 'degraded') }}</span>
        </div>
        <div class="health-panel__settings">
          rounds {{ health.settings.max_react_rounds }} · timeout {{ health.settings.run_timeout_seconds }}s · payload {{ health.settings.max_event_payload_chars }} chars
        </div>
      </section>

      <div v-if="errorMessage" class="copilot-chat__error">{{ errorMessage }}</div>

      <section v-if="!hasMessages && !loadingMessages" class="welcome-panel">
        <div>
          <p class="copilot-chat__eyebrow">Welcome</p>
          <h2>用自然语言盘问你的账户、持仓、交易和风险。</h2>
        </div>
        <div class="welcome-panel__groups">
          <section v-for="group in welcomeQuestionGroups" :key="group.title" class="welcome-panel__group">
            <h3>{{ group.title }}</h3>
            <button v-for="question in group.questions" :key="question" @click="useQuestion(question)">
              {{ question }}
            </button>
          </section>
        </div>
      </section>

      <div ref="messagesViewport" class="copilot-chat__messages" @scroll="handleMessagesScroll">
        <CopilotMessageList
          v-if="hasMessages || loadingMessages"
          :messages="messages"
          :runs-by-id="runsById"
          :selected-run-id="selectedRun?.id"
          :loading="loadingMessages"
          :approving="approving"
          @select-run="selectRun"
          @approve="approveSkill"
        />
      </div>

      <div class="copilot-chat__input">
        <div v-if="activeStreamingRun || streamReconnecting" class="copilot-chat__stream-status">
          <span>
            {{
              streamReconnecting
                ? `实时连接中断，正在第 ${reconnectAttempts} 次重连...`
                : '当前分析仍在运行，你可以等待完成后继续追问。'
            }}
          </span>
          <Button
            v-if="selectedRun && (selectedRun._streaming || selectedRun.status === 'running')"
            label="停止分析"
            icon="pi pi-stop-circle"
            severity="secondary"
            size="small"
            @click="cancelSelectedRun"
          />
        </div>
        <CopilotInputBox v-model="inputText" :loading="sending" @send="sendCurrentMessage" />
      </div>
    </section>

    <aside class="copilot-inspector">
      <CopilotRunTracePanel :run="selectedRun" />
      <CopilotMemoryPanel
        v-model:memory-type="memoryType"
        :memories="memories"
        :loading="memoryLoading"
        :rebuilding="memoryRebuilding"
        @rebuild="rebuildMemories"
      />
    </aside>
  </main>
</template>

<style scoped>
.account-copilot-page {
  display: flex;
  align-items: stretch;
  height: var(--account-copilot-height, calc(100vh - 180px));
  min-height: 640px;
  margin: 24px auto 0;
  max-width: 1720px;
  width: 100%;
  overflow: auto;
  color: #e2e8f0;
  border: 1px solid rgba(125, 211, 252, 0.15);
  border-radius: 18px;
  background:
    radial-gradient(circle at 28% 12%, rgba(34, 211, 238, 0.12), transparent 34%),
    linear-gradient(135deg, rgba(2, 6, 23, 0.94), rgba(15, 23, 42, 0.9));
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.32);
}

.copilot-chat {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.copilot-chat__header {
  display: flex;
  flex-shrink: 0;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 22px 24px;
  border-bottom: 1px solid rgba(125, 211, 252, 0.13);
}

.copilot-chat__header h1 {
  margin: 0;
  font-size: 1.45rem;
}

.copilot-chat__eyebrow {
  margin: 0 0 5px;
  color: #22d3ee;
  font-size: 0.72rem;
  text-transform: uppercase;
}

.copilot-chat__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.health-pill {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #f59e0b;
  box-shadow: 0 0 12px rgba(245, 158, 11, 0.65);
}

.health-dot.is-ok {
  background: #22c55e;
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.65);
}

.health-panel {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 14px 24px 0;
  padding: 12px;
  border: 1px solid rgba(125, 211, 252, 0.14);
  border-radius: 14px;
  background: rgba(2, 8, 23, 0.64);
}

.health-panel__item {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
  color: #94a3b8;
  font-size: 0.78rem;
}

.health-panel__item strong {
  color: #e2e8f0;
}

.health-panel__settings {
  grid-column: 1 / -1;
  color: #7dd3fc;
  font-size: 0.76rem;
}

.copilot-chat__error {
  flex-shrink: 0;
  margin: 14px 24px 0;
  padding: 10px 12px;
  color: #fecaca;
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 12px;
  background: rgba(127, 29, 29, 0.32);
}

.copilot-chat__messages {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.copilot-chat__input {
  flex-shrink: 0;
  padding: 18px 24px 22px;
  border-top: 1px solid rgba(125, 211, 252, 0.13);
}

.copilot-chat__stream-status {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
  padding: 10px 12px;
  color: #bae6fd;
  font-size: 0.82rem;
  border: 1px solid rgba(125, 211, 252, 0.18);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.66);
}

.welcome-panel {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  margin: 24px;
  padding: 22px;
  border: 1px solid rgba(125, 211, 252, 0.15);
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.58);
}

.welcome-panel h2 {
  max-width: 760px;
  margin: 0 0 18px;
  font-size: 1.35rem;
  line-height: 1.5;
}

.welcome-panel__groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.welcome-panel__group {
  display: grid;
  gap: 8px;
}

.welcome-panel__group h3 {
  margin: 0;
  color: #93c5fd;
  font-size: 0.82rem;
}

.welcome-panel__group button {
  padding: 12px;
  color: #dff7ff;
  text-align: left;
  border: 1px solid rgba(125, 211, 252, 0.16);
  border-radius: 14px;
  background: rgba(2, 8, 23, 0.52);
  cursor: pointer;
}

.welcome-panel__group button:hover {
  border-color: rgba(34, 211, 238, 0.72);
}

.copilot-inspector {
  display: grid;
  align-content: start;
  gap: 18px;
  width: 360px;
  min-width: 360px;
  height: 100%;
  min-height: 0;
  flex-shrink: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 18px;
  border-left: 1px solid rgba(125, 211, 252, 0.14);
  background: rgba(2, 8, 23, 0.72);
}

@media (max-width: 1180px) {
  .account-copilot-page {
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(220px, 34%);
  }

  .session-sidebar {
    grid-row: 1 / span 2;
  }

  .copilot-inspector {
    grid-column: 2;
    width: auto;
    min-width: 0;
    height: auto;
    border-left: 0;
    border-top: 1px solid rgba(125, 211, 252, 0.14);
  }
}

@media (max-width: 820px) {
  .account-copilot-page {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr) minmax(180px, 28%);
    margin: 12px;
  }

  .session-sidebar {
    grid-row: auto;
    width: auto;
    min-width: 0;
    max-height: 150px;
    border-right: 0;
    border-bottom: 1px solid rgba(125, 211, 252, 0.14);
  }

  .copilot-chat__header,
  .copilot-chat__input {
    padding-right: 16px;
    padding-left: 16px;
  }

  .copilot-inspector {
    grid-column: auto;
  }

  .welcome-panel__groups,
  .health-panel {
    grid-template-columns: 1fr;
  }
}
</style>
