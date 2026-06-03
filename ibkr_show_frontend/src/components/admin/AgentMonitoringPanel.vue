<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import {
  getAgentMonitoringOverview,
  getAgentRecentLlmCalls,
  getAgentRecentToolCalls,
  getStructuredOutputRecent,
  getToolReliabilityLatest,
  runToolReliabilityProbe,
} from '@/api/accountCopilot'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { formatLocalDateTime } from '@/utils/dateTime'
import type {
  AgentMonitoringOverviewResponse,
  AgentMonitoringStatusSummary,
  AgentRecentLlmCall,
  AgentRecentToolCall,
  AgentStructuredOutputEvent,
  CopilotToolProbeResult,
  CopilotToolReliabilityLatestResponse,
  CopilotToolReliabilityProbeResponse,
} from '@/types/accountCopilot'

echarts.use([LineChart, BarChart, ScatterChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

type ProbeKind = 'mcp' | 'ibkr'
type CallTypeFilter = 'all' | 'mcp' | 'ibkr' | 'llm'

const agentOptions = [
  { label: '全部 Agent', value: '' },
  { label: 'Trade Decision', value: 'trade_decision' },
  { label: 'Account Copilot', value: 'account_copilot' },
  { label: 'Trade Review', value: 'trade_review' },
  { label: 'Daily Review', value: 'daily_review' },
]
const typeOptions: { label: string; value: CallTypeFilter }[] = [
  { label: '全部', value: 'all' },
  { label: 'MCP', value: 'mcp' },
  { label: 'IBKR', value: 'ibkr' },
  { label: 'LLM', value: 'llm' },
]
const limitOptions = [50, 100, 200, 500]

const SENSITIVE_KEYWORDS = ['api_key', 'apikey', 'cookie', 'authorization', 'secret', 'password', 'access_token', 'refresh_token']
const SENSITIVE_VALUE_PATTERN = /(bearer\s+[a-z0-9._~+/-]+|sk-[a-z0-9_-]+|api[_-]?key\s*[:=]\s*[^,\s]+)/gi

const loading = ref(true)
const errorMessage = ref('')
const probeMessage = ref('')
const probing = ref<ProbeKind | null>(null)
const selectedAgent = ref('')
const selectedType = ref<CallTypeFilter>('all')
const selectedLimit = ref(100)
const overview = ref<AgentMonitoringOverviewResponse | null>(null)
const toolCalls = ref<AgentRecentToolCall[]>([])
const llmCalls = ref<AgentRecentLlmCall[]>([])
const soEvents = ref<AgentStructuredOutputEvent[]>([])
const latestProbe = ref<CopilotToolReliabilityLatestResponse | CopilotToolReliabilityProbeResponse | null>(null)
const showProbeDetails = ref(false)
const expandedFailure = ref<string | null>(null)
const expandedProbeRow = ref<string | null>(null)

const ibkrChartRef = ref<HTMLDivElement | null>(null)
const mcpChartRef = ref<HTMLDivElement | null>(null)
const llmChartRef = ref<HTMLDivElement | null>(null)
const llmTokenChartRef = ref<HTMLDivElement | null>(null)
const soChartRef = ref<HTMLDivElement | null>(null)

let ibkrChart: EChartsType | null = null
let mcpChart: EChartsType | null = null
let llmChart: EChartsType | null = null
let llmTokenChart: EChartsType | null = null
let soChart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null

const METRIC_LABELS: Record<string, string> = {
  latency_ms: '调用耗时',
  rolling_success_rate_10: '最近10次成功率',
  missing_fields_count: '缺失字段数',
  total_tokens: 'Token 消耗',
  rolling_repair_rate_10: '最近10次修复率',
  rolling_fallback_rate_10: '最近10次兜底率',
  repair_attempts: '修复次数',
}

function fmtOk(v: unknown): string {
  return v === true ? '成功' : v === false ? '失败' : '--'
}
function fmtBool(v: unknown): string {
  return v === true ? '是' : v === false ? '否' : '--'
}

const tooltipBase = {
  backgroundColor: 'rgba(8, 13, 24, 0.96)',
  borderColor: 'rgba(129, 160, 207, 0.22)',
  textStyle: { color: '#dbeafe' },
}

const ibkrCalls = computed(() => toolCalls.value.filter((item) => item.tool_domain === 'ibkr'))
const mcpCalls = computed(() => toolCalls.value.filter((item) => item.tool_domain === 'longbridge'))
const soContractOptions = computed(() => {
  const names = new Set(soEvents.value.map((e) => e.contract_name).filter(Boolean))
  return [{ label: '全部 Contract', value: '' }, ...Array.from(names).sort().map((n) => ({ label: n, value: n }))]
})
const soFailures = computed(() =>
  soEvents.value.filter((e) => !e.ok || e.repaired || e.fallback_used).slice(0, 50),
)
const visibleProbeResults = computed(() => (latestProbe.value?.results ?? []).filter((row) => ['fail', 'partial', 'skipped'].includes(row.status)))
const hasVisibleProbeResults = computed(() => visibleProbeResults.value.length > 0)

const statusCards = computed(() => [
  {
    key: 'ibkr',
    title: 'IBKR 工具',
    icon: 'pi pi-database',
    summary: overview.value?.ibkr,
    recent: summarizeRecent(ibkrCalls.value),
  },
  {
    key: 'mcp',
    title: 'MCP 工具',
    icon: 'pi pi-link',
    summary: overview.value?.longbridge,
    recent: summarizeRecent(mcpCalls.value),
  },
  {
    key: 'llm',
    title: 'LLM',
    icon: 'pi pi-sparkles',
    summary: overview.value?.llm,
    recent: summarizeRecent(llmCalls.value),
    models: Array.from(new Set(llmCalls.value.map((item) => item.model).filter(Boolean))).slice(0, 6),
  },
])

const recentFailures = computed(() => {
  const toolRows = toolCalls.value
    .filter((item) => item.ok === false || item.empty_result || item.compact_ok === false || item.missing_fields_count > 0)
    .map((item) => ({
      key: `tool:${item.id}`,
      created_at: item.created_at,
      kind: 'tool' as const,
      agent_name: item.agent_name,
      node_name: item.node_name,
      name: item.tool_name,
      domain: item.tool_domain,
      error_code: item.error_code || (item.missing_fields_count > 0 ? 'PARTIAL_FIELDS' : item.empty_result ? 'EMPTY_RESULT' : ''),
      error_message: item.error_message || (item.missing_fields_count > 0 ? `缺少字段 ${item.missing_fields_count} 个` : ''),
      latency_ms: item.latency_ms,
      run_id: item.run_id,
      task_id: item.task_id,
      partial: item.ok && item.missing_fields_count > 0,
    }))
  const llmRows = llmCalls.value
    .filter((item) => item.ok === false)
    .map((item) => ({
      key: `llm:${item.id}`,
      created_at: item.created_at,
      kind: 'llm' as const,
      agent_name: item.agent_name,
      node_name: item.node_name,
      name: item.model,
      domain: 'llm',
      error_code: item.error_code || '',
      error_message: item.error_message || '',
      latency_ms: item.latency_ms,
      run_id: item.run_id,
      task_id: item.task_id,
      partial: false,
    }))
  return [...toolRows, ...llmRows]
    .sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at))
    .slice(0, 80)
})

watch([selectedAgent, selectedLimit], () => {
  void loadAll()
})

watch([toolCalls, llmCalls, selectedType], () => {
  void nextTick(renderCharts)
})

onMounted(async () => {
  await loadAll()
  await nextTick()
  ensureCharts()
  renderCharts()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  ibkrChart?.dispose()
  mcpChart?.dispose()
  llmChart?.dispose()
  llmTokenChart?.dispose()
  soChart?.dispose()
})

async function loadAll(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const agentName = selectedAgent.value || undefined
    const [overviewResponse, toolResponse, llmResponse, latestResponse, soResponse] = await Promise.all([
      getAgentMonitoringOverview({ hours: 24, bucket: '1h' }),
      getAgentRecentToolCalls({
        limit: selectedLimit.value,
        agent_name: agentName,
      }),
      getAgentRecentLlmCalls({
        limit: selectedLimit.value,
        agent_name: agentName,
      }),
      getToolReliabilityLatest(),
      getStructuredOutputRecent({
        limit: selectedLimit.value,
        agent_name: agentName || undefined,
      }).catch(() => ({ items: [] })),
    ])
    overview.value = overviewResponse
    toolCalls.value = toolResponse.items || []
    llmCalls.value = llmResponse.items || []
    latestProbe.value = latestResponse
    soEvents.value = soResponse.items || []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 Agent 监控数据失败'
  } finally {
    loading.value = false
    await nextTick()
    requestAnimationFrame(() => {
      ensureCharts()
      renderCharts()
    })
  }
}

async function runOneClickProbe(kind: ProbeKind): Promise<void> {
  probing.value = kind
  probeMessage.value = ''
  errorMessage.value = ''
  try {
    const response = await runToolReliabilityProbe({
      include_live: true,
      include_longbridge: kind === 'mcp',
      include_ibkr: kind === 'ibkr',
      include_agent_eval: false,
      symbol: 'AMD.US',
      keyword: 'AMD',
      max_tools: 20,
    })
    latestProbe.value = response
    probeMessage.value = [
      `${kind === 'mcp' ? 'MCP' : 'IBKR'} 检测完成`,
      `total ${response.total}`,
      `pass ${response.pass}`,
      `fail ${response.fail}`,
      `skipped ${response.skipped}`,
      `成功率 ${formatPct(response.success_rate)}`,
      '检测结果已写入监控数据。',
    ].join(' · ')
    await loadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运行检测失败'
  } finally {
    probing.value = null
  }
}

function ensureCharts(): void {
  // Dispose stale instances: ref is null (DOM destroyed by v-if) OR DOM mismatch (ref replaced)
  if (ibkrChart && (!ibkrChartRef.value || ibkrChart.getDom() !== ibkrChartRef.value)) { ibkrChart.dispose(); ibkrChart = null }
  if (mcpChart && (!mcpChartRef.value || mcpChart.getDom() !== mcpChartRef.value)) { mcpChart.dispose(); mcpChart = null }
  if (llmChart && (!llmChartRef.value || llmChart.getDom() !== llmChartRef.value)) { llmChart.dispose(); llmChart = null }
  if (llmTokenChart && (!llmTokenChartRef.value || llmTokenChart.getDom() !== llmTokenChartRef.value)) { llmTokenChart.dispose(); llmTokenChart = null }
  if (soChart && (!soChartRef.value || soChart.getDom() !== soChartRef.value)) { soChart.dispose(); soChart = null }

  if (!ibkrChart && ibkrChartRef.value) ibkrChart = echarts.init(ibkrChartRef.value, undefined, { renderer: 'canvas' })
  if (!mcpChart && mcpChartRef.value) mcpChart = echarts.init(mcpChartRef.value, undefined, { renderer: 'canvas' })
  if (!llmChart && llmChartRef.value) llmChart = echarts.init(llmChartRef.value, undefined, { renderer: 'canvas' })
  if (!llmTokenChart && llmTokenChartRef.value) llmTokenChart = echarts.init(llmTokenChartRef.value, undefined, { renderer: 'canvas' })
  if (!soChart && soChartRef.value) soChart = echarts.init(soChartRef.value, undefined, { renderer: 'canvas' })
  if (!resizeObserver && (ibkrChartRef.value || mcpChartRef.value || llmChartRef.value || llmTokenChartRef.value || soChartRef.value)) {
    resizeObserver = new ResizeObserver(() => {
      ibkrChart?.resize()
      mcpChart?.resize()
      llmChart?.resize()
      llmTokenChart?.resize()
      soChart?.resize()
    })
    ;[ibkrChartRef.value, mcpChartRef.value, llmChartRef.value, llmTokenChartRef.value, soChartRef.value].forEach((element) => {
      if (element) resizeObserver?.observe(element)
    })
  }
}

function renderCharts(): void {
  ensureCharts()
  if (selectedType.value === 'llm') {
    renderToolChart(ibkrChart, [], 'IBKR 工具调用稳定性')
    renderToolChart(mcpChart, [], 'Longbridge MCP 公开数据工具稳定性')
  } else {
    renderToolChart(ibkrChart, selectedType.value === 'mcp' ? [] : ibkrCalls.value, 'IBKR 工具调用稳定性')
    renderToolChart(mcpChart, selectedType.value === 'ibkr' ? [] : mcpCalls.value, 'Longbridge MCP 公开数据工具稳定性')
  }
  const llmData = selectedType.value === 'mcp' || selectedType.value === 'ibkr' ? [] : llmCalls.value
  renderLlmStabilityChart(llmData)
  renderLlmTokenChart(llmData)
  renderSoChart(soEvents.value)
}

const AXIS_STYLE = { color: '#9fb2d1' }
const SPLIT_LINE = { lineStyle: { color: 'rgba(129, 160, 207, 0.12)' } }
const AXIS_LINE = { lineStyle: { color: 'rgba(159, 178, 209, 0.24)' } }

function renderToolChart(chart: EChartsType | null, calls: AgentRecentToolCall[], title: string): void {
  if (!chart) return
  const labels = calls.map((_, i) => `#${i + 1}`)
  chart.setOption({
    color: ['#60a5fa', '#22c55e', '#f59e0b', '#ef4444'],
    backgroundColor: 'transparent',
    legend: { top: 6, right: 0, textStyle: { color: '#9fb2d1' }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 52, right: 60, top: 42, bottom: 42 },
    tooltip: {
      trigger: 'axis',
      ...tooltipBase,
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        const idx = rows[0]?.dataIndex ?? 0
        const p = calls[idx]
        if (!p) return '暂无调用'
        return [
          `${rows[0]?.axisValue || ''} · ${formatTime(p.created_at)}`,
          `Agent: ${p.agent_name}　节点: ${p.node_name}`,
          `工具: ${p.tool_name}`,
          `是否成功: ${fmtOk(p.ok)}　调用耗时: ${formatMs(p.latency_ms)}`,
          `最近10次成功率: ${formatPct(p.rolling_success_rate_10)} (${p.rolling_window_size})`,
          `最近10次失败率: ${formatPct(p.rolling_failure_rate_10)}`,
          `是否空结果: ${fmtBool(p.empty_result)}`,
          `原始调用成功: ${fmtOk(p.raw_ok)}　压缩解析成功: ${fmtOk(p.compact_ok)}`,
          `已解析字段: ${p.parsed_fields_count}　缺失字段: ${p.missing_fields_count}`,
          p.error_code ? `错误码: ${p.error_code}` : '',
          p.error_message ? `错误信息: ${truncateText(p.error_message, 160)}` : '',
        ].filter(Boolean).join('<br/>')
      },
    },
    xAxis: { type: 'category', axisLine: AXIS_LINE, axisTick: { show: false }, axisLabel: AXIS_STYLE, data: labels },
    yAxis: [
      { type: 'value', min: 0, name: '耗时 / 缺失字段', nameTextStyle: { color: '#9fb2d1', fontSize: 11 }, nameGap: 8, axisLabel: { formatter: '{value}', ...AXIS_STYLE }, splitLine: SPLIT_LINE },
      { type: 'value', min: 0, max: 100, name: '成功率', nameTextStyle: { color: '#9fb2d1', fontSize: 11 }, nameGap: 8, axisLabel: { formatter: '{value}%', ...AXIS_STYLE }, splitLine: { show: false } },
    ],
    series: [
      { name: METRIC_LABELS.latency_ms, type: 'line', yAxisIndex: 0, smooth: true, data: calls.map((c) => c.latency_ms) },
      { name: METRIC_LABELS.rolling_success_rate_10, type: 'line', yAxisIndex: 1, smooth: true, data: calls.map((c) => roundPct(c.rolling_success_rate_10)) },
      { name: METRIC_LABELS.missing_fields_count, type: 'bar', yAxisIndex: 0, barMaxWidth: 16, data: calls.map((c) => c.missing_fields_count) },
      { name: '异常点', type: 'scatter', yAxisIndex: 0, symbolSize: 9, data: calls.map((c) => (c.ok === false || c.empty_result || c.compact_ok === false ? c.latency_ms : null)) },
    ],
  }, true)
}

function renderLlmStabilityChart(calls: AgentRecentLlmCall[]): void {
  if (!llmChart) return
  const labels = calls.map((_, i) => `#${i + 1}`)
  llmChart.setOption({
    color: ['#60a5fa', '#22c55e', '#ef4444'],
    backgroundColor: 'transparent',
    legend: { top: 6, right: 0, textStyle: { color: '#9fb2d1' }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 52, right: 60, top: 42, bottom: 42 },
    tooltip: {
      trigger: 'axis',
      ...tooltipBase,
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        const idx = rows[0]?.dataIndex ?? 0
        const p = calls[idx]
        if (!p) return '暂无调用'
        return [
          `${rows[0]?.axisValue || ''} · ${formatTime(p.created_at)}`,
          `Agent: ${p.agent_name}　节点: ${p.node_name}`,
          `服务商: ${p.provider}　模型: ${p.model}`,
          `调用类型: ${p.call_type}`,
          `是否成功: ${fmtOk(p.ok)}　调用耗时: ${formatMs(p.latency_ms)}`,
          `输入 Token: ${formatNumber(p.prompt_tokens)}　输出 Token: ${formatNumber(p.completion_tokens)}`,
          `最近10次成功率: ${formatPct(p.rolling_success_rate_10)} (${p.rolling_window_size})`,
          p.error_code ? `错误码: ${p.error_code}` : '',
          p.error_message ? `错误信息: ${truncateText(p.error_message, 160)}` : '',
        ].filter(Boolean).join('<br/>')
      },
    },
    xAxis: { type: 'category', axisLine: AXIS_LINE, axisTick: { show: false }, axisLabel: AXIS_STYLE, data: labels },
    yAxis: [
      { type: 'value', min: 0, name: '耗时 (ms)', nameTextStyle: { color: '#9fb2d1', fontSize: 11 }, nameGap: 8, axisLabel: { formatter: '{value}', ...AXIS_STYLE }, splitLine: SPLIT_LINE },
      { type: 'value', min: 0, max: 100, name: '成功率', nameTextStyle: { color: '#9fb2d1', fontSize: 11 }, nameGap: 8, axisLabel: { formatter: '{value}%', ...AXIS_STYLE }, splitLine: { show: false } },
    ],
    series: [
      { name: METRIC_LABELS.latency_ms, type: 'line', yAxisIndex: 0, smooth: true, data: calls.map((c) => c.latency_ms) },
      { name: METRIC_LABELS.rolling_success_rate_10, type: 'line', yAxisIndex: 1, smooth: true, data: calls.map((c) => roundPct(c.rolling_success_rate_10)) },
      { name: '失败点', type: 'scatter', yAxisIndex: 0, symbolSize: 9, data: calls.map((c) => (c.ok === false ? c.latency_ms : null)) },
    ],
  }, true)
}

function renderLlmTokenChart(calls: AgentRecentLlmCall[]): void {
  if (!llmTokenChart) return
  const labels = calls.map((_, i) => `#${i + 1}`)
  llmTokenChart.setOption({
    color: ['#a78bfa', '#60a5fa'],
    backgroundColor: 'transparent',
    legend: { top: 6, right: 0, textStyle: { color: '#9fb2d1' }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 60, right: 24, top: 42, bottom: 42 },
    tooltip: {
      trigger: 'axis',
      ...tooltipBase,
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        const idx = rows[0]?.dataIndex ?? 0
        const p = calls[idx]
        if (!p) return '暂无调用'
        return [
          `${rows[0]?.axisValue || ''} · ${formatTime(p.created_at)}`,
          `模型: ${p.model}`,
          `输入 Token: ${formatNumber(p.prompt_tokens)}`,
          `输出 Token: ${formatNumber(p.completion_tokens)}`,
          `总 Token: ${formatNumber(p.total_tokens)}`,
        ].join('<br/>')
      },
    },
    xAxis: { type: 'category', axisLine: AXIS_LINE, axisTick: { show: false }, axisLabel: AXIS_STYLE, data: labels },
    yAxis: [
      { type: 'value', min: 0, name: 'Token 数', nameTextStyle: { color: '#9fb2d1', fontSize: 11 }, nameGap: 8, axisLabel: { ...AXIS_STYLE }, splitLine: SPLIT_LINE },
    ],
    series: [
      { name: '输入 Token', type: 'bar', stack: 'tokens', barMaxWidth: 20, data: calls.map((c) => c.prompt_tokens) },
      { name: '输出 Token', type: 'bar', stack: 'tokens', barMaxWidth: 20, data: calls.map((c) => c.completion_tokens) },
    ],
  }, true)
}

function renderSoChart(events: AgentStructuredOutputEvent[]): void {
  if (!soChart) return
  const labels = events.map((_, i) => `#${i + 1}`)
  soChart.setOption({
    color: ['#60a5fa', '#22c55e', '#f59e0b', '#ef4444', '#a78bfa'],
    backgroundColor: 'transparent',
    legend: { top: 6, right: 0, textStyle: { color: '#9fb2d1' }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 52, right: 60, top: 42, bottom: 42 },
    tooltip: {
      trigger: 'axis',
      ...tooltipBase,
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        const idx = rows[0]?.dataIndex ?? 0
        const p = events[idx]
        if (!p) return '暂无记录'
        return [
          `${rows[0]?.axisValue || ''} · ${formatTime(p.created_at)}`,
          `输出契约: ${p.contract_name}`,
          `Agent: ${p.agent_name}　节点: ${p.node_name}`,
          `是否成功: ${fmtOk(p.ok)}`,
          `是否修复: ${fmtBool(p.repaired)}${p.repaired ? ` (${p.repair_attempts} 次)` : ''}`,
          `是否兜底: ${fmtBool(p.fallback_used)}`,
          `Schema 校验: ${fmtOk(p.schema_validation_passed)}`,
          `最近10次成功率: ${formatPct(p.rolling_success_rate_10)}`,
          `最近10次修复率: ${formatPct(p.rolling_repair_rate_10)}`,
          `最近10次兜底率: ${formatPct(p.rolling_fallback_rate_10)}`,
          p.error_code ? `错误码: ${p.error_code}` : '',
          p.error_message ? `错误信息: ${truncateText(p.error_message, 160)}` : '',
          `run_id: ${p.run_id || '--'}`,
          `task_id: ${p.task_id || '--'}`,
        ].filter(Boolean).join('<br/>')
      },
    },
    xAxis: { type: 'category', axisLine: AXIS_LINE, axisTick: { show: false }, axisLabel: AXIS_STYLE, data: labels },
    yAxis: [
      { type: 'value', min: 0, max: 100, name: '比例 (%)', nameTextStyle: { color: '#9fb2d1', fontSize: 11 }, nameGap: 8, axisLabel: { formatter: '{value}%', ...AXIS_STYLE }, splitLine: SPLIT_LINE },
      { type: 'value', min: 0, name: '次数', nameTextStyle: { color: '#9fb2d1', fontSize: 11 }, nameGap: 8, axisLabel: { ...AXIS_STYLE }, splitLine: { show: false } },
    ],
    series: [
      { name: METRIC_LABELS.rolling_success_rate_10, type: 'line', yAxisIndex: 0, smooth: true, data: events.map((e) => roundPct(e.rolling_success_rate_10)) },
      { name: METRIC_LABELS.rolling_repair_rate_10, type: 'line', yAxisIndex: 0, smooth: true, data: events.map((e) => roundPct(e.rolling_repair_rate_10)) },
      { name: METRIC_LABELS.rolling_fallback_rate_10, type: 'line', yAxisIndex: 0, smooth: true, data: events.map((e) => roundPct(e.rolling_fallback_rate_10)) },
      { name: METRIC_LABELS.repair_attempts, type: 'bar', yAxisIndex: 1, barMaxWidth: 12, data: events.map((e) => e.repair_attempts) },
      { name: '输出状态', type: 'scatter', yAxisIndex: 1, symbolSize: 10, data: events.map((e) => { if (!e.ok) return 1; if (e.fallback_used) return 0.8; if (e.repaired) return 0.5; return 0 }) },
    ],
  }, true)
}

function summarizeRecent(items: Array<{ ok: boolean; latency_ms: number; rolling_success_rate_10?: number }>): { count: number; successRate: number; p95: number; status: string } {
  const count = items.length
  const last = items[count - 1]
  const successRate = last?.rolling_success_rate_10 ?? (count ? items.filter((item) => item.ok).length / count : 0)
  const p95 = percentile(items.map((item) => item.latency_ms), 0.95)
  return { count, successRate, p95, status: statusFromSuccessRate(successRate, count) }
}

function percentile(values: number[], ratio: number): number {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (!sorted.length) return 0
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1)
  return sorted[index]
}

function statusFromSuccessRate(successRate: number, total: number): string {
  if (total <= 0) return 'unknown'
  if (successRate >= 0.95) return 'healthy'
  if (successRate >= 0.8) return 'degraded'
  return 'down'
}

function roundPct(value: number | null | undefined): number {
  return Number(((value ?? 0) * 100).toFixed(1))
}

function formatPct(value: number | null | undefined): string {
  return `${roundPct(value).toFixed(1)}%`
}

function formatMs(value: number | null | undefined): string {
  const ms = Math.round(value ?? 0)
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(Math.round(value ?? 0))
}

function formatTime(value: string | null | undefined): string {
  return formatLocalDateTime(value) || '--'
}

function timestamp(value: string): number {
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

function statusLabel(status: string | undefined): string {
  switch (status) {
    case 'healthy': return '正常'
    case 'degraded': return '降级'
    case 'down': return '异常'
    default: return '暂无数据'
  }
}

function statusSeverity(status: string | undefined): 'success' | 'warn' | 'danger' | 'secondary' {
  switch (status) {
    case 'healthy': return 'success'
    case 'degraded': return 'warn'
    case 'down': return 'danger'
    default: return 'secondary'
  }
}

function getLegacySummaryMetric(summary: AgentMonitoringStatusSummary | undefined, metric: string): number {
  if (!summary) return 0
  const requested = `${metric}_24h`
  const value = summary[requested] ?? 0
  return typeof value === 'number' ? value : 0
}

function isSensitiveKey(key: string): boolean {
  const lower = key.toLowerCase()
  return SENSITIVE_KEYWORDS.some((keyword) => lower === keyword || lower.includes(keyword))
}

function sanitizeText(value: string | null | undefined): string {
  if (!value) return ''
  let sanitized = value.replace(SENSITIVE_VALUE_PATTERN, '***REDACTED***')
  SENSITIVE_KEYWORDS.forEach((keyword) => {
    const pattern = new RegExp(`(${keyword}\\s*[:=]\\s*)[^,;\\s]+`, 'gi')
    sanitized = sanitized.replace(pattern, '$1***REDACTED***')
  })
  return sanitized
}

function truncateText(value: string | null | undefined, maxLength = 120): string {
  const sanitized = sanitizeText(value)
  return sanitized.length > maxLength ? `${sanitized.slice(0, maxLength)}...` : sanitized
}

function sanitizeObject(obj: Record<string, any> | null | undefined): Record<string, any> {
  if (!obj) return {}
  const out: Record<string, any> = {}
  for (const [key, value] of Object.entries(obj)) {
    if (isSensitiveKey(key)) {
      out[key] = '***REDACTED***'
    } else if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      out[key] = sanitizeObject(value as Record<string, any>)
    } else if (typeof value === 'string') {
      out[key] = sanitizeText(value)
    } else {
      out[key] = value
    }
  }
  return out
}

function emptyHint(kind: string): string {
  return `当前筛选条件下没有${kind}调用记录。可以点击一键检测 MCP / IBKR，或先运行一次 AI 决策任务后刷新。`
}

function failureKey(row: { key: string }): string {
  return row.key
}

function toggleFailure(row: { key: string }): void {
  expandedFailure.value = expandedFailure.value === row.key ? null : row.key
}

function toggleProbeRow(row: CopilotToolProbeResult): void {
  expandedProbeRow.value = expandedProbeRow.value === row.id ? null : row.id
}

function probeStatusSeverity(status: string): 'success' | 'danger' | 'warn' | 'secondary' {
  switch (status) {
    case 'pass': return 'success'
    case 'fail': return 'danger'
    case 'partial': return 'warn'
    default: return 'secondary'
  }
}
</script>

<template>
  <section class="agent-monitoring">
    <LoadingBlock v-if="loading" />

    <template v-else>
      <ErrorBlock v-if="errorMessage" :message="errorMessage" />

      <section class="agent-monitoring__toolbar surface-panel">
        <div class="surface-panel__content agent-monitoring__toolbar-content">
          <div>
            <p class="eyebrow">RECENT CALLS</p>
            <h3 class="panel-title">运行监控</h3>
            <p class="panel-subtitle">每个点代表一次真实调用；成功率为最近 10 次滚动值。</p>
          </div>
          <div class="agent-monitoring__toolbar-controls">
            <label>
              Agent
              <select v-model="selectedAgent">
                <option v-for="option in agentOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>
              类型
              <select v-model="selectedType">
                <option v-for="option in typeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>
              Limit
              <select v-model.number="selectedLimit">
                <option v-for="option in limitOptions" :key="option" :value="option">{{ option }}</option>
              </select>
            </label>
            <Button label="刷新" icon="pi pi-refresh" class="p-button p-button--ghost" @click="loadAll" />
          </div>
        </div>
      </section>

      <section class="agent-monitoring__status-grid">
        <article
          v-for="card in statusCards"
          :key="card.key"
          class="agent-monitoring__status-card"
          :class="`agent-monitoring__status-card--${card.recent.status}`"
        >
          <div class="agent-monitoring__status-header">
            <span class="agent-monitoring__status-icon"><i :class="card.icon"></i></span>
            <div>
              <h3>{{ card.title }}</h3>
              <Tag :value="statusLabel(card.recent.status)" :severity="statusSeverity(card.recent.status)" />
            </div>
          </div>
          <dl class="agent-monitoring__status-metrics">
            <div>
              <dt>最近 10 次成功率</dt>
              <dd>{{ formatPct(card.recent.successRate) }}</dd>
            </div>
            <div>
              <dt>当前列表调用数</dt>
              <dd>{{ card.recent.count }}</dd>
            </div>
            <div>
              <dt>P95 耗时</dt>
              <dd>{{ formatMs(card.recent.p95 || getLegacySummaryMetric(card.summary, 'p95_latency_ms')) }}</dd>
            </div>
          </dl>
          <div v-if="'models' in card && card.models?.length" class="agent-monitoring__models">
            <span v-for="model in card.models" :key="model">{{ model }}</span>
          </div>
        </article>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header agent-monitoring__actions-header">
            <div>
              <h3 class="panel-title">一键检测</h3>
              <p class="panel-subtitle">检测只会调用只读工具，不会下单、撤单、转账或修改账户。</p>
            </div>
            <div class="agent-monitoring__probe-actions">
              <Button
                label="一键检测 MCP"
                icon="pi pi-link"
                class="p-button p-button--accent"
                :loading="probing === 'mcp'"
                :disabled="probing !== null"
                @click="runOneClickProbe('mcp')"
              />
              <Button
                label="一键检测 IBKR"
                icon="pi pi-database"
                class="p-button p-button--ghost"
                :loading="probing === 'ibkr'"
                :disabled="probing !== null"
                @click="runOneClickProbe('ibkr')"
              />
            </div>
          </div>
          <p v-if="probeMessage" class="agent-monitoring__probe-message">{{ probeMessage }}</p>
        </div>
      </section>

      <section class="agent-monitoring__chart-grid">
        <article v-if="selectedType === 'all' || selectedType === 'ibkr'" class="agent-monitoring__chart-card">
          <h4 class="agent-monitoring__chart-title">IBKR 工具调用稳定性</h4>
          <p class="agent-monitoring__chart-desc">观察账户、持仓、交易等 IBKR 只读工具调用是否成功、耗时是否异常、返回字段是否完整。</p>
          <div v-if="!ibkrCalls.length" class="agent-monitoring__empty-chart">{{ emptyHint(' IBKR 工具') }}</div>
          <div ref="ibkrChartRef" class="agent-monitoring__chart"></div>
        </article>
        <article v-if="selectedType === 'all' || selectedType === 'mcp'" class="agent-monitoring__chart-card">
          <h4 class="agent-monitoring__chart-title">Longbridge MCP 公开数据工具稳定性</h4>
          <p class="agent-monitoring__chart-desc">观察行情、新闻、财报等公开市场数据工具调用是否成功、是否返回空结果、耗时是否异常。</p>
          <div v-if="!mcpCalls.length" class="agent-monitoring__empty-chart">{{ emptyHint(' MCP 工具') }}</div>
          <div ref="mcpChartRef" class="agent-monitoring__chart"></div>
        </article>
        <article v-if="selectedType === 'all' || selectedType === 'llm'" class="agent-monitoring__chart-card agent-monitoring__chart-card--wide">
          <h4 class="agent-monitoring__chart-title">LLM 模型调用稳定性</h4>
          <p class="agent-monitoring__chart-desc">观察模型调用是否成功、耗时是否异常、失败点是否集中出现。</p>
          <div v-if="!llmCalls.length" class="agent-monitoring__empty-chart">{{ emptyHint(' LLM') }}</div>
          <div ref="llmChartRef" class="agent-monitoring__chart"></div>
        </article>
        <article v-if="selectedType === 'all' || selectedType === 'llm'" class="agent-monitoring__chart-card agent-monitoring__chart-card--wide">
          <h4 class="agent-monitoring__chart-title">LLM Token 消耗</h4>
          <p class="agent-monitoring__chart-desc">观察每次模型调用的 Token 消耗，帮助判断成本和上下文是否异常膨胀。</p>
          <div v-if="!llmCalls.length" class="agent-monitoring__empty-chart">{{ emptyHint(' LLM Token') }}</div>
          <div ref="llmTokenChartRef" class="agent-monitoring__chart"></div>
        </article>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">结构化输出质量</h3>
              <p class="panel-subtitle">观察 LLM 输出 JSON 后，schema 校验、repair、fallback 是否稳定。</p>
            </div>
            <Tag :value="`${soEvents.length} 条`" severity="info" />
          </div>
          <div v-if="soEvents.length" class="agent-monitoring__chart-card agent-monitoring__chart-card--wide">
            <div ref="soChartRef" class="agent-monitoring__chart"></div>
          </div>
          <div v-else class="empty-state">当前还没有结构化输出监控记录。请先运行一次 Account Copilot / AI 决策 / 每日复盘 / 交易复盘，然后刷新。</div>
        </div>
      </section>

      <section class="surface-panel agent-monitoring__legend-panel">
        <div class="surface-panel__content">
          <h3 class="panel-title">指标说明</h3>
          <dl class="agent-monitoring__legend-grid">
            <div><dt>调用耗时</dt><dd>单次工具或模型调用花费的时间，越高说明越慢。</dd></div>
            <div><dt>最近10次成功率</dt><dd>以当前点为结尾，向前最多统计10次调用的成功比例，用于观察短期稳定性。</dd></div>
            <div><dt>缺失字段数</dt><dd>工具返回结果中，预期字段没有被解析到的数量，越高说明数据完整性越差。</dd></div>
            <div><dt>异常点</dt><dd>调用失败、返回空结果、或解析失败的位置。</dd></div>
            <div><dt>Token 消耗</dt><dd>一次模型调用使用的输入和输出 token 总数，影响成本和上下文长度。</dd></div>
            <div><dt>修复率</dt><dd>LLM 输出格式不符合 schema 后，系统尝试修复 JSON 的比例。</dd></div>
            <div><dt>兜底率</dt><dd>修复失败或数据不足时，系统使用保守 fallback 结果的比例。</dd></div>
          </dl>
        </div>
      </section>

      <section v-if="soFailures.length" class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">结构化输出异常记录</h3>
              <p class="panel-subtitle">最近失败、repair 或 fallback 的结构化输出事件。</p>
            </div>
            <Tag :value="`${soFailures.length} 条`" severity="warn" />
          </div>
          <div class="table-shell">
            <table class="agent-monitoring__table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>Contract</th>
                  <th>Agent / 节点</th>
                  <th>状态</th>
                  <th>Repair</th>
                  <th>Fallback</th>
                  <th>错误码</th>
                  <th>run_id</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in soFailures" :key="row.id">
                  <td>{{ formatTime(row.created_at) }}</td>
                  <td class="agent-monitoring__mono">{{ row.contract_name }}</td>
                  <td>{{ row.agent_name }} / {{ row.node_name }}</td>
                  <td>
                    <Tag
                      :value="row.ok ? (row.fallback_used ? 'fallback' : row.repaired ? 'repaired' : 'success') : 'failed'"
                      :severity="row.ok ? (row.fallback_used ? 'warn' : row.repaired ? 'info' : 'success') : 'danger'"
                    />
                  </td>
                  <td>{{ row.repaired ? `${row.repair_attempts}次` : '--' }}</td>
                  <td>{{ row.fallback_used ? '是' : '--' }}</td>
                  <td>{{ row.error_code || '--' }}</td>
                  <td class="agent-monitoring__mono">{{ row.run_id || '--' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">最近失败与部分结果</h3>
              <p class="panel-subtitle">基于最近调用明细生成；字段缺失标记为 partial，不等同于调用失败。</p>
            </div>
            <Tag :value="`${recentFailures.length} 条`" severity="danger" />
          </div>

          <div v-if="recentFailures.length" class="table-shell">
            <table class="agent-monitoring__table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>Agent / 节点</th>
                  <th>类型</th>
                  <th>名称</th>
                  <th>错误码</th>
                  <th>错误信息</th>
                  <th>耗时</th>
                  <th>run / task</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="row in recentFailures" :key="failureKey(row)">
                  <tr class="agent-monitoring__failure-row" @click="toggleFailure(row)">
                    <td>{{ formatTime(row.created_at) }}</td>
                    <td>{{ row.agent_name }} / {{ row.node_name }}</td>
                    <td><Tag :value="row.partial ? 'partial' : row.kind" :severity="row.partial ? 'warn' : row.kind === 'llm' ? 'danger' : 'info'" /></td>
                    <td class="agent-monitoring__mono">{{ row.name }}</td>
                    <td>{{ row.error_code || '--' }}</td>
                    <td>{{ truncateText(row.error_message) || '--' }}</td>
                    <td>{{ formatMs(row.latency_ms) }}</td>
                    <td class="agent-monitoring__mono">{{ row.run_id || '--' }}<br />{{ row.task_id || '--' }}</td>
                  </tr>
                  <tr v-if="expandedFailure === failureKey(row)" class="agent-monitoring__detail-row">
                    <td colspan="8">
                      <pre>{{ sanitizeText(row.error_message) || '无错误详情' }}</pre>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-state">当前筛选条件下没有失败或部分结果。</div>
        </div>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <button type="button" class="agent-monitoring__collapse-button" @click="showProbeDetails = !showProbeDetails">
            <i :class="showProbeDetails ? 'pi pi-chevron-down' : 'pi pi-chevron-right'"></i>
            最近主动检测明细
          </button>

          <div v-if="showProbeDetails" class="agent-monitoring__probe-details">
            <div v-if="hasVisibleProbeResults" class="table-shell">
              <table class="agent-monitoring__table">
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Domain</th>
                    <th>Status</th>
                    <th>Latency</th>
                    <th>Error Code</th>
                    <th>Created At</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="row in visibleProbeResults" :key="row.id">
                    <tr class="agent-monitoring__failure-row" @click="toggleProbeRow(row)">
                      <td class="agent-monitoring__mono">{{ row.tool_name }}</td>
                      <td>{{ row.tool_domain }}</td>
                      <td><Tag :value="row.status.toUpperCase()" :severity="probeStatusSeverity(row.status)" /></td>
                      <td>{{ formatMs(row.latency_ms) }}</td>
                      <td>{{ row.error_code || '--' }}</td>
                      <td>{{ formatTime(row.created_at) }}</td>
                    </tr>
                    <tr v-if="expandedProbeRow === row.id" class="agent-monitoring__detail-row">
                      <td colspan="6">
                        <div v-if="row.error_message">
                          <strong>Error Message</strong>
                          <pre>{{ sanitizeText(row.error_message) }}</pre>
                        </div>
                        <div>
                          <strong>Arguments Preview</strong>
                          <pre>{{ JSON.stringify(sanitizeObject(row.arguments_preview), null, 2) }}</pre>
                        </div>
                        <div>
                          <strong>Metadata</strong>
                          <pre>{{ JSON.stringify(sanitizeObject(row.metadata), null, 2) }}</pre>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-state">暂无失败、部分成功或跳过的主动检测明细。</div>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.agent-monitoring {
  display: grid;
  gap: var(--space-4);
}

.agent-monitoring__toolbar-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.agent-monitoring__toolbar-controls {
  display: flex;
  align-items: end;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.agent-monitoring__toolbar-controls label {
  display: grid;
  gap: 5px;
  color: var(--color-text-secondary);
  font-size: 0.76rem;
}

.agent-monitoring__toolbar-controls select {
  min-height: 34px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.78);
  color: var(--color-text-primary);
  padding: 0 10px;
}

.agent-monitoring__status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.agent-monitoring__status-card {
  display: grid;
  gap: 16px;
  padding: 18px;
  border: 1px solid rgba(129, 160, 207, 0.16);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.62);
}

.agent-monitoring__status-card--healthy {
  border-color: rgba(34, 197, 94, 0.35);
}

.agent-monitoring__status-card--degraded {
  border-color: rgba(245, 158, 11, 0.38);
}

.agent-monitoring__status-card--down {
  border-color: rgba(239, 68, 68, 0.42);
}

.agent-monitoring__status-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.agent-monitoring__status-header h3 {
  margin: 0 0 6px;
  font-size: 1rem;
}

.agent-monitoring__status-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: var(--radius-sm);
  background: rgba(129, 160, 207, 0.13);
  color: #bfdbfe;
}

.agent-monitoring__status-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.agent-monitoring__status-metrics dt {
  color: var(--color-text-secondary);
  font-size: 0.76rem;
}

.agent-monitoring__status-metrics dd {
  margin: 5px 0 0;
  font-weight: 700;
}

.agent-monitoring__models {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.agent-monitoring__models span {
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: rgba(129, 160, 207, 0.12);
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.74rem;
}

.agent-monitoring__actions-header {
  align-items: center;
}

.agent-monitoring__probe-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.agent-monitoring__probe-message {
  margin: 12px 0 0;
  padding: 10px 12px;
  border: 1px solid rgba(34, 197, 94, 0.22);
  border-radius: var(--radius-sm);
  background: rgba(20, 83, 45, 0.18);
  color: #bbf7d0;
}

.agent-monitoring__chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.agent-monitoring__chart-card {
  position: relative;
  min-height: 380px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.54);
  padding: 14px;
}

.agent-monitoring__chart-card--wide {
  grid-column: 1 / -1;
}

.agent-monitoring__chart-title {
  margin: 0 0 2px;
  font-size: 0.92rem;
  font-weight: 600;
  color: var(--color-text-primary);
}

.agent-monitoring__chart-desc {
  margin: 0 0 8px;
  font-size: 0.72rem;
  color: var(--color-text-tertiary);
  line-height: 1.4;
}

.agent-monitoring__chart {
  width: 100%;
  height: 310px;
}

.agent-monitoring__empty-chart {
  position: absolute;
  inset: 108px 28px auto;
  z-index: 1;
  display: flex;
  justify-content: center;
  text-align: center;
  color: var(--color-text-secondary);
  pointer-events: none;
}

.agent-monitoring__chart-note {
  margin: 0 0 6px;
  font-size: 0.72rem;
  color: var(--color-text-tertiary);
  line-height: 1.4;
}

.agent-monitoring__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}

.agent-monitoring__table th,
.agent-monitoring__table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.12);
  text-align: left;
  vertical-align: top;
}

.agent-monitoring__table th {
  color: var(--color-text-secondary);
  font-weight: 600;
}

.agent-monitoring__failure-row {
  cursor: pointer;
}

.agent-monitoring__failure-row:hover {
  background: rgba(129, 160, 207, 0.06);
}

.agent-monitoring__detail-row pre {
  max-height: 280px;
  overflow: auto;
  margin: 8px 0;
  padding: 12px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-sm);
  background: rgba(2, 6, 23, 0.5);
  color: var(--color-text-secondary);
  white-space: pre-wrap;
}

.agent-monitoring__mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
}

.agent-monitoring__collapse-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
  color: var(--color-text-secondary);
  cursor: pointer;
  font: inherit;
  padding: 0 12px;
}

.agent-monitoring__probe-details {
  margin-top: 14px;
}

.empty-state {
  padding: 28px;
  border: 1px dashed rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  text-align: center;
}

.agent-monitoring__legend-panel {
  margin-top: 4px;
}

.agent-monitoring__legend-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px 24px;
  margin: 0;
}

.agent-monitoring__legend-grid dt {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 2px;
}

.agent-monitoring__legend-grid dd {
  margin: 0;
  font-size: 0.76rem;
  color: var(--color-text-tertiary);
  line-height: 1.45;
}

@media (max-width: 960px) {
  .agent-monitoring__status-grid,
  .agent-monitoring__chart-grid {
    grid-template-columns: 1fr;
  }

  .agent-monitoring__toolbar-controls {
    justify-content: flex-start;
  }
}
</style>
