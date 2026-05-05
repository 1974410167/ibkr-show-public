<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Paginator from 'primevue/paginator'

import { fetchTradeSummary, fetchTrades } from '@/api/trades'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatCard from '@/components/StatCard.vue'
import TradeTable from '@/components/TradeTable.vue'
import type { TradeItem, TradeListResponse, TradeSummaryResponse } from '@/types/trades'

const state = reactive({
  start_date: '',
  end_date: '',
  symbol: '',
  buy_sell: '',
  page: 1,
  page_size: 20,
})

const tradeResponse = ref<TradeListResponse | null>(null)
const tradeSummary = ref<TradeSummaryResponse | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const sortKey = ref<'proceeds' | 'fifo_pnl_realized' | null>(null)
const sortOrder = ref<'asc' | 'desc'>('desc')

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) {
    return '--'
  }
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

const tradeItems = computed<TradeItem[]>(() => tradeResponse.value?.items ?? [])

function currentSortBy(): 'date_time' | 'proceeds' | 'fifo_pnl_realized' {
  return sortKey.value ?? 'date_time'
}

async function loadTrades(): Promise<void> {
  loading.value = true
  errorMessage.value = ''

  try {
    const filters = {
      start_date: state.start_date,
      end_date: state.end_date,
      symbol: state.symbol.trim().toUpperCase(),
      buy_sell: state.buy_sell,
    }
    const [summaryResponse, listResponse] = await Promise.all([
      fetchTradeSummary(filters),
      fetchTrades({
        ...filters,
        sort_by: currentSortBy(),
        sort_order: sortOrder.value,
        page: state.page,
        page_size: state.page_size,
      }),
    ])
    tradeSummary.value = summaryResponse
    tradeResponse.value = listResponse
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载交易记录失败'
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  state.page = 1
  void loadTrades()
}

function setSide(nextSide: 'BUY' | 'SELL'): void {
  state.buy_sell = state.buy_sell === nextSide ? '' : nextSide
  applyFilters()
}

function setSort(nextKey: 'proceeds' | 'fifo_pnl_realized'): void {
  if (sortKey.value === nextKey) {
    sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortKey.value = nextKey
    sortOrder.value = 'desc'
  }
  state.page = 1
  void loadTrades()
}

function onPageChange(event: { page: number; rows: number }): void {
  state.page = event.page + 1
  state.page_size = event.rows
  void loadTrades()
}

function toneByNumber(value: number | null | undefined): 'positive' | 'negative' | 'neutral' {
  if (!value) {
    return 'neutral'
  }
  return value > 0 ? 'positive' : 'negative'
}

onMounted(() => {
  void loadTrades()
})
</script>

<template>
  <section class="page-section">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <h2 class="panel-title">交易筛选</h2>
            <p class="panel-subtitle">支持按日期、代码和买卖方向筛选，排序直接在表头完成。</p>
          </div>
        </div>

        <form class="trade-filters" @submit.prevent="applyFilters">
          <label class="field-stack">
            <span class="field-stack__label">开始日期</span>
            <InputText v-model="state.start_date" type="date" />
          </label>
          <label class="field-stack">
            <span class="field-stack__label">结束日期</span>
            <InputText v-model="state.end_date" type="date" />
          </label>
          <label class="field-stack">
            <span class="field-stack__label">代码</span>
            <InputText v-model="state.symbol" type="text" placeholder="AAPL" />
          </label>
          <div class="field-stack">
            <div class="trade-side-toggle__label-row">
              <span class="field-stack__label">方向</span>
              <span class="trade-side-toggle__helper">默认全部</span>
            </div>
            <div class="trade-side-toggle">
              <Button
                type="button"
                label="买入"
                class="trade-side-toggle__button"
                :class="{ 'is-active': state.buy_sell === 'BUY' }"
                @click="setSide('BUY')"
              />
              <Button
                type="button"
                label="卖出"
                class="trade-side-toggle__button"
                :class="{ 'is-active': state.buy_sell === 'SELL' }"
                @click="setSide('SELL')"
              />
            </div>
          </div>
          <div class="field-stack field-stack--action">
            <Button label="刷新交易" icon="pi pi-search" class="p-button p-button--accent" type="submit" />
          </div>
        </form>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage" :message="errorMessage" />

    <template v-else>
      <section class="stats-grid stats-grid--summary">
        <StatCard title="成交笔数" :value="String(tradeSummary?.trade_count ?? 0)" icon="pi pi-list" tone="accent" />
        <StatCard title="买入笔数" :value="String(tradeSummary?.buy_count ?? 0)" icon="pi pi-arrow-up" tone="positive" />
        <StatCard title="卖出笔数" :value="String(tradeSummary?.sell_count ?? 0)" icon="pi pi-arrow-down" tone="negative" />
        <StatCard title="交易标的数" :value="String(tradeSummary?.symbols_count ?? 0)" icon="pi pi-hashtag" tone="neutral" />
        <StatCard title="总佣金" :value="formatNumber(tradeSummary?.total_commission ?? null, 4)" icon="pi pi-minus-circle" :tone="toneByNumber(tradeSummary?.total_commission)" />
        <StatCard title="已实现盈亏" :value="formatNumber(tradeSummary?.total_realized_pnl ?? null)" icon="pi pi-chart-line" :tone="toneByNumber(tradeSummary?.total_realized_pnl)" />
        <StatCard title="成交净额" :value="formatNumber(tradeSummary?.total_proceeds ?? null)" icon="pi pi-chart-bar" :tone="toneByNumber(tradeSummary?.total_proceeds)" />
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h2 class="panel-title">交易明细表</h2>
              <p class="panel-subtitle">点击表头可按成交金额和已实现盈亏排序。</p>
            </div>
          </div>
          <template v-if="tradeItems.length > 0">
            <TradeTable
              :items="tradeItems"
              :format-number="formatNumber"
              :sort-key="sortKey"
              :sort-order="sortOrder"
              :on-sort="setSort"
            />
            <Paginator
              :rows="state.page_size"
              :totalRecords="tradeResponse?.pagination.total ?? 0"
              :first="(state.page - 1) * state.page_size"
              :rowsPerPageOptions="[20, 50, 100]"
              @page="onPageChange"
            />
          </template>
          <div v-else class="empty-state">暂无交易数据</div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.trade-filters {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-3);
  align-items: end;
}

.trade-side-toggle {
  display: flex;
  gap: 10px;
}

.trade-side-toggle__label-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.trade-side-toggle__button {
  min-width: 96px;
}

.trade-side-toggle__button.is-active {
  background: linear-gradient(135deg, rgba(60, 146, 255, 0.95), rgba(25, 92, 182, 0.95));
  border-color: rgba(116, 194, 255, 0.75);
  box-shadow: 0 0 0 1px rgba(116, 194, 255, 0.25) inset;
}

.trade-side-toggle__helper {
  font-size: 0.82rem;
  color: var(--color-text-secondary);
}

@media (max-width: 1200px) {
  .trade-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .trade-filters {
    grid-template-columns: 1fr;
  }

  .trade-side-toggle {
    flex-wrap: wrap;
  }
}
</style>
