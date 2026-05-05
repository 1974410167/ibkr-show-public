<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Card from 'primevue/card'
import Tag from 'primevue/tag'

import { fetchPerformanceCalendar } from '@/api/charts'
import type {
  PerformanceCalendarItem,
  PerformanceCalendarResponse,
  PerformanceCalendarSummary,
  PerformanceCalendarView,
} from '@/types/charts'

type CalendarCell = {
  key: string
  label: string | null
  item: PerformanceCalendarItem | null
  isCurrentMonth: boolean
}

const props = defineProps<{
  latestReportDate: string | null
}>()

const weekdayLabels = ['一', '二', '三', '四', '五', '六', '日']
const viewOptions: Array<{ key: PerformanceCalendarView; label: string }> = [
  { key: 'month', label: '月视图' },
  { key: 'year', label: '年视图' },
  { key: 'all-years', label: '年度汇总' },
]

const activeView = ref<PerformanceCalendarView>('month')
const response = ref<PerformanceCalendarResponse | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const selectedMonthAnchor = ref('')
const selectedYearAnchor = ref('')
const selectedMonthYear = ref('')
const selectedMonthNumber = ref('')

const anchorLabel = computed(() => {
  const payload = response.value
  if (!payload) {
    return '--'
  }
  if (payload.view === 'month') {
    const [year, month] = payload.anchor.split('-')
    return `${year}年${Number(month)}月`
  }
  if (payload.view === 'year') {
    return `${payload.anchor}年`
  }
  return '全部年份'
})

const periodLabel = computed(() => {
  if (activeView.value === 'month') {
    return '交易日'
  }
  if (activeView.value === 'year') {
    return '月份'
  }
  return '年份'
})

const summary = computed<PerformanceCalendarSummary>(() => {
  return (
    response.value?.summary ?? {
      positive_periods: 0,
      negative_periods: 0,
      total_pnl: null,
      periods_with_data: 0,
    }
  )
})

const monthCells = computed<CalendarCell[]>(() => {
  const payload = response.value
  if (!payload || payload.view !== 'month') {
    return []
  }

  const [yearText, monthText] = payload.anchor.split('-')
  const year = Number(yearText)
  const month = Number(monthText)
  const firstDay = new Date(Date.UTC(year, month - 1, 1))
  const leadingPadding = (firstDay.getUTCDay() + 6) % 7
  const cells: CalendarCell[] = []

  for (let index = 0; index < leadingPadding; index += 1) {
    cells.push({
      key: `leading-${index}`,
      label: null,
      item: null,
      isCurrentMonth: false,
    })
  }

  for (const item of payload.items) {
    cells.push({
      key: item.period_key,
      label: item.label,
      item,
      isCurrentMonth: true,
    })
  }

  const trailingPadding = (7 - (cells.length % 7)) % 7
  for (let index = 0; index < trailingPadding; index += 1) {
    cells.push({
      key: `trailing-${index}`,
      label: null,
      item: null,
      isCurrentMonth: false,
    })
  }

  return cells
})

const aggregatedGridItems = computed(() => {
  const payload = response.value
  if (!payload || payload.view === 'month') {
    return []
  }
  return payload.items
})

const availableYearOptions = computed(() => {
  const payload = response.value
  if (!payload || payload.view === 'all-years' || !payload.earliest_anchor) {
    return [] as string[]
  }
  const earliestYear = Number(payload.earliest_anchor.slice(0, 4))
  const latestYear = Number(payload.latest_anchor.slice(0, 4))
  const years: string[] = []
  for (let year = earliestYear; year <= latestYear; year += 1) {
    years.push(String(year))
  }
  return years
})

const availableMonthNumbers = computed(() => {
  const payload = response.value
  if (!payload || payload.view !== 'month' || !selectedMonthYear.value) {
    return [] as string[]
  }

  const earliestAnchor = payload.earliest_anchor ?? payload.anchor
  const [earliestYearText, earliestMonthText] = earliestAnchor.split('-')
  const [latestYearText, latestMonthText] = payload.latest_anchor.split('-')
  const year = Number(selectedMonthYear.value)
  const earliestYear = Number(earliestYearText)
  const latestYear = Number(latestYearText)

  const startMonth = year === earliestYear ? Number(earliestMonthText) : 1
  const endMonth = year === latestYear ? Number(latestMonthText) : 12
  const months: string[] = []
  for (let month = startMonth; month <= endMonth; month += 1) {
    months.push(String(month).padStart(2, '0'))
  }
  return months
})

function normalizeNumericValue(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) {
    return null
  }
  return value
}

function toneByValue(value: number | null): 'positive' | 'negative' | 'neutral' {
  value = normalizeNumericValue(value)
  if (value === null || value === 0) {
    return 'neutral'
  }
  return value > 0 ? 'positive' : 'negative'
}

function isFlatValue(value: number | null): boolean {
  value = normalizeNumericValue(value)
  return value === 0
}

function formatSignedInteger(value: number | null): string {
  value = normalizeNumericValue(value)
  if (value === null) {
    return '--'
  }
  if (value === 0) {
    return '无变化'
  }
  const rounded = Math.round(value)
  return `${rounded > 0 ? '+' : ''}${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(rounded)}`
}

function formatSignedPercent(value: number | null): string {
  value = normalizeNumericValue(value)
  if (value === null || value === 0) {
    return ''
  }
  return `${value > 0 ? '+' : ''}${new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)}%`
}

function formatSummaryAmount(value: number | null): string {
  value = normalizeNumericValue(value)
  if (value === null) {
    return '--'
  }
  return `${value > 0 ? '+' : ''}${new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)}`
}

function buildDefaultAnchor(view: PerformanceCalendarView, latestReportDate: string | null): string | undefined {
  if (!latestReportDate || view === 'all-years') {
    return undefined
  }
  return view === 'month' ? latestReportDate.slice(0, 7) : latestReportDate.slice(0, 4)
}

async function loadCalendar(showLoading = true, nextAnchor?: string): Promise<void> {
  if (!props.latestReportDate) {
    response.value = null
    return
  }

  if (showLoading) {
    loading.value = true
  }
  errorMessage.value = ''

  try {
    response.value = await fetchPerformanceCalendar({
      view: activeView.value,
      anchor: nextAnchor ?? response.value?.anchor ?? buildDefaultAnchor(activeView.value, props.latestReportDate),
    })
    if (response.value.view === 'month') {
      selectedMonthAnchor.value = response.value.anchor
      selectedMonthYear.value = response.value.anchor.slice(0, 4)
      selectedMonthNumber.value = response.value.anchor.slice(5, 7)
    } else if (response.value.view === 'year') {
      selectedYearAnchor.value = response.value.anchor
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载盈亏日历失败'
  } finally {
    if (showLoading) {
      loading.value = false
    }
  }
}

function switchView(nextView: PerformanceCalendarView): void {
  if (activeView.value === nextView) {
    return
  }
  activeView.value = nextView
  void loadCalendar(true, buildDefaultAnchor(nextView, props.latestReportDate))
}

function jumpAnchor(direction: 'previous' | 'next'): void {
  const payload = response.value
  if (!payload) {
    return
  }
  const nextAnchor = direction === 'previous' ? payload.previous_anchor : payload.next_anchor
  if (!nextAnchor) {
    return
  }
  void loadCalendar(true, nextAnchor)
}

function applyMonthAnchorSelection(): void {
  if (!selectedMonthYear.value || !selectedMonthNumber.value) {
    return
  }
  const nextAnchor = `${selectedMonthYear.value}-${selectedMonthNumber.value}`
  if (!nextAnchor || response.value?.anchor === nextAnchor) {
    return
  }
  selectedMonthAnchor.value = nextAnchor
  void loadCalendar(true, nextAnchor)
}

function handleMonthYearChange(event: Event): void {
  selectedMonthYear.value = (event.target as HTMLSelectElement).value
  const monthOptions = availableMonthNumbers.value
  if (!monthOptions.includes(selectedMonthNumber.value)) {
    selectedMonthNumber.value = monthOptions[0] ?? ''
  }
  applyMonthAnchorSelection()
}

function handleMonthNumberChange(event: Event): void {
  selectedMonthNumber.value = (event.target as HTMLSelectElement).value
  applyMonthAnchorSelection()
}

function handleYearAnchorChange(event: Event): void {
  const nextAnchor = (event.target as HTMLSelectElement).value.trim()
  if (!nextAnchor || response.value?.anchor === nextAnchor) {
    return
  }
  selectedYearAnchor.value = nextAnchor
  void loadCalendar(true, nextAnchor)
}

watch(
  () => props.latestReportDate,
  () => {
    if (!props.latestReportDate) {
      response.value = null
      return
    }
    void loadCalendar(
      response.value === null,
      response.value?.view === activeView.value
        ? response.value.anchor
        : buildDefaultAnchor(activeView.value, props.latestReportDate),
    )
  },
  { immediate: true },
)
</script>

<template>
  <Card class="surface-panel calendar-panel">
    <template #content>
      <div class="surface-panel__content">
        <div class="calendar-panel__header">
          <div>
            <p class="eyebrow">Calendar</p>
            <h2 class="panel-title calendar-panel__title">盈亏日历</h2>
            <p class="panel-subtitle calendar-panel__subtitle">
              月视图看每日盈亏，年视图看每月盈亏，年度汇总看每年盈亏；金额口径优先采用 IBKR CNAV 的当日 MTM。
            </p>
          </div>
          <div class="calendar-panel__tags">
            <Tag class="p-tag p-tag--accent" :value="anchorLabel" />
            <Tag class="p-tag" :value="`${summary.periods_with_data} 个有效${periodLabel}`" />
            <Tag class="p-tag" :value="`${periodLabel}内 ${formatSummaryAmount(summary.total_pnl)}`" />
          </div>
        </div>

        <div class="calendar-toolbar">
          <div class="calendar-view-switcher" aria-label="Performance calendar views">
            <button
              v-for="option in viewOptions"
              :key="option.key"
              type="button"
              class="calendar-view-button"
              :class="{ 'calendar-view-button--active': activeView === option.key }"
              @click="switchView(option.key)"
            >
              {{ option.label }}
            </button>
          </div>

          <div v-if="response && activeView !== 'all-years'" class="calendar-toolbar__controls">
            <label v-if="activeView === 'month'" class="calendar-picker">
              <span class="calendar-picker__label">选择月份</span>
              <div class="calendar-picker__row">
                <select
                  :value="selectedMonthYear"
                  class="calendar-picker__input calendar-picker__select"
                  :disabled="loading"
                  @change="handleMonthYearChange"
                >
                  <option v-for="year in availableYearOptions" :key="year" :value="year">{{ year }}年</option>
                </select>
                <select
                  :value="selectedMonthNumber"
                  class="calendar-picker__input calendar-picker__select"
                  :disabled="loading"
                  @change="handleMonthNumberChange"
                >
                  <option v-for="month in availableMonthNumbers" :key="month" :value="month">{{ Number(month) }}月</option>
                </select>
              </div>
            </label>

            <label v-else-if="activeView === 'year'" class="calendar-picker">
              <span class="calendar-picker__label">选择年份</span>
              <select
                :value="selectedYearAnchor"
                class="calendar-picker__input calendar-picker__select calendar-picker__input--year"
                :disabled="loading"
                @change="handleYearAnchorChange"
              >
                <option v-for="year in availableYearOptions" :key="year" :value="year">{{ year }}年</option>
              </select>
            </label>

            <div class="calendar-navigation">
            <button
              type="button"
              class="calendar-nav-button"
              :disabled="!response.previous_anchor || loading"
              @click="jumpAnchor('previous')"
            >
              上一{{ activeView === 'month' ? '月' : '年' }}
            </button>
            <button
              type="button"
              class="calendar-nav-button"
              :disabled="!response.next_anchor || loading"
              @click="jumpAnchor('next')"
            >
              下一{{ activeView === 'month' ? '月' : '年' }}
            </button>
            </div>
          </div>
        </div>

        <div v-if="loading" class="calendar-loading">正在更新盈亏日历…</div>
        <div v-else-if="errorMessage" class="empty-state">{{ errorMessage }}</div>
        <div v-else-if="!response" class="empty-state">暂无日历数据</div>
        <div v-else class="calendar-panel__body">
          <div class="calendar-summary">
            <div class="calendar-summary__item">
              <span>正收益{{ periodLabel }}</span>
              <strong class="metric-positive">{{ summary.positive_periods }}</strong>
            </div>
            <div class="calendar-summary__item">
              <span>负收益{{ periodLabel }}</span>
              <strong class="metric-negative">{{ summary.negative_periods }}</strong>
            </div>
            <div class="calendar-summary__item">
              <span>净变化</span>
              <strong :class="toneByValue(summary.total_pnl) === 'positive' ? 'metric-positive' : toneByValue(summary.total_pnl) === 'negative' ? 'metric-negative' : ''">
                {{ formatSummaryAmount(summary.total_pnl) }}
              </strong>
            </div>
          </div>

          <div v-if="activeView === 'month'" class="calendar-grid" aria-label="Monthly performance calendar">
            <div v-for="label in weekdayLabels" :key="label" class="calendar-grid__weekday">{{ label }}</div>

            <article
              v-for="cell in monthCells"
              :key="cell.key"
              class="calendar-cell"
              :class="{
                'calendar-cell--muted': !cell.isCurrentMonth,
                'calendar-cell--positive': toneByValue(cell.item?.pnl ?? null) === 'positive',
                'calendar-cell--negative': toneByValue(cell.item?.pnl ?? null) === 'negative',
              }"
            >
              <template v-if="cell.isCurrentMonth && cell.item">
                <div class="calendar-cell__day">{{ cell.label }}</div>
                <div class="calendar-cell__amount" :class="{ 'calendar-cell__amount--flat': isFlatValue(cell.item.pnl), 'calendar-cell__amount--empty': normalizeNumericValue(cell.item.pnl) === null }">
                  {{ formatSignedInteger(cell.item.pnl) }}
                </div>
                <div class="calendar-cell__meta" :class="{ 'calendar-cell__meta--empty': normalizeNumericValue(cell.item.twr) === null }">
                  {{ formatSignedPercent(cell.item.twr) || '无数据' }}
                </div>
              </template>
            </article>
          </div>

          <div v-else class="aggregate-grid" :class="{ 'aggregate-grid--years': activeView === 'all-years' }">
            <article
              v-for="item in aggregatedGridItems"
              :key="item.period_key"
              class="aggregate-card"
              :class="{
                'aggregate-card--positive': toneByValue(item.pnl) === 'positive',
                'aggregate-card--negative': toneByValue(item.pnl) === 'negative',
              }"
            >
              <div class="aggregate-card__label">{{ item.label }}</div>
              <div class="aggregate-card__amount" :class="{ 'aggregate-card__amount--flat': isFlatValue(item.pnl), 'aggregate-card__amount--empty': normalizeNumericValue(item.pnl) === null }">
                {{ formatSignedInteger(item.pnl) }}
              </div>
              <div class="aggregate-card__meta" :class="{ 'aggregate-card__meta--empty': normalizeNumericValue(item.twr) === null }">
                {{ formatSignedPercent(item.twr) || '无数据' }}
              </div>
            </article>
          </div>
        </div>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.calendar-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.calendar-panel__title {
  font-size: 1.4rem;
}

.calendar-panel__subtitle {
  max-width: 48rem;
}

.calendar-panel__tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.calendar-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.calendar-view-switcher,
.calendar-navigation {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.calendar-toolbar__controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.calendar-picker {
  display: grid;
  gap: 6px;
}

.calendar-picker__row {
  display: flex;
  gap: 8px;
}

.calendar-picker__label {
  color: var(--color-text-secondary);
  font-size: 0.78rem;
}

.calendar-picker__input {
  min-width: 148px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  background: rgba(15, 26, 45, 0.72);
  color: var(--color-text-primary);
  border-radius: 14px;
  padding: 8px 12px;
  outline: none;
}

.calendar-picker__select {
  appearance: none;
}

.calendar-picker__input--year {
  min-width: 110px;
}

.calendar-view-button,
.calendar-nav-button {
  border: 1px solid rgba(129, 160, 207, 0.12);
  background: rgba(15, 26, 45, 0.72);
  color: var(--color-text-secondary);
  border-radius: 999px;
  padding: 8px 14px;
  cursor: pointer;
  transition:
    border-color 160ms ease,
    background-color 160ms ease,
    color 160ms ease,
    transform 160ms ease;
}

.calendar-view-button:hover,
.calendar-nav-button:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(86, 213, 255, 0.24);
  color: var(--color-text-primary);
}

.calendar-view-button--active {
  border-color: rgba(86, 213, 255, 0.28);
  background: rgba(26, 66, 122, 0.88);
  color: #eaf5ff;
}

.calendar-nav-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.calendar-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  border-radius: 22px;
  border: 1px solid rgba(86, 213, 255, 0.14);
  background: rgba(8, 15, 28, 0.5);
  color: var(--color-text-primary);
  font-weight: 600;
}

.calendar-panel__body {
  display: grid;
  gap: var(--space-4);
}

.calendar-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.calendar-summary__item {
  display: grid;
  gap: 6px;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  background: rgba(15, 26, 45, 0.66);
}

.calendar-summary__item span {
  color: var(--color-text-secondary);
  font-size: 0.84rem;
}

.calendar-summary__item strong {
  font-size: 1.12rem;
  letter-spacing: -0.03em;
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 10px;
}

.calendar-grid__weekday {
  padding: 0 6px 4px;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  font-weight: 600;
  text-align: center;
}

.calendar-cell,
.aggregate-card {
  min-height: 136px;
  padding: 16px;
  border-radius: 22px;
  border: 1px solid rgba(129, 160, 207, 0.1);
  background: linear-gradient(180deg, rgba(11, 20, 37, 0.94) 0%, rgba(8, 14, 28, 0.94) 100%);
  display: grid;
  align-content: space-between;
  gap: 10px;
}

.calendar-cell--muted {
  opacity: 0.3;
}

.calendar-cell--positive,
.aggregate-card--positive {
  border-color: rgba(54, 208, 165, 0.4);
  background:
    radial-gradient(circle at 78% 20%, rgba(37, 211, 102, 0.18), transparent 42%),
    linear-gradient(180deg, rgba(8, 43, 40, 0.88) 0%, rgba(6, 20, 26, 0.92) 100%);
}

.calendar-cell--negative,
.aggregate-card--negative {
  border-color: rgba(255, 104, 135, 0.38);
  background:
    radial-gradient(circle at 18% 16%, rgba(255, 87, 120, 0.16), transparent 40%),
    linear-gradient(180deg, rgba(56, 16, 28, 0.86) 0%, rgba(23, 10, 18, 0.94) 100%);
}

.calendar-cell__day,
.aggregate-card__label {
  color: #b9c8e7;
  font-size: 1.08rem;
  font-weight: 700;
}

.calendar-cell__amount,
.aggregate-card__amount {
  color: #ebf5ff;
  font-size: 1.95rem;
  font-weight: 700;
  letter-spacing: -0.06em;
}

.calendar-cell__amount--flat,
.aggregate-card__amount--flat {
  font-size: 1.22rem;
  letter-spacing: 0;
}

.calendar-cell__amount--empty,
.aggregate-card__amount--empty {
  font-size: 1.05rem;
  letter-spacing: 0;
  color: #8fa2c3;
}

.calendar-cell__meta,
.aggregate-card__meta {
  color: #c6d7f2;
  font-size: 0.96rem;
}

.calendar-cell__meta--empty,
.aggregate-card__meta--empty {
  color: #7f92b2;
  font-size: 0.82rem;
}

.aggregate-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.aggregate-grid--years {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

@media (max-width: 1100px) {
  .calendar-summary {
    grid-template-columns: 1fr;
  }

  .aggregate-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .calendar-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .calendar-grid__weekday {
    display: none;
  }

  .aggregate-grid {
    grid-template-columns: 1fr;
  }

  .calendar-cell,
  .aggregate-card {
    min-height: 112px;
  }
}
</style>
