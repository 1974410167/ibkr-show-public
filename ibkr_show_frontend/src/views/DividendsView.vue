<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Paginator from 'primevue/paginator'

import { fetchDividendSummary, fetchDividends } from '@/api/dividends'
import { ApiError } from '@/api/http'
import DividendTable from '@/components/DividendTable.vue'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatCard from '@/components/StatCard.vue'
import type {
  DividendCurrencySummaryItem,
  DividendItem,
  DividendSummaryResponse,
} from '@/types/dividends'

const router = useRouter()

const state = reactive({
  start_date: '',
  end_date: '',
  currency: '',
  symbol: '',
  page: 1,
  page_size: 20,
})

const dividendResponse = ref<Awaited<ReturnType<typeof fetchDividends>> | null>(null)
const dividendSummary = ref<DividendSummaryResponse | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const sortKey = ref<'date_time' | 'ex_date' | 'amount' | null>(null)
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

const dividendItems = computed<DividendItem[]>(() => dividendResponse.value?.items ?? [])

function currentSortBy(): 'date_time' | 'ex_date' | 'amount' {
  return sortKey.value ?? 'date_time'
}

function currentFilters() {
  return {
    start_date: state.start_date,
    end_date: state.end_date,
    currency: state.currency,
    symbol: state.symbol,
  }
}

async function loadDividends(includeSummary = true): Promise<void> {
  loading.value = true
  errorMessage.value = ''

  try {
    const summaryPromise = includeSummary
      ? fetchDividendSummary(currentFilters())
      : Promise.resolve<DividendSummaryResponse | null>(dividendSummary.value)
    const [summaryResponse, listResponse] = await Promise.all([
      summaryPromise,
      fetchDividends({
        ...currentFilters(),
        sort_by: currentSortBy(),
        sort_order: sortOrder.value,
        page: state.page,
        page_size: state.page_size,
      }),
    ])

    dividendSummary.value = summaryResponse
    dividendResponse.value = listResponse
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      await router.push('/')
      return
    }
    errorMessage.value = error instanceof Error ? error.message : '加载股息记录失败'
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  state.page = 1
  void loadDividends()
}

function setSort(nextKey: 'date_time' | 'ex_date' | 'amount'): void {
  if (sortKey.value === nextKey) {
    sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortKey.value = nextKey
    sortOrder.value = 'desc'
  }
  state.page = 1
  void loadDividends(false)
}

function onPageChange(event: { page: number; rows: number }): void {
  state.page = event.page + 1
  state.page_size = event.rows
  void loadDividends(false)
}

function toneByNumber(value: number | null | undefined): 'positive' | 'negative' | 'neutral' {
  if (!value) {
    return 'neutral'
  }
  return value > 0 ? 'positive' : 'negative'
}

const currencySummaries = computed<DividendCurrencySummaryItem[]>(() => {
  return dividendSummary.value?.by_currency ?? []
})

function currencyLabel(value: string | null): string {
  return value ?? '未知币种'
}

onMounted(() => {
  void loadDividends()
})
</script>

<template>
  <section class="page-section">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <h2 class="panel-title">筛选与排序</h2>
            <p class="panel-subtitle">查看已发放的历史股息、预扣税和 Payment In Lieu 记录。</p>
          </div>
        </div>

        <form class="cash-flow-filters" @submit.prevent="applyFilters">
          <label class="field-stack">
            <span class="field-stack__label">开始日期</span>
            <InputText v-model="state.start_date" type="date" />
          </label>
          <label class="field-stack">
            <span class="field-stack__label">结束日期</span>
            <InputText v-model="state.end_date" type="date" />
          </label>
          <label class="field-stack">
            <span class="field-stack__label">币种</span>
            <InputText v-model="state.currency" type="text" placeholder="USD / CNH / HKD" />
          </label>
          <label class="field-stack">
            <span class="field-stack__label">标的</span>
            <InputText v-model="state.symbol" type="text" placeholder="AAPL / MSFT / SGOV" />
          </label>
          <div class="field-stack field-stack--action">
            <Button label="刷新股息" icon="pi pi-building-columns" class="p-button p-button--accent" type="submit" />
          </div>
        </form>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage" :message="errorMessage" />

    <template v-else>
      <section class="stats-grid stats-grid--summary">
        <StatCard title="记录笔数" :value="String(dividendSummary?.record_count ?? 0)" icon="pi pi-list" tone="accent" />
        <StatCard title="股息入账" :value="formatNumber(dividendSummary?.gross_dividend_amount ?? null)" icon="pi pi-arrow-down-left" tone="positive" />
        <StatCard title="预扣税" :value="formatNumber(dividendSummary?.withholding_tax_amount ?? null)" icon="pi pi-minus-circle" tone="negative" />
        <StatCard title="净到账" :value="formatNumber(dividendSummary?.net_amount ?? null)" icon="pi pi-chart-line" :tone="toneByNumber(dividendSummary?.net_amount)" />
      </section>

      <section v-if="currencySummaries.length > 0" class="currency-summary-list">
        <section v-for="item in currencySummaries" :key="item.currency ?? 'unknown'" class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h2 class="panel-title">{{ currencyLabel(item.currency) }} 股息统计</h2>
                <p class="panel-subtitle">
                  {{ item.record_count }} 笔记录 · 股息 {{ item.dividend_count }} 笔 · 预扣税 {{ item.withholding_tax_count }} 笔
                </p>
              </div>
            </div>

            <section class="stats-grid stats-grid--summary">
              <StatCard title="股息入账" :value="formatNumber(item.gross_dividend_amount)" icon="pi pi-plus-circle" tone="positive" />
              <StatCard title="预扣税" :value="formatNumber(item.withholding_tax_amount)" icon="pi pi-minus-circle" tone="negative" />
              <StatCard title="净到账" :value="formatNumber(item.net_amount)" icon="pi pi-chart-line" :tone="toneByNumber(item.net_amount)" />
            </section>
          </div>
        </section>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h2 class="panel-title">股息明细表</h2>
              <p class="panel-subtitle">按到账时间展示股息、预扣税和 Payment In Lieu 记录，点击表头可排序。</p>
            </div>
          </div>
          <template v-if="dividendItems.length > 0">
            <DividendTable
              :items="dividendItems"
              :format-number="formatNumber"
              :sort-key="sortKey"
              :sort-order="sortOrder"
              :on-sort="setSort"
            />
            <Paginator
              :rows="state.page_size"
              :totalRecords="dividendResponse?.pagination.total ?? 0"
              :first="(state.page - 1) * state.page_size"
              :rowsPerPageOptions="[20, 50, 100]"
              @page="onPageChange"
            />
          </template>
          <div v-else class="empty-state">暂无股息记录</div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.currency-summary-list {
  display: grid;
  gap: var(--space-4);
}

.cash-flow-filters {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-3);
  align-items: end;
}

@media (max-width: 1200px) {
  .cash-flow-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .cash-flow-filters {
    grid-template-columns: 1fr;
  }
}
</style>
