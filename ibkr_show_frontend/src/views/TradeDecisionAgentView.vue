<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'
import SymbolInput from '@/components/SymbolInput.vue'
import { formatLocalDateTime } from '@/utils/dateTime'

import {
  fetchTradeDecisionDetail,
  fetchTradeDecisionHoldings,
  fetchRecentTradeDecisions,
  fetchTradeDecisionHealth,
  fetchTradeDecisionTasks,
  startEntryDecisionTask,
  startHoldingDecisionTask,
} from '@/api/tradeDecision'
import AgentEvidencePanel from '@/components/AgentEvidencePanel.vue'
import AgentTaskGraph from '@/components/AgentTaskGraph.vue'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import SymbolAnalysisPanel from '@/components/SymbolAnalysisPanel.vue'
import type { AgentTask } from '@/types/agentTasks'
import type { TradeDecisionHoldingItem, TradeDecisionHealth, TradeDecisionResult } from '@/types/tradeDecision'

const route = useRoute()
const router = useRouter()

const loading = ref(true)
const errorMessage = ref('')
const generatingKey = ref('')
const health = ref<TradeDecisionHealth | null>(null)
const currentHoldings = ref<TradeDecisionHoldingItem[]>([])
const recentDecisions = ref<TradeDecisionResult[]>([])
const selectedDecision = ref<TradeDecisionResult | null>(null)
const taskItems = ref<AgentTask[]>([])
const expandedTaskId = ref<string | null>(null)
const showAllRecentDecisions = ref(false)
const now = ref(Date.now())
let taskTimer: number | undefined

type DecisionMode = 'auto' | 'entry' | 'holding'
type DecisionTab = DecisionMode | 'research'

const entryForm = reactive({
  symbol: '',
  question: '',
})

const decisionMode = ref<DecisionMode>('auto')
const activeDecisionTab = ref<DecisionTab>('auto')

const scoreDimensions: readonly { key: string; label: string; fullWidth?: boolean }[] = [
  { key: 'fundamental_quality_score', label: '公司质量' },
  { key: 'valuation_score', label: '估值质量' },
  { key: 'trend_score', label: '趋势强度' },
  { key: 'account_fit_score', label: '账户适配' },
  { key: 'risk_reward_score', label: '风险收益' },
  { key: 'review_constraint_score', label: '复盘约束' },
  { key: 'event_catalyst_score', label: '事件催化', fullWidth: true },
]

const actionLabels: Record<string, string> = {
  add: '加仓',
  add_small: '小幅加仓',
  add_batch: '分批加仓',
  hold: '持有',
  reduce: '减仓',
  reduce_batch: '分批减仓',
  sell: '清仓',
  wait: '等待',
  avoid: '回避',
  watchlist: '观察',
}

const ratingLabels: Record<string, string> = {
  strong_buy_or_hold: '强买/强持',
  positive: '积极',
  neutral: '中性',
  negative: '谨慎',
}

const decisionTypeLabels: Record<string, string> = {
  entry_decision: '新标的建仓',
  holding_decision: '持仓管理',
}

const healthTone = computed(() => (health.value?.llm_configured ? 'p-tag--positive' : 'p-tag--negative'))
const visibleTasks = computed(() => {
  const active = taskItems.value.filter((t) => t.status === 'queued' || t.status === 'running')
  const done = taskItems.value.filter((t) => t.status === 'completed' || t.status === 'failed')
  return [...active, ...done.slice(0, 2)]
})
const activeTaskCount = computed(() => taskItems.value.filter((task) => task.status === 'queued' || task.status === 'running').length)
const isGenerating = computed(() => activeTaskCount.value > 0 || generatingKey.value !== '')
const isDecisionWorkTab = computed(() => activeDecisionTab.value !== 'research')
const recentDecisionVisibleLimit = 6
const visibleRecentDecisions = computed(() => (showAllRecentDecisions.value ? recentDecisions.value : recentDecisions.value.slice(0, recentDecisionVisibleLimit)))
const hiddenRecentDecisionCount = computed(() => Math.max(0, recentDecisions.value.length - recentDecisionVisibleLimit))

function hasPosition(symbol: string): TradeDecisionHoldingItem | undefined {
  return currentHoldings.value.find((h) => h.symbol === symbol.trim().toUpperCase())
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--'
  return new Intl.NumberFormat('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value)
}

function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '--'
  return `${formatNumber(value * 100, 2)}%`
}

function actionLabel(value: string | null | undefined): string {
  if (!value) return '--'
  return actionLabels[value] ?? value
}

function ratingLabel(value: string): string {
  return ratingLabels[value] ?? value
}

function decisionTypeLabel(value: string): string {
  return decisionTypeLabels[value] ?? value
}

function formatDateTime(value: string): string {
  return formatLocalDateTime(value) || '--'
}

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [healthResponse, holdingsResponse, decisionsResponse, tasksResponse] = await Promise.all([
      fetchTradeDecisionHealth(),
      fetchTradeDecisionHoldings(),
      fetchRecentTradeDecisions({ limit: 10 }),
      fetchTradeDecisionTasks(20),
    ])
    health.value = healthResponse
    currentHoldings.value = holdingsResponse.items
    recentDecisions.value = decisionsResponse
    taskItems.value = tasksResponse
    generatingKey.value = tasksResponse.some((task) => task.status === 'queued' || task.status === 'running') ? 'entry' : ''
    selectedDecision.value = decisionsResponse[0] ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 AI 决策失败'
  } finally {
    loading.value = false
  }
}

async function refreshRecent(): Promise<void> {
  recentDecisions.value = await fetchRecentTradeDecisions({ limit: 10 })
}

async function generateDecision(): Promise<void> {
  const symbol = entryForm.symbol.trim().toUpperCase()
  if (!symbol) return

  const position = hasPosition(symbol)
  let mode = decisionMode.value

  if (mode === 'auto') {
    mode = position ? 'holding' : 'entry'
  }

  generatingKey.value = mode
  errorMessage.value = ''

  try {
    let task: AgentTask
    if (mode === 'holding') {
      task = await startHoldingDecisionTask({ symbol, question: entryForm.question.trim() })
    } else {
      task = await startEntryDecisionTask({ symbol, question: entryForm.question.trim() })
    }
    taskItems.value = [task, ...taskItems.value.filter((item) => item.id !== task.id)].slice(0, 20)
    await pollTasks()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成交易建议失败'
    generatingKey.value = ''
  }
}

function taskElapsedSeconds(task: AgentTask): number {
  const start = Date.parse(task.started_at || task.created_at)
  const end = task.completed_at ? Date.parse(task.completed_at) : now.value
  return Math.max(0, Math.floor((end - start) / 1000))
}

function taskStage(task: AgentTask): string {
  if (task.status === 'completed') return '已完成'
  if (task.status === 'failed') return task.error_message || '运行失败'
  const elapsed = taskElapsedSeconds(task)
  if (elapsed < 5) return '排队并构建账户上下文'
  if (elapsed < 20) return '拉取 Longbridge 行情、估值和事件'
  if (elapsed < 45) return '调用 LLM 生成 AI 决策'
  return '保存结果并刷新列表'
}

function taskStatusLabel(status: AgentTask['status']): string {
  if (status === 'queued') return 'QUEUED'
  if (status === 'running') return 'RUNNING'
  if (status === 'completed') return 'DONE'
  return 'FAILED'
}

function toggleTask(task: AgentTask): void {
  expandedTaskId.value = expandedTaskId.value === task.id ? null : task.id
}

function mergeTaskGraphSnapshot(taskId: string, snapshot: AgentTask['graph_snapshot']): void {
  taskItems.value = taskItems.value.map((task) => (task.id === taskId ? { ...task, graph_snapshot: snapshot } : task))
}

function normalizeDecisionTab(value: unknown): DecisionTab {
  return value === 'entry' || value === 'holding' || value === 'research' ? value : 'auto'
}

function setDecisionTab(tab: DecisionTab): void {
  activeDecisionTab.value = tab
  if (tab !== 'research') {
    decisionMode.value = tab
  }
  void router.replace({ path: '/agent/trade-decision', query: { ...route.query, tab } })
}

async function viewTaskResult(task: AgentTask): Promise<void> {
  if (!task.result_id) return
  selectedDecision.value = await fetchTradeDecisionDetail(task.result_id)
}

async function pollTasks(): Promise<void> {
  try {
    const tasks = await fetchTradeDecisionTasks(20)
    taskItems.value = tasks
    const latestCompleted = tasks.find((task) => task.status === 'completed' && task.result_id)
    if (latestCompleted?.result_id && selectedDecision.value?.id !== latestCompleted.result_id) {
      const decision = await fetchTradeDecisionDetail(latestCompleted.result_id)
      selectedDecision.value = decision
      await refreshRecent()
    }
    generatingKey.value = tasks.some((task) => task.status === 'queued' || task.status === 'running') ? generatingKey.value : ''
  } catch {
    // Keep the last visible task state; the next poll can recover.
  }
}

onMounted(() => {
  activeDecisionTab.value = normalizeDecisionTab(route.query.tab)
  if (activeDecisionTab.value !== 'research') {
    decisionMode.value = activeDecisionTab.value
  }
  taskTimer = window.setInterval(() => {
    now.value = Date.now()
    if (activeTaskCount.value) {
      void pollTasks()
    }
  }, 2000)
  void loadPage()
})

watch(
  () => route.query.tab,
  (tab) => {
    activeDecisionTab.value = normalizeDecisionTab(tab)
    if (activeDecisionTab.value !== 'research') {
      decisionMode.value = activeDecisionTab.value
    }
  },
)

onBeforeUnmount(() => {
  if (taskTimer) {
    window.clearInterval(taskTimer)
  }
})
</script>

<template>
  <section class="page-section trade-decision-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">AGENT</p>
            <h2 class="trade-decision-title">AI 决策</h2>
            <p class="panel-subtitle">输入股票代码，获取建仓建议、持仓管理建议或标的研究分析。</p>
          </div>
          <div class="decision-health">
            <Tag :value="health?.llm_configured ? 'LLM READY' : 'LLM MISSING'" :class="healthTone" />
            <Tag :value="health?.longbridge_configured ? 'LONGBRIDGE READY' : 'LONGBRIDGE LIMITED'" :class="health?.longbridge_configured ? 'p-tag--positive' : 'p-tag--accent'" />
            <Tag
              :value="health?.mcp_auth_status === 'connected' || health?.mcp_auth_status === 'static_token' ? 'MCP CONNECTED' : 'MCP AUTH REQUIRED'"
              :class="health?.mcp_auth_status === 'connected' || health?.mcp_auth_status === 'static_token' ? 'p-tag--positive' : 'p-tag--negative'"
            />
          </div>
        </div>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage && !selectedDecision" :message="errorMessage" />

    <template v-else>
      <ErrorBlock v-if="errorMessage" :message="errorMessage" />

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">AI 决策</h3>
              <p class="panel-subtitle">输入股票代码，获取建仓建议、持仓管理建议或标的研究分析。</p>
            </div>
          </div>

          <div class="mode-selector">
            <label class="mode-option">
              <input :checked="activeDecisionTab === 'auto'" type="radio" value="auto" @change="setDecisionTab('auto')" />
              <span>自动判断</span>
            </label>
            <label class="mode-option">
              <input :checked="activeDecisionTab === 'entry'" type="radio" value="entry" @change="setDecisionTab('entry')" />
              <span>建仓（新标的）</span>
            </label>
            <label class="mode-option">
              <input :checked="activeDecisionTab === 'holding'" type="radio" value="holding" @change="setDecisionTab('holding')" />
              <span>持仓管理（已有持仓）</span>
            </label>
            <label class="mode-option">
              <input :checked="activeDecisionTab === 'research'" type="radio" value="research" @change="setDecisionTab('research')" />
              <span>标的研究</span>
            </label>
          </div>

          <form v-if="isDecisionWorkTab" class="entry-form" @submit.prevent="generateDecision">
            <label class="field-stack">
              <span class="field-stack__label">Symbol</span>
              <SymbolInput v-model="entryForm.symbol" required placeholder="AAPL / MSFT / NVDA" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">问题</span>
              <InputText v-model="entryForm.question" placeholder="现在适合建仓吗？" />
            </label>
            <div class="entry-form__actions">
              <Button
                :label="isGenerating ? '任务运行中' : '生成交易建议'"
                :icon="isGenerating ? 'pi pi-spin pi-spinner' : 'pi pi-send'"
                class="p-button p-button--accent entry-generate-button"
                type="submit"
                :disabled="isGenerating"
              />
            </div>
          </form>

          <div v-if="isDecisionWorkTab && entryForm.symbol && hasPosition(entryForm.symbol.toUpperCase())" class="holding-hint">
            <Tag value="已有持仓" class="p-tag--accent" />
            <span>{{ entryForm.symbol.toUpperCase() }} 当前存在持仓</span>
          </div>
          <div v-else-if="isDecisionWorkTab && entryForm.symbol && decisionMode === 'holding'" class="holding-hint holding-hint--warning">
            <Tag value="无持仓" class="p-tag--warning" />
            <span>{{ entryForm.symbol.toUpperCase() }} 当前无持仓，但仍可提交管理建议</span>
          </div>
          <SymbolAnalysisPanel v-if="activeDecisionTab === 'research'" />
        </div>
      </section>

      <section v-if="isDecisionWorkTab && visibleTasks.length" class="surface-panel decision-runner-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">后台任务</h3>
              <p class="panel-subtitle">切换页面后任务仍会在后端继续运行，回来后自动恢复状态和结果。</p>
            </div>
          </div>
          <div class="runner-list">
            <div
              v-for="task in visibleTasks"
              :key="task.id"
              class="runner-item"
              :class="`runner-item--${task.status}`"
            >
              <button type="button" class="runner-item__summary" @click="toggleTask(task)">
                <span class="runner-item__dot" aria-hidden="true"></span>
                <div class="runner-item__main">
                  <strong>{{ task.label }}</strong>
                  <span>{{ taskStage(task) }}</span>
                </div>
                <div class="runner-item__meta">
                  <Tag :value="taskStatusLabel(task.status)" :class="task.status === 'failed' ? 'p-tag--negative' : task.status === 'completed' ? 'p-tag--positive' : 'p-tag--accent'" />
                  <span>{{ taskElapsedSeconds(task) }}s</span>
                  <span class="pi" :class="expandedTaskId === task.id ? 'pi-chevron-up' : 'pi-chevron-down'" />
                </div>
              </button>
              <AgentTaskGraph
                v-if="expandedTaskId === task.id"
                :task="task"
                :expanded="expandedTaskId === task.id"
                @snapshot="mergeTaskGraphSnapshot"
              />
              <div v-if="expandedTaskId === task.id && task.result_id" class="runner-item__actions">
                <Button type="button" label="查看结果" size="small" severity="secondary" @click.stop="viewTaskResult(task)" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-if="isDecisionWorkTab" class="decision-layout">
        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">最近决策</h3>
                <p class="panel-subtitle">每次生成都会保存一条历史记录。</p>
              </div>
            </div>
            <div v-if="recentDecisions.length" class="decision-list">
              <button v-for="item in visibleRecentDecisions" :key="item.id" type="button" :class="{ 'is-active': selectedDecision?.id === item.id }" @click="selectedDecision = item">
                <strong>{{ item.symbol }}</strong>
                <span>{{ decisionTypeLabel(item.decision_type) }}</span>
                <span>{{ item.overall_score }}/100 · {{ actionLabel(item.action) }}</span>
                <small>{{ item.decision_summary }}</small>
              </button>
              <button v-if="hiddenRecentDecisionCount" type="button" class="list-toggle-button" @click="showAllRecentDecisions = !showAllRecentDecisions">
                {{ showAllRecentDecisions ? '收起' : `展开其余 ${hiddenRecentDecisionCount} 条` }}
              </button>
            </div>
            <div v-else class="empty-state">暂无 AI 决策</div>
          </div>
        </section>

        <section v-if="selectedDecision" class="surface-panel">
          <div class="surface-panel__content">
            <div class="decision-detail-header">
              <div>
                <p class="eyebrow">{{ decisionTypeLabel(selectedDecision.decision_type) }}</p>
                <h3>{{ selectedDecision.overall_score }}<span>/100</span></h3>
                <p class="panel-subtitle">{{ selectedDecision.decision_summary }}</p>
              </div>
              <div class="decision-tags">
                <Tag :value="actionLabel(selectedDecision.action)" class="p-tag--accent" />
                <Tag :value="ratingLabel(selectedDecision.rating)" :class="selectedDecision.overall_score >= 70 ? 'p-tag--positive' : selectedDecision.overall_score < 50 ? 'p-tag--negative' : 'p-tag--accent'" />
                <Tag :value="selectedDecision.confidence === 'high' ? '高置信' : selectedDecision.confidence === 'medium' ? '中置信' : '低置信'" class="p-tag--accent" />
              </div>
            </div>

            <section class="score-grid">
              <div
                v-for="item in scoreDimensions"
                :key="item.key"
                class="score-card"
                :class="{ 'score-card--full': item.fullWidth }"
              >
                <div class="score-card__head">
                  <span>{{ item.label }}</span>
                  <strong>{{ selectedDecision.score_detail[item.key]?.score ?? 0 }}/{{ selectedDecision.score_detail[item.key]?.max_score ?? 0 }}</strong>
                </div>
                <div class="score-card__reason-wrap">
                  <p class="score-card__reason">{{ selectedDecision.score_detail[item.key]?.reason ?? '暂无说明' }}</p>
                  <div class="score-card__tooltip">{{ selectedDecision.score_detail[item.key]?.reason ?? '暂无说明' }}</div>
                </div>
              </div>
            </section>

            <section class="advice-grid">
              <div class="advice-card">
                <h4>仓位建议</h4>
                <span>当前仓位：{{ formatPct(selectedDecision.position_advice.current_position_pct) }}</span>
                <span>目标仓位：{{ formatPct(selectedDecision.position_advice.suggested_target_position_pct) }}</span>
                <span>最大仓位：{{ formatPct(selectedDecision.position_advice.max_position_pct) }}</span>
                <span>建议金额：{{ formatNumber(selectedDecision.position_advice.suggested_cash_amount) }}</span>
                <span>仓位标签：{{ selectedDecision.position_advice.position_size_label }}</span>
              </div>
              <div class="advice-card">
                <h4>执行建议</h4>
                <span>是否现在行动：{{ selectedDecision.execution_plan.should_act_now ? '是' : '否' }}</span>
                <ul>
                  <li v-for="(step, index) in selectedDecision.execution_plan.plan" :key="index">
                    {{ step.condition ?? '条件' }}：{{ step.action ?? '行动' }} {{ step.amount ? `· ${formatNumber(Number(step.amount))}` : '' }} {{ step.note ?? '' }}
                  </li>
                </ul>
              </div>
            </section>

            <section class="insight-grid">
              <div class="insight-block">
                <h4>关键理由</h4>
                <ul><li v-for="item in selectedDecision.key_reasons" :key="item">{{ item }}</li></ul>
              </div>
              <div class="insight-block">
                <h4>主要风险</h4>
                <ul><li v-for="item in selectedDecision.major_risks" :key="item">{{ item }}</li></ul>
              </div>
              <div class="insight-block">
                <h4>复盘约束</h4>
                <ul><li v-for="item in selectedDecision.review_warnings" :key="item">{{ item }}</li></ul>
              </div>
              <div v-if="selectedDecision.data_limitations && selectedDecision.data_limitations.length > 0" class="insight-block">
                <h4>数据限制</h4>
                <ul>
                  <li
                    v-for="item in selectedDecision.data_limitations"
                    :key="item"
                    :class="item.startsWith('valuation_not_applicable') ? 'limitation-info' : ''"
                  >{{ item.startsWith('valuation_not_applicable') ? item.replace('valuation_not_applicable: ', '') : item }}</li>
                </ul>
              </div>
            </section>

            <div class="source-row">
              <Tag value="账户/持仓/交易：IBKR" class="p-tag--positive" />
              <Tag value="公开市场数据：Longbridge" class="p-tag--accent" />
              <Tag value="决策生成：LLMService" class="p-tag--accent" />
            </div>
          </div>
        </section>

        <AgentEvidencePanel
          v-if="selectedDecision"
          :metadata="selectedDecision.metadata"
          :evidence-summary="selectedDecision.evidence_summary"
          :run-trace-summary="selectedDecision.run_trace_summary"
        />
      </section>
    </template>
  </section>
</template>

<style scoped>
.trade-decision-title {
  margin: 0;
  font-size: 1.55rem;
}

.decision-health,
.decision-tags,
.source-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
  min-width: 0;
}

.decision-health,
.decision-tags {
  max-width: min(420px, 100%);
}

.decision-tags {
  align-content: flex-start;
}

.mode-selector {
  display: flex;
  gap: 12px;
  margin-bottom: var(--space-4);
  padding: 12px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.46);
}

.mode-option {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.mode-option input[type='radio'] {
  accent-color: var(--color-accent);
}

.mode-option:has(input:checked) {
  color: var(--color-text-primary);
}

.holding-hint {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: var(--space-3);
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: rgba(32, 79, 129, 0.32);
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}

.holding-hint--warning {
  background: rgba(255, 180, 84, 0.12);
}

.score-card,
.advice-card,
.insight-block {
  padding: 16px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.58);
}

.decision-list small,
.score-card p,
.advice-card span,
.insight-block li {
  color: var(--color-text-secondary);
}

.insight-block li.limitation-info {
  color: var(--color-accent, #81a0cf);
  font-style: italic;
}

.entry-form {
  display: grid;
  grid-template-columns: minmax(180px, 0.6fr) minmax(240px, 1fr) auto;
  gap: var(--space-3);
  align-items: end;
}

.entry-form__actions {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  min-width: 180px;
  min-height: 46px;
  max-height: 46px;
  overflow: visible;
}

.runner-list {
  display: grid;
  gap: 10px;
}

.runner-item {
  display: block;
  width: 100%;
  padding: 12px 14px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.58);
}

.runner-item__summary {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-primary);
  cursor: pointer;
  text-align: left;
}

.runner-item__dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--color-accent);
}

.runner-item--queued .runner-item__dot,
.runner-item--running .runner-item__dot {
  animation: runner-pulse 1.2s ease-in-out infinite;
}

.runner-item--completed .runner-item__dot {
  background: var(--color-positive);
}

.runner-item--failed .runner-item__dot {
  background: var(--color-negative);
}

.runner-item__main {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.runner-item__main span,
.runner-item__meta span {
  color: var(--color-text-secondary);
}

.runner-item__meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.runner-item__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

@keyframes runner-pulse {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}

:deep(.entry-generate-button) {
  flex: 0 0 auto;
  width: 180px;
  height: 44px;
  min-height: 44px;
  max-height: 44px;
}

.decision-layout {
  display: grid;
  grid-template-columns: minmax(300px, 0.8fr) minmax(0, 1.2fr);
  gap: var(--space-4);
}

.decision-list {
  display: grid;
  gap: 10px;
}

.decision-list button {
  display: grid;
  gap: 6px;
  width: 100%;
  padding: 14px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.62);
  color: var(--color-text-primary);
  cursor: pointer;
  text-align: left;
}

.decision-list button:not(.list-toggle-button).is-active,
.decision-list button:not(.list-toggle-button):hover {
  border-color: rgba(86, 213, 255, 0.34);
  background: rgba(19, 42, 70, 0.82);
}

.list-toggle-button {
  justify-items: center;
  color: var(--color-accent-strong);
  font-weight: 700;
  text-align: center;
}

.decision-detail-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) max-content;
  align-items: flex-start;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.decision-detail-header > div:first-child {
  min-width: 0;
}

.decision-detail-header .panel-subtitle {
  overflow-wrap: anywhere;
}

.decision-detail-header h3 {
  margin: 0;
  font-size: 3rem;
}

.decision-detail-header h3 span {
  font-size: 1.1rem;
  color: var(--color-text-secondary);
}

.score-grid,
.advice-grid,
.insight-grid {
  display: grid;
  gap: var(--space-3);
}

.score-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.score-card__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.score-card p {
  margin: 0;
}

.score-card--full {
  grid-column: 1 / -1;
}

.score-card__reason-wrap {
  position: relative;
}

.score-card__reason {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  overflow-wrap: anywhere;
  line-height: 1.6;
  margin: 0;
}

.score-card__tooltip {
  position: absolute;
  left: 0;
  top: calc(100% + 10px);
  z-index: 50;
  display: none;
  width: min(720px, calc(100vw - 80px));
  padding: 12px 14px;
  border: 1px solid rgba(129, 160, 207, 0.28);
  border-radius: var(--radius-md);
  background: rgba(8, 15, 28, 0.98);
  color: var(--color-text-primary);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.42);
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  pointer-events: none;
}

.score-card__reason-wrap:hover .score-card__tooltip {
  display: block;
}

.score-card--full .score-card__tooltip {
  width: min(900px, calc(100vw - 80px));
}

.advice-grid,
.insight-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: var(--space-4);
}

.advice-card {
  display: grid;
  gap: 8px;
}

.advice-card h4,
.insight-block h4 {
  margin: 0 0 8px;
}

.advice-card ul,
.insight-block ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 18px;
}

.source-row {
  justify-content: flex-start;
  margin-top: var(--space-4);
}

@media (max-width: 1200px) {
  .decision-layout,
  .entry-form {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .score-grid,
  .advice-grid,
  .insight-grid {
    grid-template-columns: 1fr;
  }

  .score-card--full {
    grid-column: auto;
  }

  .score-card__tooltip {
    display: none !important;
  }

  .decision-detail-header {
    display: grid;
    grid-template-columns: 1fr;
  }

  .decision-tags {
    justify-content: flex-start;
  }

  .mode-selector {
    flex-direction: column;
    gap: 8px;
  }
}
</style>
