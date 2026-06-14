<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'
import SymbolInput from '@/components/SymbolInput.vue'

import { compareSymbols, fetchSymbolFinancials, generateSymbolAiAdvice } from '@/api/symbolAnalysis'
import ErrorBlock from '@/components/ErrorBlock.vue'
import FinancialTable from '@/components/FinancialTable.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type {
  MetricComparisonItem,
  SymbolAiAdviceResponse,
  SymbolAnalysisSnapshot,
  SymbolAnalysisTask,
  SymbolAnalysisTaskStep,
  SymbolComparisonResponse,
  SymbolFinancialsResponse,
  SymbolMarketSnapshot,
} from '@/types/symbolAnalysis'

withDefaults(defineProps<{
  showResults?: boolean
}>(), {
  showResults: true,
})

const emit = defineEmits<{
  (event: 'activate'): void
  (event: 'state-change', state: SymbolAnalysisSnapshot): void
  (event: 'task-change', task: SymbolAnalysisTask | null): void
}>()

const form = reactive({
  symbol: '',
  left: '',
  right: '',
})

const singleFinancials = ref<SymbolFinancialsResponse | null>(null)
const comparison = ref<SymbolComparisonResponse | null>(null)
const aiAdvice = ref<SymbolAiAdviceResponse | null>(null)
const loading = ref(false)
const aiAdviceLoading = ref(false)
const aiAdviceError = ref('')
const errorMessage = ref('')
const activeTask = ref<SymbolAnalysisTask | null>(null)

const metricLabels: Record<string, string> = {
  revenue: '营收',
  gross_profit: '毛利润',
  gross_margin: '毛利率',
  operating_income: '营业利润',
  operating_margin: '营业利润率',
  net_income: '净利润',
  net_margin: '净利率',
  eps: 'EPS',
  operating_cash_flow: '经营现金流',
  free_cash_flow: '自由现金流',
  cash_and_equivalents: '现金及短投',
  total_debt: '总债务',
  shareholders_equity: '股东权益',
  roe: 'ROE',
}

const ratioMetrics = new Set(['gross_margin', 'operating_margin', 'net_margin', 'roe'])
const percentSnapshotKeys = new Set(['change_percent', 'dividend_yield', 'turnover_rate'])
const snapshotLabels: Record<string, string> = {
  market_cap: '市值',
  last_price: '现价',
  change_percent: '涨跌幅',
  pe_ttm: '当前PE',
  forward_pe: '远期PE',
  pe_3y_median: '3年中位PE',
  pe_industry_median: '行业中位PE',
  pb: 'PB',
  eps_ttm: 'EPS TTM',
  bps: 'BPS',
  turnover_rate: '换手率',
}

const latestComparison = computed<MetricComparisonItem[]>(() => comparison.value?.latest_metric_comparison ?? [])

watch(
  [loading, errorMessage, singleFinancials, comparison, aiAdvice, aiAdviceLoading, aiAdviceError],
  emitState,
  { deep: true, immediate: true },
)

function normalizeInput(value: string): string {
  return value.trim().toUpperCase()
}

function emitState(): void {
  emit('state-change', {
    loading: loading.value,
    errorMessage: errorMessage.value,
    singleFinancials: singleFinancials.value,
    comparison: comparison.value,
    aiAdvice: aiAdvice.value,
    aiAdviceLoading: aiAdviceLoading.value,
    aiAdviceError: aiAdviceError.value,
  })
}

function startLocalTask(label: string, steps: SymbolAnalysisTaskStep[]): void {
  activeTask.value = {
    id: `symbol-analysis-${Date.now()}`,
    label,
    status: 'running',
    stage: steps[0]?.label || '运行标的分析',
    started_at: new Date().toISOString(),
    completed_at: null,
    error_message: null,
    steps,
  }
  emit('task-change', activeTask.value)
}

function updateLocalTask(stepId: string, status: SymbolAnalysisTaskStep['status'], stage?: string): void {
  if (!activeTask.value) return
  const next = {
    ...activeTask.value,
    stage: stage || activeTask.value.stage,
    steps: activeTask.value.steps.map((step) => (step.id === stepId ? { ...step, status } : step)),
  }
  activeTask.value = next
  emit('task-change', next)
}

function finishLocalTask(status: 'completed' | 'failed', errorMessage: string | null = null): void {
  if (!activeTask.value) return
  const next = {
    ...activeTask.value,
    status,
    stage: status === 'completed' ? '标的分析完成' : errorMessage || '标的分析失败',
    completed_at: new Date().toISOString(),
    error_message: errorMessage,
    steps: activeTask.value.steps.map((step) => (
      step.status === 'running' || step.status === 'queued' ? { ...step, status } : step
    )),
  }
  activeTask.value = next
  emit('task-change', next)
}

function formatValue(key: string, value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '--'
  }
  if (ratioMetrics.has(key)) {
    return `${formatNumber(value * 100, 2)}%`
  }
  if (Math.abs(value) >= 1_000_000_000) {
    return `${formatNumber(value / 1_000_000_000, 2)}B`
  }
  if (Math.abs(value) >= 1_000_000) {
    return `${formatNumber(value / 1_000_000, 2)}M`
  }
  return formatNumber(value, key === 'eps' ? 2 : 0)
}

function formatNumber(value: number, digits = 2): string {
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

function formatSnapshotValue(key: string, value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '--'
  }
  if (percentSnapshotKeys.has(key)) {
    return `${formatNumber(value, 2)}%`
  }
  if (key === 'market_cap') {
    return formatValue(key, value)
  }
  return formatNumber(value, key === 'last_price' || key === 'eps_ttm' || key === 'bps' ? 2 : 2)
}

function snapshotMetric(snapshot: SymbolMarketSnapshot, key: string): number | null | undefined {
  const value = snapshot[key as keyof SymbolMarketSnapshot]
  return typeof value === 'number' || value === null || value === undefined ? value : null
}

function formatChange(key: string, value: number | null | undefined, previous: number | null | undefined): string | null {
  if (value === null || value === undefined || previous === null || previous === undefined) {
    return null
  }
  const delta = value - previous
  if (Math.abs(delta) <= 1e-12) {
    return '0.00%'
  }
  const sign = delta > 0 ? '+' : ''
  if (ratioMetrics.has(key)) {
    return `${sign}${formatNumber(delta * 100, 2)}pp`
  }
  if (!previous) {
    return null
  }
  return `${sign}${formatNumber((delta / Math.abs(previous)) * 100, 2)}%`
}

function winnerClass(winner: string, side: 'left' | 'right'): string {
  if (winner === side) {
    return 'is-winner'
  }
  if (winner === 'tie') {
    return 'is-tie'
  }
  return ''
}

function recommendationLabel(advice: SymbolAiAdviceResponse): string {
  if (advice.recommendation === 'left') {
    return `${advice.left_symbol} 更适合加仓/建仓`
  }
  if (advice.recommendation === 'right') {
    return `${advice.right_symbol} 更适合加仓/建仓`
  }
  return '暂不分胜负'
}

function recommendationClass(value: string): string {
  if (value === 'left' || value === 'right') return 'p-tag--positive'
  return 'p-tag--accent'
}

function confidenceLabel(value: string): string {
  const labels: Record<string, string> = {
    high: '高置信',
    medium: '中等置信',
    low: '低置信',
  }
  return labels[value] ?? value
}

async function loadSingle(): Promise<void> {
  emit('activate')
  const symbol = normalizeInput(form.symbol)
  if (!symbol) return
  startLocalTask(`标的财报分析 · ${symbol}`, [
    { id: 'financials', label: '拉取 Longbridge 财报与估值', status: 'running' },
    { id: 'render', label: '整理财报表格与快照', status: 'queued' },
  ])
  loading.value = true
  errorMessage.value = ''
  singleFinancials.value = null
  try {
    singleFinancials.value = await fetchSymbolFinancials(symbol)
    updateLocalTask('financials', 'completed', '整理财报表格与快照')
    updateLocalTask('render', 'completed', '标的分析完成')
    finishLocalTask('completed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载标的财报失败'
    finishLocalTask('failed', errorMessage.value)
  } finally {
    loading.value = false
  }
}

async function loadComparison(): Promise<void> {
  emit('activate')
  const left = normalizeInput(form.left)
  const right = normalizeInput(form.right)
  if (!left || !right) return
  startLocalTask(`标的对比与 AI 判断 · ${left} vs ${right}`, [
    { id: 'comparison', label: '拉取两只标的财报与估值', status: 'running' },
    { id: 'ai_advice', label: '生成 AI 加仓/建仓判断', status: 'queued' },
    { id: 'render', label: '整理对比结果', status: 'queued' },
  ])
  loading.value = true
  errorMessage.value = ''
  aiAdvice.value = null
  aiAdviceError.value = ''
  comparison.value = null
  try {
    comparison.value = await compareSymbols(left, right)
    updateLocalTask('comparison', 'completed', '生成 AI 加仓/建仓判断')
    await loadAiAdvice(left, right)
    updateLocalTask('render', 'completed', '标的分析完成')
    finishLocalTask('completed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载标的对比失败'
    finishLocalTask('failed', errorMessage.value)
  } finally {
    loading.value = false
  }
}

async function loadAiAdvice(left: string, right: string): Promise<void> {
  aiAdviceLoading.value = true
  aiAdviceError.value = ''
  updateLocalTask('ai_advice', 'running', '生成 AI 加仓/建仓判断')
  try {
    aiAdvice.value = await generateSymbolAiAdvice({
      left_symbol: left,
      right_symbol: right,
      question: '基于这两只股票的财报、估值和趋势对比，哪只更适合加仓/建仓？',
      comparison: comparison.value ?? undefined,
    })
    updateLocalTask('ai_advice', 'completed', '整理对比结果')
  } catch (error) {
    aiAdviceError.value = error instanceof Error ? error.message : '生成 AI 建议失败'
    updateLocalTask('ai_advice', 'failed', aiAdviceError.value)
  } finally {
    aiAdviceLoading.value = false
  }
}

</script>

<template>
  <section class="symbol-analysis-page" @click="emit('activate')" @focusin="emit('activate')">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">FUNDAMENTALS</p>
            <h2 class="panel-title symbol-analysis-title">标的分析</h2>
            <p class="panel-subtitle">输入股票代码，查看长桥实际返回的最近季度财报核心指标；选择两只股票后可左右对比。</p>
          </div>
          <div class="symbol-analysis-tags">
            <Tag value="UP TO 8 QUARTERS" class="p-tag--accent" />
            <Tag value="LONGBRIDGE" class="p-tag--positive" />
          </div>
        </div>

        <div class="symbol-analysis-forms">
          <form class="symbol-analysis-form" @submit.prevent="loadSingle">
            <label class="field-stack">
              <span class="field-stack__label">单标的</span>
              <SymbolInput v-model="form.symbol" placeholder="AAPL / TSLA / MSFT" />
            </label>
            <Button label="查看财报" icon="pi pi-chart-bar" class="p-button p-button--accent" type="submit" :disabled="loading" />
          </form>

          <form class="symbol-analysis-form symbol-analysis-form--compare" @submit.prevent="loadComparison">
            <label class="field-stack">
              <span class="field-stack__label">左侧标的</span>
              <SymbolInput v-model="form.left" placeholder="AAPL" />
            </label>
            <label class="field-stack">
              <span class="field-stack__label">右侧标的</span>
              <SymbolInput v-model="form.right" placeholder="MSFT" />
            </label>
            <Button label="对比" icon="pi pi-sliders-h" class="p-button p-button--accent" type="submit" :disabled="loading" />
          </form>
        </div>
      </div>
    </section>

    <template v-if="showResults">
      <LoadingBlock v-if="loading" />
      <ErrorBlock v-if="errorMessage" :message="errorMessage" />

      <section v-if="singleFinancials" class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <h2 class="panel-title">{{ singleFinancials.symbol }} 最近 {{ singleFinancials.period_count }} 个季度</h2>
            <p class="panel-subtitle">币种：{{ singleFinancials.currency ?? '--' }} · 数据源：Longbridge financial statements</p>
          </div>
        </div>
        <article v-if="singleFinancials.market_snapshot" class="market-snapshot">
          <div class="market-snapshot__head">
            <div>
              <h3>{{ singleFinancials.market_snapshot.name ?? singleFinancials.symbol }}</h3>
              <span>{{ singleFinancials.market_snapshot.valuation_date ?? 'Longbridge 当前数据' }}</span>
            </div>
            <strong>{{ singleFinancials.market_snapshot.currency ?? singleFinancials.currency ?? '--' }}</strong>
          </div>
          <div class="market-snapshot__grid">
            <div v-for="(label, key) in snapshotLabels" :key="key" class="market-snapshot__item">
              <span>{{ label }}</span>
              <strong>{{ formatSnapshotValue(key, snapshotMetric(singleFinancials.market_snapshot, key)) }}</strong>
            </div>
          </div>
          <p v-if="singleFinancials.market_snapshot.valuation_summary" class="market-snapshot__summary">
            {{ singleFinancials.market_snapshot.valuation_summary }}
          </p>
        </article>
        <FinancialTable :financials="singleFinancials" :metric-labels="metricLabels" :format-value="formatValue" :format-change="formatChange" />
      </div>
      </section>

      <template v-if="comparison">
      <section class="surface-panel ai-advice-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h2 class="panel-title">AI 加仓/建仓判断</h2>
              <p class="panel-subtitle">{{ comparison.left.symbol }} vs {{ comparison.right.symbol }}</p>
            </div>
            <div v-if="aiAdvice" class="symbol-analysis-tags">
              <Tag :value="recommendationLabel(aiAdvice)" :class="recommendationClass(aiAdvice.recommendation)" />
              <Tag :value="confidenceLabel(aiAdvice.confidence)" class="p-tag--accent" />
            </div>
          </div>

          <LoadingBlock v-if="aiAdviceLoading" />
          <ErrorBlock v-else-if="aiAdviceError" :message="aiAdviceError" />
          <div v-else-if="aiAdvice" class="ai-advice-content">
            <p class="ai-advice-summary">{{ aiAdvice.summary }}</p>
            <div class="ai-advice-grid">
              <section>
                <h3>关键理由</h3>
                <ul>
                  <li v-for="item in aiAdvice.key_reasons" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <h3>主要风险</h3>
                <ul>
                  <li v-for="item in aiAdvice.risks" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <h3>加仓/建仓条件</h3>
                <ul>
                  <li v-for="item in aiAdvice.add_conditions" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section v-if="aiAdvice.data_limitations.length">
                <h3>数据限制</h3>
                <ul>
                  <li v-for="item in aiAdvice.data_limitations" :key="item">{{ item }}</li>
                </ul>
              </section>
            </div>
          </div>
        </div>
      </section>

      <section class="symbol-compare-layout">
        <article class="surface-panel">
          <div class="surface-panel__content">
            <div class="compare-panel-head">
              <h2 class="panel-title">{{ comparison.left.symbol }}</h2>
              <span>{{ comparison.left.currency ?? '--' }}</span>
            </div>
            <article v-if="comparison.left.market_snapshot" class="market-snapshot market-snapshot--compact">
              <div class="market-snapshot__head">
                <div>
                  <h3>{{ comparison.left.market_snapshot.name ?? comparison.left.symbol }}</h3>
                  <span>{{ comparison.left.market_snapshot.valuation_date ?? 'Longbridge 当前数据' }}</span>
                </div>
              </div>
              <div class="market-snapshot__grid">
                <div v-for="(label, key) in snapshotLabels" :key="key" class="market-snapshot__item">
                  <span>{{ label }}</span>
                  <strong>{{ formatSnapshotValue(key, snapshotMetric(comparison.left.market_snapshot, key)) }}</strong>
                </div>
              </div>
            </article>
            <FinancialTable :financials="comparison.left" :metric-labels="metricLabels" :format-value="formatValue" :format-change="formatChange" compact />
          </div>
        </article>

        <article class="surface-panel">
          <div class="surface-panel__content">
            <div class="compare-panel-head">
              <h2 class="panel-title">{{ comparison.right.symbol }}</h2>
              <span>{{ comparison.right.currency ?? '--' }}</span>
            </div>
            <article v-if="comparison.right.market_snapshot" class="market-snapshot market-snapshot--compact">
              <div class="market-snapshot__head">
                <div>
                  <h3>{{ comparison.right.market_snapshot.name ?? comparison.right.symbol }}</h3>
                  <span>{{ comparison.right.market_snapshot.valuation_date ?? 'Longbridge 当前数据' }}</span>
                </div>
              </div>
              <div class="market-snapshot__grid">
                <div v-for="(label, key) in snapshotLabels" :key="key" class="market-snapshot__item">
                  <span>{{ label }}</span>
                  <strong>{{ formatSnapshotValue(key, snapshotMetric(comparison.right.market_snapshot, key)) }}</strong>
                </div>
              </div>
            </article>
            <FinancialTable :financials="comparison.right" :metric-labels="metricLabels" :format-value="formatValue" :format-change="formatChange" compact />
          </div>
        </article>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h2 class="panel-title">最新季度核心指标对比</h2>
              <p class="panel-subtitle">绿色高亮代表该指标当前更优；总债务按更低更优处理。</p>
            </div>
          </div>
          <div class="metric-comparison-grid">
            <div v-for="item in latestComparison" :key="item.key" class="metric-comparison-row">
              <span>{{ item.label }}</span>
              <strong :class="winnerClass(item.winner, 'left')">{{ formatValue(item.key, item.left_value) }}</strong>
              <strong :class="winnerClass(item.winner, 'right')">{{ formatValue(item.key, item.right_value) }}</strong>
            </div>
          </div>
        </div>
      </section>
      </template>
    </template>
  </section>
</template>

<style scoped>
.symbol-analysis-page {
  display: grid;
  gap: var(--space-5);
}

.symbol-analysis-title {
  font-size: 1.45rem;
}

.symbol-analysis-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: flex-end;
}

.symbol-analysis-forms {
  display: grid;
  gap: var(--space-4);
}

.symbol-analysis-form {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto;
  gap: var(--space-3);
  align-items: end;
}

.symbol-analysis-form--compare {
  grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) auto;
}

.symbol-compare-layout {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.compare-panel-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: baseline;
  margin-bottom: var(--space-4);
}

.compare-panel-head span {
  color: var(--color-text-secondary);
}

.market-snapshot {
  margin-bottom: var(--space-4);
  padding: 16px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: var(--radius-md);
  background: rgba(15, 31, 52, 0.52);
}

.market-snapshot__head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.market-snapshot__head h3 {
  margin: 0;
  font-size: 1rem;
}

.market-snapshot__head span,
.market-snapshot__item span,
.market-snapshot__summary {
  color: var(--color-text-secondary);
}

.market-snapshot__grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(112px, 1fr));
  gap: 10px;
}

.market-snapshot__item {
  min-height: 74px;
  display: grid;
  align-content: center;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: var(--radius-sm);
  background: rgba(9, 20, 36, 0.42);
}

.market-snapshot__item strong {
  font-size: 1rem;
  line-height: 1.2;
}

.market-snapshot__summary {
  margin: var(--space-3) 0 0;
}

.market-snapshot--compact .market-snapshot__grid {
  grid-template-columns: repeat(2, minmax(112px, 1fr));
}

.metric-comparison-grid {
  display: grid;
  gap: 8px;
}

.metric-comparison-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(110px, 0.7fr) minmax(110px, 0.7fr);
  gap: var(--space-3);
  align-items: center;
  padding: 12px 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: var(--radius-md);
  background: rgba(15, 31, 52, 0.52);
}

.metric-comparison-row strong {
  text-align: right;
}

.ai-advice-panel {
  border-color: rgba(34, 211, 238, 0.22);
}

.ai-advice-content {
  display: grid;
  gap: var(--space-4);
}

.ai-advice-summary {
  margin: 0;
  color: var(--color-text-primary);
  line-height: 1.7;
}

.ai-advice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.ai-advice-grid section {
  min-height: 140px;
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: var(--radius-md);
  background: rgba(15, 31, 52, 0.52);
}

.ai-advice-grid h3 {
  margin: 0 0 var(--space-3);
  font-size: 0.95rem;
}

.ai-advice-grid ul {
  margin: 0;
  padding-left: 18px;
  color: var(--color-text-secondary);
  line-height: 1.65;
}

.is-winner {
  color: var(--color-positive);
}

.is-tie {
  color: var(--color-accent-strong);
}

@media (max-width: 860px) {
  .symbol-analysis-form,
  .symbol-analysis-form--compare,
  .symbol-compare-layout,
  .ai-advice-grid,
  .market-snapshot__grid,
  .market-snapshot--compact .market-snapshot__grid {
    grid-template-columns: 1fr;
  }

  .metric-comparison-row {
    grid-template-columns: 1fr;
  }

  .metric-comparison-row strong {
    text-align: left;
  }
}
</style>
