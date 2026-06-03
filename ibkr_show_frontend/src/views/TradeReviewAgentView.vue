<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'
import SymbolInput from '@/components/SymbolInput.vue'
import { formatLocalDateTime } from '@/utils/dateTime'

import {
  fetchMistakeSummary,
  fetchRecentTradeReviews,
  fetchTradeReviewDetail,
  fetchTradeReviewHealth,
  fetchTradeReviewTasks,
  startSingleTradeReviewTask,
  startSymbolReviewTask,
} from '@/api/tradeReview'
import AgentEvidencePanel from '@/components/AgentEvidencePanel.vue'
import AgentTaskGraph from '@/components/AgentTaskGraph.vue'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import DailyPositionReviewView from '@/views/DailyPositionReviewView.vue'
import type { AgentTask } from '@/types/agentTasks'
import type { TradeReviewHealth, TradeReviewMistakeSummaryItem, TradeReviewResult } from '@/types/tradeReview'

const route = useRoute()
const router = useRouter()

const symbolForm = reactive({
  symbol: '',
  start_date: '',
  end_date: '',
})
const tradeForm = reactive({
  trade_id: '',
})

const loading = ref(true)
const errorMessage = ref('')
const pageLoadFailed = ref(false)
const health = ref<TradeReviewHealth | null>(null)
const recentReviews = ref<TradeReviewResult[]>([])
const mistakeItems = ref<TradeReviewMistakeSummaryItem[]>([])
const selectedReview = ref<TradeReviewResult | null>(null)
const showAllRecentReviews = ref(false)
const now = ref(Date.now())
let clockTimer: number | undefined

const reviewTasks = ref<AgentTask[]>([])
const expandedTaskId = ref<string | null>(null)
type ReviewTab = 'symbol-review' | 'daily-review'
const activeReviewTab = ref<ReviewTab>('symbol-review')

const scoreDimensions = [
  ['return_result_score', '收益结果'],
  ['relative_performance_score', '相对收益'],
  ['entry_quality_score', '买点质量'],
  ['exit_quality_score', '卖点质量'],
  ['position_sizing_score', '仓位质量'],
  ['holding_period_score', '持仓周期'],
  ['risk_control_score', '风险控制'],
  ['decision_attribution_score', '决策归因'],
] as const

const mistakeTagLabels: Record<string, string> = {
  CHASE_HIGH: '追高买入',
  SELL_TOO_EARLY: '卖出过早',
  SELL_TOO_LATE: '卖出过晚',
  PANIC_SELL: '恐慌卖出',
  POSITION_TOO_SMALL: '仓位过小',
  POSITION_TOO_LARGE: '仓位过重',
  MISSED_OPPORTUNITY: '错过机会',
  NO_CLEAR_PLAN: '计划不清晰',
  WEAK_RELATIVE_PERFORMANCE: '相对表现弱',
  GOOD_ENTRY: '买点优秀',
  GOOD_EXIT: '卖点优秀',
  GOOD_POSITION_SIZING: '仓位合理',
  GOOD_TREND_FOLLOW: '趋势跟随好',
  GOOD_RISK_CONTROL: '风控优秀',
}

const reviewTypeLabels: Record<string, string> = {
  symbol_level_review: '标的级复盘',
  single_trade_review: '单笔交易复盘',
}

const ratingLabels: Record<string, string> = {
  excellent: '优秀',
  good: '良好',
  average: '一般',
  poor: '较差',
}

const healthTone = computed(() => (health.value?.llm_configured ? 'p-tag--positive' : 'p-tag--negative'))
const visibleTasks = computed(() => {
  const active = reviewTasks.value.filter((t) => t.status === 'queued' || t.status === 'running')
  const done = reviewTasks.value.filter((t) => t.status === 'completed' || t.status === 'failed')
  return [...active, ...done.slice(0, 2)]
})
const activeTaskCount = computed(() => reviewTasks.value.filter((task) => task.status === 'queued' || task.status === 'running').length)
const isGeneratingSymbol = computed(() => reviewTasks.value.some((task) => task.task_type === 'symbol_level_review' && (task.status === 'queued' || task.status === 'running')))
const isGeneratingTrade = computed(() => reviewTasks.value.some((task) => task.task_type === 'single_trade_review' && (task.status === 'queued' || task.status === 'running')))
const recentReviewVisibleLimit = 6
const visibleRecentReviews = computed(() => (showAllRecentReviews.value ? recentReviews.value : recentReviews.value.slice(0, recentReviewVisibleLimit)))
const hiddenRecentReviewCount = computed(() => Math.max(0, recentReviews.value.length - recentReviewVisibleLimit))

function normalizeReviewTab(value: unknown): ReviewTab {
  return value === 'daily-review' ? 'daily-review' : 'symbol-review'
}

function setReviewTab(tab: ReviewTab): void {
  activeReviewTab.value = tab
  void router.replace({ path: '/agent/trade-review', query: { ...route.query, tab } })
}

function formatDateTime(value: string): string {
  return formatLocalDateTime(value) || '--'
}

function ratingClass(rating: string): string {
  if (rating === 'excellent' || rating === 'good') {
    return 'p-tag--positive'
  }
  if (rating === 'poor') {
    return 'p-tag--negative'
  }
  return 'p-tag--accent'
}

function mistakeTagLabel(tag: string): string {
  return mistakeTagLabels[tag] ?? tag
}

function reviewTypeLabel(reviewType: string): string {
  return reviewTypeLabels[reviewType] ?? reviewType
}

function ratingLabel(rating: string): string {
  return ratingLabels[rating] ?? rating
}

function selectedTradeFacts(): Record<string, any> {
  return (selectedReview.value?.evidence_pack?.trade_facts as Record<string, any> | undefined) ?? {}
}

function scoreReason(key: string): string {
  const item = selectedReview.value?.score_detail[key]
  const reason = item?.reason || '暂无说明'
  if (key !== 'exit_quality_score' || item?.applicable === false) {
    return reason
  }
  const facts = selectedTradeFacts()
  if (facts.has_reopened_position_after_sell === true && !reason.includes('当前最新持仓尚未退出')) {
    return `${reason}；评价历史卖出批次；当前最新持仓尚未退出。`
  }
  return reason
}

function taskElapsedSeconds(task: AgentTask): number {
  const start = Date.parse(task.started_at || task.created_at)
  const end = task.completed_at ? Date.parse(task.completed_at) : now.value
  return Math.max(0, Math.floor((end - start) / 1000))
}

function taskStage(task: AgentTask): string {
  if (task.status === 'completed') {
    return '已完成'
  }
  if (task.status === 'failed') {
    return task.error_message || '运行失败'
  }
  const elapsed = taskElapsedSeconds(task)
  if (elapsed < 5) {
    return '构建 IBKR 交易事实'
  }
  if (elapsed < 15) {
    return '拉取长桥 K 线、基准与资讯'
  }
  if (elapsed < 35) {
    return '调用 LLM 生成 8 维评分'
  }
  return '保存复盘结果并刷新列表'
}

function formatElapsed(task: AgentTask): string {
  const elapsed = taskElapsedSeconds(task)
  if (elapsed < 60) {
    return `${elapsed}s`
  }
  const minutes = Math.floor(elapsed / 60)
  const seconds = elapsed % 60
  return `${minutes}m ${seconds}s`
}

function toggleTask(task: AgentTask): void {
  expandedTaskId.value = expandedTaskId.value === task.id ? null : task.id
}

function mergeTaskGraphSnapshot(taskId: string, snapshot: AgentTask['graph_snapshot']): void {
  reviewTasks.value = reviewTasks.value.map((task) => (task.id === taskId ? { ...task, graph_snapshot: snapshot } : task))
}

async function viewTaskResult(task: AgentTask): Promise<void> {
  if (!task.result_id) return
  selectedReview.value = await fetchTradeReviewDetail(task.result_id)
}

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  pageLoadFailed.value = false
  try {
    const [healthResponse, reviewsResponse, mistakesResponse, tasksResponse] = await Promise.all([
      fetchTradeReviewHealth(),
      fetchRecentTradeReviews({ limit: 20 }),
      fetchMistakeSummary(),
      fetchTradeReviewTasks(20),
    ])
    health.value = healthResponse
    recentReviews.value = reviewsResponse
    mistakeItems.value = mistakesResponse.items
    reviewTasks.value = tasksResponse
    selectedReview.value = reviewsResponse[0] ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 AI 复盘失败'
    pageLoadFailed.value = true
  } finally {
    loading.value = false
  }
}

async function generateSymbol(): Promise<void> {
  const symbol = symbolForm.symbol.trim().toUpperCase()
  if (!symbol) {
    return
  }
  errorMessage.value = ''
  try {
    const task = await startSymbolReviewTask({
      symbol,
      start_date: symbolForm.start_date,
      end_date: symbolForm.end_date,
    })
    reviewTasks.value = [task, ...reviewTasks.value.filter((item) => item.id !== task.id)].slice(0, 20)
    await pollTasks()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成标的复盘失败'
  }
}

async function generateTrade(): Promise<void> {
  const tradeId = tradeForm.trade_id.trim()
  if (!tradeId) {
    return
  }
  errorMessage.value = ''
  try {
    const task = await startSingleTradeReviewTask(tradeId)
    reviewTasks.value = [task, ...reviewTasks.value.filter((item) => item.id !== task.id)].slice(0, 20)
    await pollTasks()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成单笔复盘失败'
  }
}

async function loadRecentOnly(): Promise<void> {
  const [reviewsResponse, mistakesResponse] = await Promise.all([
    fetchRecentTradeReviews({ limit: 20 }),
    fetchMistakeSummary(),
  ])
  recentReviews.value = reviewsResponse
  mistakeItems.value = mistakesResponse.items
}

async function selectReview(review: TradeReviewResult): Promise<void> {
  try {
    selectedReview.value = await fetchTradeReviewDetail(review.id)
  } catch {
    selectedReview.value = review
  }
}

async function pollTasks(): Promise<void> {
  try {
    const tasks = await fetchTradeReviewTasks(20)
    reviewTasks.value = tasks
    const latestCompleted = tasks.find((task) => task.status === 'completed' && task.result_id)
    if (latestCompleted?.result_id && selectedReview.value?.id !== latestCompleted.result_id) {
      const review = await fetchTradeReviewDetail(latestCompleted.result_id)
      selectedReview.value = review
      await loadRecentOnly()
    }
  } catch {
    // Keep the last visible task state; the next poll can recover.
  }
}

onMounted(() => {
  activeReviewTab.value = normalizeReviewTab(route.query.tab)
  const queryTradeId = route.query.trade_id
  if (typeof queryTradeId === 'string' && queryTradeId) {
    tradeForm.trade_id = queryTradeId
  }
  clockTimer = window.setInterval(() => {
    now.value = Date.now()
    if (activeTaskCount.value) {
      void pollTasks()
    }
  }, 1000)
  void loadPage()
})

watch(
  () => route.query.tab,
  (tab) => {
    activeReviewTab.value = normalizeReviewTab(tab)
  },
)

onBeforeUnmount(() => {
  if (clockTimer) {
    window.clearInterval(clockTimer)
  }
})
</script>

<template>
  <section class="page-section trade-review-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">AGENT</p>
            <h2 class="trade-review-title">AI 复盘</h2>
            <p class="panel-subtitle">复盘单个标的交易表现，或分析每日账户涨跌归因。</p>
          </div>
          <div class="agent-health">
            <Tag :value="health?.llm_configured ? 'LLM READY' : 'LLM MISSING'" :class="healthTone" />
            <Tag :value="health?.longbridge_configured ? 'LONGBRIDGE READY' : 'LONGBRIDGE LIMITED'" :class="health?.longbridge_configured ? 'p-tag--positive' : 'p-tag--accent'" />
          </div>
        </div>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="pageLoadFailed && errorMessage" :message="errorMessage" />

    <template v-else>
      <ErrorBlock v-if="errorMessage" :message="errorMessage" />

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="review-tab-selector">
            <label class="review-tab-option">
              <input :checked="activeReviewTab === 'symbol-review'" type="radio" value="symbol-review" @change="setReviewTab('symbol-review')" />
              <span>标的复盘</span>
            </label>
            <label class="review-tab-option">
              <input :checked="activeReviewTab === 'daily-review'" type="radio" value="daily-review" @change="setReviewTab('daily-review')" />
              <span>每日复盘</span>
            </label>
          </div>
        </div>
      </section>

      <DailyPositionReviewView v-if="activeReviewTab === 'daily-review'" embedded />

      <template v-else>
      <section class="generation-grid">
        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">标的级复盘</h3>
                <p class="panel-subtitle">复盘某个 symbol 的完整买入、加仓、减仓、卖出历史。</p>
              </div>
            </div>
            <form class="review-form" @submit.prevent="generateSymbol">
              <label class="field-stack field-stack--wide">
                <span class="field-stack__label">Symbol</span>
                <SymbolInput v-model="symbolForm.symbol" required placeholder="ARM / MSFT / AMD" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">开始日期</span>
                <InputText v-model="symbolForm.start_date" type="date" />
              </label>
              <label class="field-stack">
                <span class="field-stack__label">结束日期</span>
                <InputText v-model="symbolForm.end_date" type="date" />
              </label>
              <div class="review-form-actions field-stack--wide">
                <Button
                  :label="isGeneratingSymbol ? '生成中' : '生成标的复盘'"
                  :icon="isGeneratingSymbol ? 'pi pi-spin pi-spinner' : 'pi pi-sparkles'"
                  type="submit"
                  class="p-button p-button--accent review-generate-button"
                  :disabled="isGeneratingSymbol"
                />
              </div>
            </form>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">单笔交易复盘</h3>
                <p class="panel-subtitle">复盘某一笔买入、卖出、加仓或减仓。</p>
              </div>
            </div>
            <form class="review-form" @submit.prevent="generateTrade">
              <label class="field-stack field-stack--wide">
                <span class="field-stack__label">Trade ID</span>
                <InputText v-model="tradeForm.trade_id" required placeholder="trade_id / transaction_id" />
              </label>
              <div class="review-form-actions field-stack--wide">
                <Button
                  :label="isGeneratingTrade ? '生成中' : '生成单笔复盘'"
                  :icon="isGeneratingTrade ? 'pi pi-spin pi-spinner' : 'pi pi-send'"
                  type="submit"
                  class="p-button p-button--accent review-generate-button"
                  :disabled="isGeneratingTrade"
                />
              </div>
            </form>
          </div>
        </section>
      </section>

      <section v-if="visibleTasks.length" class="surface-panel review-runner-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">复盘运行状态</h3>
              <p class="panel-subtitle">
                {{ activeTaskCount ? `${activeTaskCount} 个复盘正在运行` : '最近完成的复盘任务' }}
              </p>
            </div>
          </div>
          <div class="runner-list">
            <div v-for="task in visibleTasks" :key="task.id" class="runner-item" :class="`runner-item--${task.status}`">
              <button type="button" class="runner-item__summary" @click="toggleTask(task)">
                <span class="runner-item__dot" aria-hidden="true"></span>
                <div class="runner-item__main">
                  <strong>{{ task.label }}</strong>
                  <span>{{ taskStage(task) }}</span>
                </div>
                <div class="runner-item__meta">
                  <span>{{ formatElapsed(task) }}</span>
                  <Tag
                    :value="task.status === 'queued' ? 'QUEUED' : task.status === 'running' ? 'RUNNING' : task.status === 'completed' ? 'DONE' : 'FAILED'"
                    :class="task.status === 'completed' ? 'p-tag--positive' : task.status === 'failed' ? 'p-tag--negative' : 'p-tag--accent'"
                  />
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

      <section class="review-layout">
        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">最近复盘</h3>
                <p class="panel-subtitle">默认展示最新生成的复盘结果。</p>
              </div>
            </div>
            <div v-if="recentReviews.length" class="review-list">
              <button
                v-for="review in visibleRecentReviews"
                :key="review.id"
                class="review-list__item"
                :class="{ 'is-active': selectedReview?.id === review.id }"
                type="button"
                @click="selectReview(review)"
              >
                <span>{{ formatDateTime(review.created_at) }}</span>
                <strong>{{ review.symbol }}</strong>
                <span>{{ reviewTypeLabel(review.review_type) }}</span>
                <span>{{ review.overall_score }}/100 · {{ ratingLabel(review.rating) }}</span>
                <small>{{ review.summary }}</small>
              </button>
              <button v-if="hiddenRecentReviewCount" type="button" class="review-list__item review-list__item--toggle" @click="showAllRecentReviews = !showAllRecentReviews">
                {{ showAllRecentReviews ? '收起' : `展开其余 ${hiddenRecentReviewCount} 条` }}
              </button>
            </div>
            <div v-else class="empty-state">暂无复盘记录</div>
          </div>
        </section>

        <div class="review-result-stack">
          <section v-if="selectedReview" class="surface-panel">
            <div class="surface-panel__content">
              <div class="review-detail-header">
                <div>
                  <p class="eyebrow">{{ reviewTypeLabel(selectedReview.review_type) }}</p>
                  <h3 class="review-score">{{ selectedReview.overall_score }}<span>/100</span></h3>
                  <p v-if="selectedReview.excluded_score_dimensions?.length" class="score-basis">
                    适用维度得分：{{ selectedReview.raw_applicable_score }}/{{ selectedReview.applicable_max_score }}
                    ，已排除：{{ selectedReview.excluded_score_dimensions.map(d => `${d.label} ${d.max_score}分`).join('、') }}
                  </p>
                  <p class="panel-subtitle">{{ selectedReview.summary }}</p>
                </div>
                <Tag :value="ratingLabel(selectedReview.rating)" :class="ratingClass(selectedReview.rating)" />
              </div>

              <section class="score-grid">
                <div v-for="[key, label] in scoreDimensions" :key="key" class="score-card" :class="{ 'score-card--na': selectedReview.score_detail[key]?.applicable === false }">
                  <div class="score-card__head">
                    <span>{{ label }}</span>
                    <strong v-if="selectedReview.score_detail[key]?.applicable === false">N/A</strong>
                    <strong v-else>{{ selectedReview.score_detail[key]?.score ?? 0 }}/{{ selectedReview.score_detail[key]?.max_score ?? 0 }}</strong>
                  </div>
                  <p>{{ scoreReason(key) }}</p>
                </div>
              </section>

              <section class="insight-grid">
                <div class="insight-block">
                  <h4>主要优点</h4>
                  <ul>
                    <li v-for="item in selectedReview.strengths" :key="item">{{ item }}</li>
                  </ul>
                </div>
                <div class="insight-block">
                  <h4>主要问题</h4>
                  <ul>
                    <li v-for="item in selectedReview.weaknesses" :key="item">{{ item }}</li>
                  </ul>
                </div>
                <div class="insight-block">
                  <h4>改进建议</h4>
                  <ul>
                    <li v-for="item in selectedReview.improvement_suggestions" :key="item">{{ item }}</li>
                  </ul>
                </div>
                <div class="insight-block">
                  <h4>数据限制</h4>
                  <ul>
                    <li v-for="item in selectedReview.data_limitations" :key="item">{{ item }}</li>
                  </ul>
                </div>
              </section>

              <div class="tag-row">
                <Tag v-for="tag in selectedReview.mistake_tags" :key="tag" :value="mistakeTagLabel(tag)" class="p-tag--accent" />
              </div>
            </div>
          </section>

          <AgentEvidencePanel
            v-if="selectedReview"
            :metadata="selectedReview.metadata"
            :evidence-summary="selectedReview.evidence_summary"
            :run-trace-summary="selectedReview.run_trace_summary"
          />

          <section v-else class="surface-panel">
            <div class="surface-panel__content">
              <div class="empty-state">请选择一条复盘查看结果</div>
            </div>
          </section>
        </div>
      </section>

      <section class="surface-panel mistake-summary-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">错误模式统计</h3>
              <p class="panel-subtitle">按 mistake_tags 聚合历史复盘。</p>
            </div>
          </div>
          <div v-if="mistakeItems.length" class="mistake-grid">
            <div v-for="item in mistakeItems" :key="item.tag" class="mistake-card">
              <strong>{{ mistakeTagLabel(item.tag) }}</strong>
              <span>{{ item.count }} 次</span>
              <small class="mistake-card__code">{{ item.tag }}</small>
              <small>{{ item.symbols.join(', ') || '--' }}</small>
            </div>
          </div>
          <div v-else class="empty-state">暂无错误模式数据</div>
        </div>
      </section>
      </template>
    </template>
  </section>
</template>

<style scoped>
.trade-review-title {
  margin: 0;
  font-size: 1.55rem;
}

.agent-health {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
  max-width: min(420px, 100%);
}

.review-tab-selector {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.46);
}

.review-tab-option {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
  font-weight: 600;
  cursor: pointer;
}

.review-tab-option input[type='radio'] {
  accent-color: var(--color-accent);
}

.review-tab-option:has(input:checked) {
  color: var(--color-text-primary);
}

.generation-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.review-layout {
  display: grid;
  grid-template-columns: minmax(280px, 0.72fr) minmax(0, 1.28fr);
  gap: var(--space-4);
  align-items: start;
}

.review-result-stack {
  display: grid;
  gap: var(--space-4);
  min-width: 0;
}

.mistake-summary-panel {
  margin-top: var(--space-4);
}

.review-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.field-stack--wide {
  grid-column: 1 / -1;
}

.review-form-actions {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  min-height: 46px;
  max-height: 46px;
  overflow: visible;
}

:deep(.review-generate-button) {
  flex: 0 0 auto;
  width: auto;
  min-width: 180px;
  max-width: 100%;
  height: 44px;
  max-height: 44px;
  min-height: 44px;
  justify-self: start;
  align-self: start;
}

.review-runner-panel {
  margin-top: var(--space-4);
}

.runner-list {
  display: grid;
  gap: 10px;
}

.runner-item {
  padding: 14px 16px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.58);
}

.runner-item__summary {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto;
  gap: 14px;
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
  box-shadow: 0 0 18px rgba(86, 213, 255, 0.42);
}

.runner-item--queued .runner-item__dot,
.runner-item--running .runner-item__dot {
  animation: runner-pulse 1.2s ease-in-out infinite;
}

.runner-item--completed .runner-item__dot {
  background: #58d6a1;
  box-shadow: 0 0 18px rgba(88, 214, 161, 0.34);
}

.runner-item--failed .runner-item__dot {
  background: #ff6b7a;
  box-shadow: 0 0 18px rgba(255, 107, 122, 0.34);
}

.runner-item__main {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.runner-item__main strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runner-item__main span,
.runner-item__meta span {
  color: var(--color-text-secondary);
  font-size: 0.86rem;
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
    opacity: 0.52;
    transform: scale(0.82);
  }

  50% {
    opacity: 1;
    transform: scale(1);
  }
}

.review-list {
  display: grid;
  gap: 10px;
}

.review-list__item {
  display: grid;
  grid-template-columns: 150px 80px minmax(150px, 1fr) 110px;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 14px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.62);
  color: var(--color-text-primary);
  text-align: left;
  cursor: pointer;
}

.review-list__item.is-active,
.review-list__item:hover {
  border-color: rgba(86, 213, 255, 0.34);
  background: rgba(19, 42, 70, 0.82);
}

.review-list__item small {
  grid-column: 1 / -1;
  color: var(--color-text-secondary);
}

.review-layout .review-list__item {
  grid-template-columns: 1fr;
  gap: 6px;
}

.review-list__item--toggle {
  justify-items: center;
  color: var(--color-accent-strong);
  font-weight: 700;
  text-align: center;
}

.mistake-grid,
.score-grid,
.insight-grid {
  display: grid;
  gap: var(--space-3);
}

.mistake-grid {
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
}

.mistake-card,
.score-card,
.insight-block {
  padding: 16px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(129, 160, 207, 0.12);
  background: rgba(10, 18, 32, 0.58);
}

.score-basis {
  margin: 2px 0 0;
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  opacity: 0.8;
}

.score-card--na {
  opacity: 0.5;
}

.score-card--na strong {
  color: var(--color-text-secondary);
  font-weight: 500;
}

.mistake-card {
  display: grid;
  gap: 6px;
}

.mistake-card span {
  color: var(--color-accent-strong);
  font-weight: 700;
}

.mistake-card small {
  color: var(--color-text-secondary);
}

.review-detail-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) max-content;
  gap: var(--space-4);
  align-items: flex-start;
  margin-bottom: var(--space-4);
}

.review-detail-header > div:first-child {
  min-width: 0;
}

.review-detail-header .panel-subtitle {
  overflow-wrap: anywhere;
}

.review-detail-header > [data-pc-name='tag'][data-pc-section='root'] {
  justify-self: end;
}

.review-score {
  margin: 0;
  font-size: 3rem;
  letter-spacing: -0.02em;
}

.review-score span {
  font-size: 1.1rem;
  color: var(--color-text-secondary);
}

.score-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.review-result-stack .score-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.score-card__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.score-card__head span {
  color: var(--color-text-secondary);
}

.score-card p,
.insight-block li {
  color: var(--color-text-secondary);
}

.score-card p {
  margin: 0;
}

.insight-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: var(--space-4);
}

.insight-block h4 {
  margin: 0 0 10px;
}

.insight-block ul {
  display: grid;
  gap: 8px;
  margin: 0;
  padding-left: 18px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  margin-top: var(--space-4);
}

@media (max-width: 1100px) {
  .generation-grid,
  .review-layout,
  .insight-grid {
    grid-template-columns: 1fr;
  }

  .score-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .review-tab-selector {
    flex-direction: column;
    gap: 8px;
  }

  .review-form,
  .score-grid,
  .review-result-stack .score-grid {
    grid-template-columns: 1fr;
  }

  .runner-item {
    grid-template-columns: 12px minmax(0, 1fr);
  }

  .runner-item__meta {
    grid-column: 2;
    justify-content: flex-start;
  }

  .review-detail-header {
    grid-template-columns: 1fr;
  }

  .review-detail-header > [data-pc-name='tag'][data-pc-section='root'] {
    justify-self: start;
  }

  .review-list__item {
    grid-template-columns: 1fr;
  }
}
</style>
