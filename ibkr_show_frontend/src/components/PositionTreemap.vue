<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import {
  use,
  graphic,
  init,
  type ComposeOption,
  type EChartsType,
} from 'echarts/core'
import { TreemapChart, type TreemapSeriesOption } from 'echarts/charts'
import {
  TooltipComponent,
  type TooltipComponentOption,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import type { PositionItem } from '@/types/positions'

use([TreemapChart, TooltipComponent, CanvasRenderer])

type TreemapOption = ComposeOption<TreemapSeriesOption | TooltipComponentOption>

interface TreemapDataNode {
  name: string
  value: number
  symbol?: string
  percentText?: string
  valueText?: string
  itemStyle?: { color?: string; borderColor?: string; borderWidth?: number }
  children?: TreemapDataNode[]
  _item?: PositionItem
}

interface TreemapLabelRect {
  x: number
  y: number
  width: number
  height: number
}

interface TreemapSeriesDataLike {
  tree?: {
    root?: TreemapTreeNodeLike
  }
}

interface TreemapSeriesModelLike {
  getData: () => TreemapSeriesDataLike
}

interface EChartsModelLike {
  getSeriesByIndex: (index: number) => TreemapSeriesModelLike | undefined
}

interface EChartsTreemapLayoutReader {
  getModel: () => EChartsModelLike
}

interface TreemapLabelLine {
  text: string
  fontSize: number
  fontWeight: number
  lineHeight: number
  color: string
}

interface TreemapTreeNodeLike {
  name?: string
  dataIndex?: number
  getModel?: () => {
    option?: TreemapDataNode
  }
  viewChildren?: TreemapTreeNodeLike[]
  getLayout: () => unknown
}

interface ZRenderLayerDepth {
  z: number
  z2: number
}

const props = defineProps<{
  items: PositionItem[]
  formatNumber: (value: number | null, digits?: number) => string
}>()

const emit = defineEmits<{
  select: [item: PositionItem]
}>()

const chartRef = ref<HTMLDivElement | null>(null)
const chartInstance = shallowRef<EChartsType | null>(null)
let resizeObserver: ResizeObserver | null = null
let labelLayer: InstanceType<typeof graphic.Group> | null = null

const INDUSTRY_COLORS: Record<string, string> = {
  '半导体': '#18a7ff',
  '软件平台': '#7c5cff',
  '消费电子': '#a855f7',
  '汽车出行': '#22c55e',
  '数字资产': '#f59e0b',
  '金融券商': '#38bdf8',
  '电商消费': '#ec4899',
  '其他': '#64748b',
}

function classifyIndustry(item: PositionItem): string {
  const text = `${item.symbol ?? ''} ${item.description ?? ''}`.toUpperCase()
  if (text.includes('AMD') || text.includes('ARM') || text.includes('INTC') || text.includes('INTEL') || text.includes('QCOM') || text.includes('QUALCOMM') || text.includes('SMCI') || text.includes('ASML') || text.includes('TSM') || text.includes('NVDA') || text.includes('SEMI')) return '半导体'
  if (text.includes('MSFT') || text.includes('MICROSOFT') || text.includes('META') || text.includes('ORCL') || text.includes('ORACLE') || text.includes('SOFTWARE')) return '软件平台'
  if (text.includes('MSTR') || text.includes('STRATEGY') || text.includes('BITCOIN') || text.includes('BTC') || text.includes('IBIT')) return '数字资产'
  if (text.includes('IBKR') || text.includes('INTERACTIVE BROKERS') || text.includes('BROKER')) return '金融券商'
  if (text.includes('XIACY') || text.includes('XIAOMI')) return '消费电子'
  if (text.includes('TSLA') || text.includes('TESLA')) return '汽车出行'
  if (text.includes('AMAZON') || text.includes('AMZN') || text.includes('BABA') || text.includes('PDD') || text.includes('JD')) return '电商消费'
  return '其他'
}

function getIndustryColor(industry: string): string {
  return INDUSTRY_COLORS[industry] ?? INDUSTRY_COLORS['其他']
}

const treemapData = computed<TreemapDataNode[]>(() => {
  const valid = props.items.filter((item) => {
    const symbol = (item.symbol ?? '').trim()
    return symbol.length > 0 && (item.position_value ?? 0) > 0
  })

  valid.sort((a, b) => (b.position_value ?? 0) - (a.position_value ?? 0))

  return valid.map((item) => {
    const symbol = item.symbol ?? '--'
    const navPercent = item.percent_of_nav ?? null
    const percentText = navPercent !== null ? `${props.formatNumber(navPercent, 2)}%` : '--'
    const valueText = props.formatNumber(item.position_value, 0)
    const industry = classifyIndustry(item)
    const color = getIndustryColor(industry)

    return {
      name: symbol,
      value: item.position_value ?? 0,
      symbol,
      percentText,
      valueText,
      itemStyle: { color },
      _item: item,
    }
  })
})

function isTreemapLabelRect(value: unknown): value is TreemapLabelRect {
  if (!value || typeof value !== 'object') return false
  const rect = value as Partial<TreemapLabelRect>
  return (
    typeof rect.x === 'number'
    && typeof rect.y === 'number'
    && typeof rect.width === 'number'
    && typeof rect.height === 'number'
  )
}

function getTreemapLabelLines(data: TreemapDataNode, areaPercent: number, rect: TreemapLabelRect): TreemapLabelLine[] {
  if (areaPercent > 0.08 && rect.width >= 88 && rect.height >= 76) {
    return [
      { text: data.symbol ?? '', fontSize: 22, fontWeight: 800, lineHeight: 28, color: '#e6eefc' },
      { text: data.percentText ?? '', fontSize: 16, fontWeight: 700, lineHeight: 22, color: '#adc0df' },
      { text: data.valueText ?? '', fontSize: 13, fontWeight: 700, lineHeight: 18, color: '#7f96b8' },
    ]
  }
  if (areaPercent > 0.025 && rect.width >= 64 && rect.height >= 46) {
    return [
      { text: data.symbol ?? '', fontSize: 17, fontWeight: 800, lineHeight: 22, color: '#e6eefc' },
      { text: data.percentText ?? '', fontSize: 13, fontWeight: 700, lineHeight: 18, color: '#adc0df' },
    ]
  }
  if (areaPercent > 0.012 && rect.width >= 42 && rect.height >= 24) {
    return [
      { text: data.symbol ?? '', fontSize: 14, fontWeight: 800, lineHeight: 18, color: '#e6eefc' },
    ]
  }
  return []
}

function updateTreemapLabelGraphics(totalValue: number): void {
  const chart = chartInstance.value
  if (!chart) return

  if (labelLayer) {
    chart.getZr().remove(labelLayer)
    labelLayer = null
  }

  const model = (chart as unknown as EChartsTreemapLayoutReader).getModel()
  const seriesData = model.getSeriesByIndex(0)?.getData()
  if (!seriesData) return

  const layer = new graphic.Group({
    silent: true,
  })
  ;(layer as unknown as ZRenderLayerDepth).z = 100

  const rootLayout = seriesData.tree?.root?.getLayout()
  const rootOffsetX = isTreemapLabelRect(rootLayout) ? rootLayout.x : 0
  const rootOffsetY = isTreemapLabelRect(rootLayout) ? rootLayout.y : 0
  const nodes = seriesData.tree?.root?.viewChildren ?? []

  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index]
    const rect = node.getLayout()
    const nodeOption = node.getModel?.().option
    const data = nodeOption?._item
      ? nodeOption
      : treemapData.value.find((item) => item.name === node.name) ?? treemapData.value[index]
    if (!isTreemapLabelRect(rect) || !data) continue

    const areaPercent = totalValue > 0 ? data.value / totalValue : 0
    const lines = getTreemapLabelLines(data, areaPercent, rect)
    if (!lines.length) continue

    const totalTextHeight = lines.reduce((sum, line) => sum + line.lineHeight, 0)
    let lineY = -totalTextHeight / 2
    const group = new graphic.Group({
      x: rootOffsetX + rect.x + rect.width / 2,
      y: rootOffsetY + rect.y + rect.height / 2,
      silent: true,
    })

    for (const line of lines) {
      lineY += line.lineHeight / 2
      const textElement = new graphic.Text({
        x: 0,
        y: lineY,
        silent: true,
        style: {
          text: line.text,
          fill: line.color,
          fontSize: line.fontSize,
          fontWeight: line.fontWeight,
          lineHeight: line.lineHeight,
          align: 'center' as const,
          verticalAlign: 'middle' as const,
        },
      })
      ;(textElement as unknown as ZRenderLayerDepth).z = 100
      ;(textElement as unknown as ZRenderLayerDepth).z2 = 100
      group.add(textElement)
      lineY += line.lineHeight / 2
    }

    layer.add(group)
  }

  chart.getZr().add(layer)
  chart.getZr().refreshImmediately()
  labelLayer = layer
}

function renderChart(): void {
  if (!chartInstance.value || treemapData.value.length === 0) return

  const totalValue = treemapData.value.reduce((sum, d) => sum + d.value, 0)

  const option: TreemapOption = {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: 'rgba(6, 12, 24, 0.96)',
      borderColor: 'rgba(129, 160, 207, 0.22)',
      textStyle: { color: '#e6eefc', fontSize: 13 },
      formatter(params: unknown) {
        const p = params as Record<string, unknown>
        const data = p.data as TreemapDataNode | undefined
        const item = data?._item
        if (!item) return ''

        const lines: string[] = []
        lines.push(`<div style="font-weight:700;margin-bottom:6px;color:#56d5ff">${item.symbol ?? '--'}</div>`)
        if (item.description) lines.push(`<div style="color:#9aa9c8;margin-bottom:4px">${item.description}</div>`)
        lines.push(`<div>持仓市值: <strong>${props.formatNumber(item.position_value, 2)}</strong></div>`)
        const nav = item.percent_of_nav
        lines.push(`<div>账户占比: <strong>${nav !== null ? `${props.formatNumber(nav, 2)}%` : '--'}</strong></div>`)
        lines.push(`<div>数量: ${props.formatNumber(item.quantity, 4)}</div>`)
        lines.push(`<div>现价: ${props.formatNumber(item.mark_price, 2)}</div>`)
        lines.push(`<div>持仓均价: ${props.formatNumber(item.average_cost_price, 2)}</div>`)
        lines.push(`<div>摊薄成本价: ${props.formatNumber(item.diluted_cost_price, 2)}</div>`)
        const unrealized = item.total_unrealized_pnl
        const unrealizedColor = unrealized !== null && unrealized > 0 ? '#34d2a3' : unrealized !== null && unrealized < 0 ? '#ff6b7d' : '#e6eefc'
        lines.push(`<div>未实现盈亏: <span style="color:${unrealizedColor}">${props.formatNumber(unrealized, 2)}</span></div>`)
        const realized = item.total_realized_pnl
        const realizedColor = realized !== null && realized > 0 ? '#34d2a3' : realized !== null && realized < 0 ? '#ff6b7d' : '#e6eefc'
        lines.push(`<div>已实现盈亏: <span style="color:${realizedColor}">${props.formatNumber(realized, 2)}</span></div>`)
        return lines.join('')
      },
    },
    series: [
      {
        type: 'treemap',
        data: treemapData.value,
        width: '100%',
        height: '100%',
        left: 0,
        right: 0,
        top: 0,
        bottom: 0,
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        itemStyle: {
          borderColor: 'rgba(6, 12, 24, 0.95)',
          borderWidth: 3,
          gapWidth: 3,
        },
        emphasis: {
          itemStyle: {
            borderColor: 'rgba(86, 213, 255, 0.6)',
            borderWidth: 3,
            shadowBlur: 12,
            shadowColor: 'rgba(86, 213, 255, 0.2)',
          },
        },
        upperLabel: {
          show: false,
        },
        label: {
          show: false,
          position: 'inside',
          align: 'center',
          verticalAlign: 'middle',
        },
      },
    ],
  }

  chartInstance.value.setOption(option, true)
  window.requestAnimationFrame(() => updateTreemapLabelGraphics(totalValue))
}

function handleClick(params: Record<string, unknown>): void {
  if (params.componentType !== 'series') return
  const data = params.data as TreemapDataNode | undefined
  if (data?._item) {
    emit('select', data._item)
  }
}

onMounted(() => {
  if (!chartRef.value) return
  chartInstance.value = init(chartRef.value)
  renderChart()

  chartInstance.value.on('click', handleClick)

  resizeObserver = new ResizeObserver(() => {
    chartInstance.value?.resize()
    renderChart()
  })
  resizeObserver.observe(chartRef.value)
})

watch(
  () => props.items,
  () => { renderChart() },
  { deep: true },
)

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (labelLayer) {
    chartInstance.value?.getZr().remove(labelLayer)
    labelLayer = null
  }
  chartInstance.value?.off('click', handleClick)
  chartInstance.value?.dispose()
  chartInstance.value = null
})
</script>

<template>
  <section class="surface-panel position-treemap-panel">
    <div class="surface-panel__content position-treemap-panel__content">
      <div class="section-header">
        <div>
          <h2 class="panel-title">持仓全景图</h2>
          <p class="panel-subtitle">按行业着色，面积反映仓位大小，点击查看详情。</p>
        </div>
      </div>
      <div v-if="treemapData.length === 0" class="empty-state">暂无持仓数据</div>
      <div v-else ref="chartRef" class="treemap-chart"></div>
    </div>
  </section>
</template>

<style scoped>
.position-treemap-panel__content {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.position-treemap-panel :deep(.section-header) {
  margin-bottom: 0.5rem;
}

.treemap-chart {
  width: 100%;
  height: 460px;
}

@media (max-width: 980px) {
  .treemap-chart {
    height: 360px;
  }
}
</style>
