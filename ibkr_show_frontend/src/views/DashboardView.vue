<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { fetchEquityCurve } from '@/api/charts'
import { useAccountOverviewData } from '@/composables/accountOverview'
import EquityCurveSimple from '@/components/EquityCurveSimple.vue'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import PerformanceCalendar from '@/components/PerformanceCalendar.vue'
import StatCard from '@/components/StatCard.vue'
import type { EquityCurvePoint } from '@/types/charts'
import { buildDashboardStatCards, formatMetricNumber as formatNumber } from '@/views/dashboardMetrics'
import {
  buildEquityCurveRangeParams,
  EQUITY_CURVE_RANGE_OPTIONS,
  type EquityCurveRangeKey,
} from '@/views/equityCurveRange'

const { overview, ensureLoaded } = useAccountOverviewData()
const curveItems = ref<EquityCurvePoint[]>([])
const pageLoading = ref(true)
const pageErrorMessage = ref('')
const curveLoading = ref(false)
const curveErrorMessage = ref('')
const selectedRange = ref<EquityCurveRangeKey>('ytd')
let refreshTimer: number | null = null

const statCards = computed(() => {
  if (!overview.value) {
    return []
  }

  return buildDashboardStatCards(overview.value)
})

async function loadDashboard(): Promise<void> {
  pageLoading.value = true
  pageErrorMessage.value = ''

  try {
    await ensureLoaded()
    await loadCurveData(false)
  } catch (error) {
    pageErrorMessage.value = error instanceof Error ? error.message : '加载总览失败'
  } finally {
    pageLoading.value = false
  }
}

async function loadCurveData(showLoading: boolean, forceOverviewRefresh = false): Promise<void> {
  if (showLoading) {
    curveLoading.value = true
  }
  curveErrorMessage.value = ''
  try {
    if (forceOverviewRefresh) {
      await ensureLoaded(true)
    } else if (!overview.value) {
      await ensureLoaded()
    }
    const curveResponse = await fetchEquityCurve(
      buildEquityCurveRangeParams(overview.value?.report_date, selectedRange.value),
    )
    curveItems.value = curveResponse.items
  } catch (error) {
    curveErrorMessage.value = error instanceof Error ? error.message : '加载权益曲线失败'
    if (curveItems.value.length === 0) {
      throw error
    }
  } finally {
    if (showLoading) {
      curveLoading.value = false
    }
  }
}

function setCurveRange(nextRange: EquityCurveRangeKey): void {
  if (selectedRange.value === nextRange) {
    return
  }
  selectedRange.value = nextRange
  void loadCurveData(true)
}

onMounted(() => {
  void loadDashboard()
  refreshTimer = window.setInterval(() => {
    void loadCurveData(false, true)
  }, 30000)
})

onUnmounted(() => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
  }
})
</script>

<template>
  <section class="page-section">
    <LoadingBlock v-if="pageLoading" />
    <ErrorBlock v-else-if="pageErrorMessage" :message="pageErrorMessage" />

    <template v-else>
      <section class="surface-panel dashboard-metrics-panel">
        <div class="surface-panel__content">
          <section class="stats-grid dashboard-metrics-grid">
            <StatCard
              v-for="card in statCards"
              :key="card.title"
              :title="card.title"
              :value="card.value"
              :helper="card.helper"
              :icon="card.icon"
              :tone="card.tone"
              :delta-amount="card.deltaAmount"
              :delta-percent="card.deltaPercent"
              :delta-tone="card.deltaTone"
            />
          </section>
        </div>
      </section>

      <EquityCurveSimple
        :items="curveItems"
        :loading="curveLoading"
        :error-message="curveErrorMessage"
        :format-number="formatNumber"
        :range-options="EQUITY_CURVE_RANGE_OPTIONS"
        :selected-range="selectedRange"
        @select-range="setCurveRange"
      />
      <PerformanceCalendar :latest-report-date="overview?.report_date ?? null" />
    </template>
  </section>
</template>

<style scoped>
.dashboard-metrics-panel {
  margin-bottom: var(--space-5);
}

.dashboard-metrics-grid {
  margin-top: 0;
}
</style>
