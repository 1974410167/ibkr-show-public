<script setup lang="ts">
import { computed } from 'vue'
import Tag from 'primevue/tag'

import ErrorBlock from '@/components/ErrorBlock.vue'
import FinancialTable from '@/components/FinancialTable.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type {
  MetricComparisonItem,
  SymbolAiAdviceResponse,
  SymbolAnalysisSnapshot,
  SymbolMarketSnapshot,
} from '@/types/symbolAnalysis'

const props = defineProps<{
  state: SymbolAnalysisSnapshot
}>()

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

const latestComparison = computed<MetricComparisonItem[]>(() => props.state.comparison?.latest_metric_comparison ?? [])
const hasAnyResult = computed(() => Boolean(props.state.singleFinancials || props.state.comparison || props.state.loading || props.state.errorMessage))

function formatNumber(value: number, digits = 2): string {
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
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
</script>

<template>
  <section class="symbol-analysis-results">
    <div v-if="!hasAnyResult" class="empty-state">点击上方“标的分析”卡片并运行查询后，这里会展示财报、对比和 AI 判断。</div>

    <LoadingBlock v-if="state.loading" />
    <ErrorBlock v-if="state.errorMessage" :message="state.errorMessage" />

    <section v-if="state.singleFinancials" class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <h2 class="panel-title">{{ state.singleFinancials.symbol }} 最近 {{ state.singleFinancials.period_count }} 个季度</h2>
            <p class="panel-subtitle">币种：{{ state.singleFinancials.currency ?? '--' }} · 数据源：Longbridge financial statements</p>
          </div>
        </div>
        <article v-if="state.singleFinancials.market_snapshot" class="market-snapshot">
          <div class="market-snapshot__head">
            <div>
              <h3>{{ state.singleFinancials.market_snapshot.name ?? state.singleFinancials.symbol }}</h3>
              <span>{{ state.singleFinancials.market_snapshot.valuation_date ?? 'Longbridge 当前数据' }}</span>
            </div>
            <strong>{{ state.singleFinancials.market_snapshot.currency ?? state.singleFinancials.currency ?? '--' }}</strong>
          </div>
          <div class="market-snapshot__grid">
            <div v-for="(label, key) in snapshotLabels" :key="key" class="market-snapshot__item">
              <span>{{ label }}</span>
              <strong>{{ formatSnapshotValue(key, snapshotMetric(state.singleFinancials.market_snapshot, key)) }}</strong>
            </div>
          </div>
          <p v-if="state.singleFinancials.market_snapshot.valuation_summary" class="market-snapshot__summary">
            {{ state.singleFinancials.market_snapshot.valuation_summary }}
          </p>
        </article>
        <FinancialTable :financials="state.singleFinancials" :metric-labels="metricLabels" :format-value="formatValue" :format-change="formatChange" />
      </div>
    </section>

    <template v-if="state.comparison">
      <section class="surface-panel ai-advice-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h2 class="panel-title">AI 加仓/建仓判断</h2>
              <p class="panel-subtitle">{{ state.comparison.left.symbol }} vs {{ state.comparison.right.symbol }}</p>
            </div>
            <div v-if="state.aiAdvice" class="symbol-analysis-tags">
              <Tag :value="recommendationLabel(state.aiAdvice)" :class="recommendationClass(state.aiAdvice.recommendation)" />
              <Tag :value="confidenceLabel(state.aiAdvice.confidence)" class="p-tag--accent" />
            </div>
          </div>

          <LoadingBlock v-if="state.aiAdviceLoading" />
          <ErrorBlock v-else-if="state.aiAdviceError" :message="state.aiAdviceError" />
          <div v-else-if="state.aiAdvice" class="ai-advice-content">
            <p class="ai-advice-summary">{{ state.aiAdvice.summary }}</p>
            <div class="ai-advice-grid">
              <section>
                <h3>关键理由</h3>
                <ul>
                  <li v-for="item in state.aiAdvice.key_reasons" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <h3>主要风险</h3>
                <ul>
                  <li v-for="item in state.aiAdvice.risks" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <h3>加仓/建仓条件</h3>
                <ul>
                  <li v-for="item in state.aiAdvice.add_conditions" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section v-if="state.aiAdvice.data_limitations.length">
                <h3>数据限制</h3>
                <ul>
                  <li v-for="item in state.aiAdvice.data_limitations" :key="item">{{ item }}</li>
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
              <h2 class="panel-title">{{ state.comparison.left.symbol }}</h2>
              <span>{{ state.comparison.left.currency ?? '--' }}</span>
            </div>
            <article v-if="state.comparison.left.market_snapshot" class="market-snapshot market-snapshot--compact">
              <div class="market-snapshot__head">
                <div>
                  <h3>{{ state.comparison.left.market_snapshot.name ?? state.comparison.left.symbol }}</h3>
                  <span>{{ state.comparison.left.market_snapshot.valuation_date ?? 'Longbridge 当前数据' }}</span>
                </div>
              </div>
              <div class="market-snapshot__grid">
                <div v-for="(label, key) in snapshotLabels" :key="key" class="market-snapshot__item">
                  <span>{{ label }}</span>
                  <strong>{{ formatSnapshotValue(key, snapshotMetric(state.comparison.left.market_snapshot, key)) }}</strong>
                </div>
              </div>
            </article>
            <FinancialTable :financials="state.comparison.left" :metric-labels="metricLabels" :format-value="formatValue" :format-change="formatChange" compact />
          </div>
        </article>

        <article class="surface-panel">
          <div class="surface-panel__content">
            <div class="compare-panel-head">
              <h2 class="panel-title">{{ state.comparison.right.symbol }}</h2>
              <span>{{ state.comparison.right.currency ?? '--' }}</span>
            </div>
            <article v-if="state.comparison.right.market_snapshot" class="market-snapshot market-snapshot--compact">
              <div class="market-snapshot__head">
                <div>
                  <h3>{{ state.comparison.right.market_snapshot.name ?? state.comparison.right.symbol }}</h3>
                  <span>{{ state.comparison.right.market_snapshot.valuation_date ?? 'Longbridge 当前数据' }}</span>
                </div>
              </div>
              <div class="market-snapshot__grid">
                <div v-for="(label, key) in snapshotLabels" :key="key" class="market-snapshot__item">
                  <span>{{ label }}</span>
                  <strong>{{ formatSnapshotValue(key, snapshotMetric(state.comparison.right.market_snapshot, key)) }}</strong>
                </div>
              </div>
            </article>
            <FinancialTable :financials="state.comparison.right" :metric-labels="metricLabels" :format-value="formatValue" :format-change="formatChange" compact />
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
  </section>
</template>

<style scoped>
.symbol-analysis-results {
  display: grid;
  gap: var(--space-5);
}

.symbol-analysis-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: flex-end;
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
