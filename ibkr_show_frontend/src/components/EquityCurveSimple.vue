<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import Card from 'primevue/card'
import Tag from 'primevue/tag'
import { use, init, graphic, format, type ComposeOption, type EChartsType } from 'echarts/core'
import { LineChart, type LineSeriesOption } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  type DataZoomComponentOption,
  type GridComponentOption,
  type LegendComponentOption,
  type TooltipComponentOption,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import type { EquityCurvePoint } from '@/types/charts'
import type { EquityCurveRangeKey, EquityCurveRangeOption } from '@/views/equityCurveRange'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])

type CurveChartOption = ComposeOption<
  | LineSeriesOption
  | GridComponentOption
  | TooltipComponentOption
  | LegendComponentOption
  | DataZoomComponentOption
>

const props = defineProps<{
  items: EquityCurvePoint[]
  loading: boolean
  errorMessage: string
  formatNumber: (value: number | null, digits?: number) => string
  rangeOptions: EquityCurveRangeOption[]
  selectedRange: EquityCurveRangeKey
}>()

const emit = defineEmits<{
  selectRange: [range: EquityCurveRangeKey]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const chartInstance = shallowRef<EChartsType | null>(null)
const activeSeriesKey = ref<'total_equity' | 'total_pnl' | 'net_cost' | 'realized_pnl' | null>(null)
let resizeObserver: ResizeObserver | null = null

const latestPoint = computed(() => props.items[props.items.length - 1] ?? null)
const firstPoint = computed(() => props.items[0] ?? null)

const seriesControls = computed(() => [
  {
    key: 'total_equity' as const,
    label: '账户权益',
    helper: latestPoint.value ? `最新 ${props.formatNumber(latestPoint.value.total_equity, 2)}` : '最新 --',
    color: '#56d5ff',
  },
  {
    key: 'total_pnl' as const,
    label: '净收益',
    helper: latestPoint.value ? `最新 ${props.formatNumber(latestPoint.value.total_pnl, 2)}` : '最新 --',
    color: '#b7e11d',
  },
  {
    key: 'net_cost' as const,
    label: '净成本',
    helper: latestPoint.value ? `最新 ${props.formatNumber(latestPoint.value.net_cost, 2)}` : '最新 --',
    color: '#ffb454',
  },
  {
    key: 'realized_pnl' as const,
    label: '已实现盈亏',
    helper: latestPoint.value ? `最新 ${props.formatNumber(latestPoint.value.realized_pnl, 2)}` : '最新 --',
    color: '#8b7cff',
  },
])

const historyTag = computed(() => {
  if (!firstPoint.value || !latestPoint.value) {
    return '暂无历史'
  }
  return `${firstPoint.value.report_date} - ${latestPoint.value.report_date}`
})

const pointCountTag = computed(() => `${props.items.length} 个日点`)

function formatAxisValue(value: number): string {
  const absolute = Math.abs(value)
  if (absolute >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`
  }
  if (absolute >= 1_000) {
    return `${(value / 1_000).toFixed(0)}K`
  }
  return value.toFixed(0)
}

function isSeriesActive(key: 'total_equity' | 'total_pnl' | 'net_cost' | 'realized_pnl'): boolean {
  return activeSeriesKey.value === null || activeSeriesKey.value === key
}

function seriesLineStyle(
  key: 'total_equity' | 'total_pnl' | 'net_cost' | 'realized_pnl',
  baseWidth: number,
  color: string,
): { width: number; color: string; opacity: number } {
  const active = isSeriesActive(key)
  return {
    width: active ? baseWidth + 1 : Math.max(baseWidth - 0.5, 1.5),
    color,
    opacity: active ? 1 : 0.24,
  }
}

function seriesAreaOpacity(key: 'total_equity' | 'total_pnl' | 'net_cost' | 'realized_pnl', activeOpacity: number): number {
  return isSeriesActive(key) ? activeOpacity : 0.03
}

function toggleSeriesFocus(key: 'total_equity' | 'total_pnl' | 'net_cost' | 'realized_pnl'): void {
  activeSeriesKey.value = activeSeriesKey.value === key ? null : key
}

function selectRange(range: EquityCurveRangeKey): void {
  emit('selectRange', range)
}

function buildSeriesData(field: 'total_equity' | 'total_pnl' | 'net_cost' | 'realized_pnl'): Array<[string, number]> {
  return props.items.flatMap((item) => {
    const value = item[field]
    if (value === null || value === undefined) {
      return []
    }
    return [[item.report_date, value]]
  })
}

function renderChart(): void {
  if (!chartInstance.value) {
    return
  }

  const option: CurveChartOption = {
    animationDuration: 700,
    animationEasing: 'cubicOut',
    backgroundColor: 'transparent',
    grid: {
      top: 72,
      right: 72,
      bottom: 86,
      left: 28,
    },
    legend: {
      show: false,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(6, 12, 24, 0.96)',
      borderColor: 'rgba(129, 160, 207, 0.22)',
      borderWidth: 1,
      textStyle: {
        color: '#e6eefc',
      },
      padding: 14,
      extraCssText: 'box-shadow: 0 18px 36px rgba(2, 10, 24, 0.45); border-radius: 14px;',
      axisPointer: {
        type: 'line',
        lineStyle: {
          color: 'rgba(86, 213, 255, 0.36)',
          width: 1,
        },
      },
      formatter(params: unknown) {
        const entries = Array.isArray(params) ? params : [params]
        const first = entries[0] as { axisValueLabel?: string } | undefined
        const lines = [`<div style="margin-bottom:8px;color:#9aa9c8">${first?.axisValueLabel ?? '--'}</div>`]

        entries.forEach((entry) => {
          const point = entry as {
            seriesName: string
            color: string
            value: [string, number]
          }

          lines.push(
            `<div style="display:flex;justify-content:space-between;gap:24px;min-width:220px">` +
              `<span style="display:inline-flex;align-items:center;gap:8px">` +
              `<span style="width:8px;height:8px;border-radius:999px;background:${point.color}"></span>` +
              `${point.seriesName}</span>` +
              `<strong style="font-weight:600">${props.formatNumber(point.value[1], 2)}</strong>` +
            `</div>`,
          )
        })

        return lines.join('')
      },
    },
    xAxis: {
      type: 'time',
      axisLine: {
        lineStyle: {
          color: 'rgba(129, 160, 207, 0.16)',
        },
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
          color: '#6d7d9d',
          margin: 16,
        formatter(value: number) {
          return format.formatTime('yyyy-MM', value)
        },
      },
      splitLine: {
        show: false,
      },
    },
    yAxis: [
      {
        type: 'value',
        position: 'right',
        name: '资产',
        nameLocation: 'end',
        nameTextStyle: {
          color: '#6d7d9d',
          padding: [0, 0, 8, 0],
        },
        axisLabel: {
          color: '#6d7d9d',
          formatter(value: number) {
            return formatAxisValue(value)
          },
        },
        splitNumber: 4,
        axisLine: {
          show: false,
        },
        axisTick: {
          show: false,
        },
        splitLine: {
          lineStyle: {
            color: 'rgba(129, 160, 207, 0.11)',
            type: 'dashed',
          },
        },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'none',
        zoomOnMouseWheel: 'ctrl',
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        height: 22,
        bottom: 24,
        borderColor: 'rgba(129, 160, 207, 0.08)',
        backgroundColor: 'rgba(9, 16, 29, 0.72)',
        fillerColor: 'rgba(62, 169, 255, 0.18)',
        moveHandleStyle: {
          color: '#56d5ff',
          opacity: 0.9,
        },
        handleSize: '88%',
        handleStyle: {
          color: '#13284a',
          borderColor: '#56d5ff',
          borderWidth: 1,
        },
        textStyle: {
          color: '#6d7d9d',
        },
      },
    ],
    series: [
      {
        name: '账户权益',
        type: 'line',
        yAxisIndex: 0,
        smooth: 0.18,
        showSymbol: activeSeriesKey.value === 'total_equity',
        symbol: 'circle',
        symbolSize: 7,
        sampling: 'lttb',
        data: buildSeriesData('total_equity'),
        lineStyle: seriesLineStyle('total_equity', 3, '#56d5ff'),
        areaStyle: {
          color: new graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `rgba(86, 213, 255, ${seriesAreaOpacity('total_equity', 0.26)})` },
            { offset: 1, color: `rgba(86, 213, 255, ${seriesAreaOpacity('total_equity', 0.02)})` },
          ]),
        },
        z: isSeriesActive('total_equity') ? 6 : 2,
        emphasis: {
          focus: 'series',
        },
      },
      {
        name: '净收益',
        type: 'line',
        yAxisIndex: 0,
        smooth: 0.22,
        showSymbol: activeSeriesKey.value === 'total_pnl',
        symbol: 'circle',
        symbolSize: 6,
        sampling: 'lttb',
        data: buildSeriesData('total_pnl'),
        lineStyle: seriesLineStyle('total_pnl', 2.5, '#b7e11d'),
        areaStyle: {
          color: new graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `rgba(183, 225, 29, ${seriesAreaOpacity('total_pnl', 0.18)})` },
            { offset: 1, color: `rgba(183, 225, 29, ${seriesAreaOpacity('total_pnl', 0.01)})` },
          ]),
        },
        z: isSeriesActive('total_pnl') ? 6 : 3,
        emphasis: {
          focus: 'series',
        },
      },
      {
        name: '净成本',
        type: 'line',
        yAxisIndex: 0,
        step: 'end',
        showSymbol: activeSeriesKey.value === 'net_cost',
        data: buildSeriesData('net_cost'),
        lineStyle: seriesLineStyle('net_cost', 2.5, '#ffb454'),
        z: isSeriesActive('net_cost') ? 6 : 1,
        emphasis: {
          focus: 'series',
        },
      },
      {
        name: '已实现盈亏',
        type: 'line',
        yAxisIndex: 0,
        smooth: 0.16,
        showSymbol: activeSeriesKey.value === 'realized_pnl',
        symbol: 'circle',
        symbolSize: 6,
        sampling: 'lttb',
        data: buildSeriesData('realized_pnl'),
        lineStyle: seriesLineStyle('realized_pnl', 2.4, '#8b7cff'),
        areaStyle: {
          color: new graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `rgba(139, 124, 255, ${seriesAreaOpacity('realized_pnl', 0.14)})` },
            { offset: 1, color: `rgba(139, 124, 255, ${seriesAreaOpacity('realized_pnl', 0.01)})` },
          ]),
        },
        z: isSeriesActive('realized_pnl') ? 6 : 2,
        emphasis: {
          focus: 'series',
        },
      },
    ],
  }

  chartInstance.value.setOption(option, true)
}

function resizeChart(): void {
  chartInstance.value?.resize()
}

function initChart(): void {
  if (!chartRef.value) {
    return
  }

  chartInstance.value = init(chartRef.value, undefined, {
    renderer: 'canvas',
  })
  renderChart()

  resizeObserver = new ResizeObserver(() => {
    resizeChart()
  })
  resizeObserver.observe(chartRef.value)
  window.addEventListener('resize', resizeChart)
}

onMounted(() => {
  initChart()
})

watch(
  () => [props.items, activeSeriesKey.value],
  () => {
    renderChart()
  },
  { deep: true },
)

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', resizeChart)
  chartInstance.value?.dispose()
  chartInstance.value = null
})
</script>

<template>
  <Card class="surface-panel curve-panel">
    <template #content>
      <div class="surface-panel__content">
        <div class="curve-panel__header">
          <div>
            <p class="eyebrow">Curves</p>
            <h2 class="panel-title curve-panel__title">账户权益 / 净收益 / 净成本 / 已实现盈亏</h2>
            <p class="panel-subtitle curve-panel__subtitle">
              这里的净收益按账户权益减累计净投入计算；已实现盈亏曲线按历史交易记录累计推导，和交易页口径一致。
            </p>
          </div>
          <div class="curve-panel__tags">
            <Tag class="p-tag p-tag--accent" :value="historyTag" />
            <Tag class="p-tag" :value="pointCountTag" />
            <Tag class="p-tag" value="按住 Ctrl + 滚轮缩放" />
          </div>
        </div>

        <div class="curve-range-switcher" aria-label="Curve range presets">
          <button
            v-for="option in rangeOptions"
            :key="option.key"
            type="button"
            class="curve-range-button"
            :class="{ 'curve-range-button--active': selectedRange === option.key }"
            @click="selectRange(option.key)"
          >
            {{ option.label }}
          </button>
        </div>

        <div v-if="items.length === 0" class="empty-state">
          {{ errorMessage || '暂无曲线数据' }}
        </div>

        <div v-else class="curve-panel__body">
          <div v-if="loading" class="curve-panel__loading-mask" aria-live="polite">正在更新曲线…</div>
          <div v-else-if="errorMessage" class="curve-panel__inline-error">{{ errorMessage }}</div>

          <div class="curve-series-switcher" aria-label="Curve focus toggles">
            <button
              v-for="item in seriesControls"
              :key="item.key"
              type="button"
              class="curve-series-button"
              :class="{ 'curve-series-button--active': isSeriesActive(item.key), 'curve-series-button--focused': activeSeriesKey === item.key }"
              @click="toggleSeriesFocus(item.key)"
            >
              <span class="curve-series-button__line" :style="{ background: item.color }"></span>
              <span class="curve-series-button__text">
                <strong>{{ item.label }}</strong>
                <small>{{ item.helper }}</small>
              </span>
            </button>
          </div>

          <div ref="chartRef" class="curve-chart" aria-label="Portfolio curves" />
        </div>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.curve-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.curve-panel__title {
  font-size: 1.45rem;
}

.curve-panel__subtitle {
  max-width: 52rem;
}

.curve-panel__tags {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.curve-panel__body {
  display: grid;
  gap: var(--space-4);
  position: relative;
}

.curve-range-switcher {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: var(--space-4);
}

.curve-range-button {
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

.curve-range-button:hover {
  transform: translateY(-1px);
  border-color: rgba(86, 213, 255, 0.24);
  color: var(--color-text-primary);
}

.curve-panel__loading-mask {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(86, 213, 255, 0.16);
  border-radius: 24px;
  background: rgba(5, 12, 24, 0.44);
  backdrop-filter: blur(3px);
  color: var(--color-text-primary);
  font-weight: 600;
}

.curve-panel__inline-error {
  color: #ff9eb2;
  font-size: 0.95rem;
}

.curve-range-button--active {
  background: linear-gradient(135deg, rgba(34, 99, 196, 0.96), rgba(18, 59, 128, 0.96));
  border-color: rgba(116, 194, 255, 0.45);
  color: #f4f8ff;
  box-shadow: 0 12px 28px rgba(2, 10, 24, 0.18);
}

.curve-series-switcher {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.curve-series-button {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  background: rgba(15, 26, 45, 0.72);
  color: var(--color-text-primary);
  cursor: pointer;
  transition:
    border-color 160ms ease,
    transform 160ms ease,
    background-color 160ms ease,
    opacity 160ms ease,
    box-shadow 160ms ease;
}

.curve-series-button:hover {
  transform: translateY(-1px);
  border-color: rgba(86, 213, 255, 0.22);
}

.curve-series-button--active {
  opacity: 1;
}

.curve-series-button:not(.curve-series-button--active) {
  opacity: 0.56;
}

.curve-series-button--focused {
  border-color: rgba(86, 213, 255, 0.32);
  background: rgba(17, 31, 56, 0.92);
  box-shadow: 0 10px 24px rgba(2, 10, 24, 0.22);
}

.curve-series-button__line {
  width: 32px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 999px;
  box-shadow: 0 0 18px rgba(255, 255, 255, 0.08);
}

.curve-series-button__text {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.curve-series-button__text strong {
  font-size: 0.92rem;
  line-height: 1;
}

.curve-series-button__text small {
  font-size: 0.82rem;
  line-height: 1.05;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.curve-series-button__text {
  display: grid;
  gap: 4px;
  justify-items: start;
  text-align: left;
}

.curve-series-button__text strong {
  font-size: 1.3rem;
  letter-spacing: -0.03em;
}

.curve-series-button__text small {
  color: var(--color-text-secondary);
  font-size: 0.86rem;
}

.curve-chart {
  width: 100%;
  height: 620px;
  border-radius: 24px;
  border: 1px solid rgba(129, 160, 207, 0.1);
  background:
    radial-gradient(circle at top left, rgba(86, 213, 255, 0.08), transparent 22%),
    linear-gradient(180deg, rgba(16, 30, 53, 0.76), rgba(8, 14, 28, 0.92)),
    rgba(8, 14, 28, 0.94);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
}

@media (max-width: 1080px) {
  .curve-panel__header {
    flex-direction: column;
  }

  .curve-panel__tags {
    justify-content: flex-start;
  }

  .curve-series-switcher {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .curve-chart {
    height: 480px;
  }
}
</style>
