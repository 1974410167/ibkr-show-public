<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'
import { formatLocalDateTime } from '@/utils/dateTime'

import {
  archiveEvalCase,
  bulkUpdateEvalCases,
  cloneEvalCase,
  compareEvalRuns,
  createBadCaseFeedback,
  createEvalCase,
  createEvalCaseFromFeedback,
  createEvalCaseFromLlmCall,
  createEvalCaseFromNodeTrace,
  createEvalCaseFromReplay,
  createFeedbackFromEvalRunFailures,
  exportAgentReplay,
  getAgentReplay,
  getAgentReplayByRun,
  getAgentRun,
  getEvalCase,
  getEvalRun,
  listAgentReplays,
  listAgentRuns,
  listBadCaseFeedback,
  listEvalCases,
  listEvalRuns,
  listLlmCalls,
  runAgentRegressionEval,
  runEval,
  seedEvalCases,
  unarchiveEvalCase,
  updateBadCaseFeedback,
  updateEvalCase,
} from '@/api/adminHarness'
import AgentRegressionRunPanel from '@/components/admin/AgentRegressionRunPanel.vue'
import CorrectnessSummaryPanel from '@/components/admin/CorrectnessSummaryPanel.vue'
import EvalCoverageMatrixPanel from '@/components/admin/EvalCoverageMatrixPanel.vue'
import GateReportsPanel from '@/components/admin/GateReportsPanel.vue'
import ImpactAnalysisPanel from '@/components/admin/ImpactAnalysisPanel.vue'
import RegressionProfilePanel from '@/components/admin/RegressionProfilePanel.vue'
import BadCaseFeedbackDialog from '@/components/admin/BadCaseFeedbackDialog.vue'
import EvalCaseBulkEditDialog from '@/components/admin/EvalCaseBulkEditDialog.vue'
import EvalCaseEditorDialog from '@/components/admin/EvalCaseEditorDialog.vue'
import EvalRunAnalysisPanel from '@/components/admin/EvalRunAnalysisPanel.vue'
import EvalRunCompareDialog from '@/components/admin/EvalRunCompareDialog.vue'
import HarnessDetailDialog from '@/components/admin/HarnessDetailDialog.vue'
import JsonBlock from '@/components/admin/JsonBlock.vue'
import type {
  AgentRegressionRunPayload,
  AgentRegressionRunResponse,
  AgentReplaySnapshot,
  AgentRunTraceDetail,
  AgentRunTraceListItem,
  BadCaseFeedback,
  BadCaseFeedbackCreatePayload,
  EvalCase,
  EvalCaseResult,
  EvalRun,
  LLMCallMetric,
} from '@/types/adminHarness'

type HarnessTab = 'overview' | 'coverage' | 'llm-calls' | 'agent-runs' | 'replays' | 'eval-cases' | 'eval-runs' | 'bad-case-feedback' | 'regression-profiles' | 'correctness-summary'

const router = useRouter()
const activeTab = ref<HarnessTab>('overview')
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')

const llmCalls = ref<LLMCallMetric[]>([])
const llmSummary = ref<Record<string, unknown>>({})
const agentRuns = ref<AgentRunTraceListItem[]>([])
const agentRunSummary = ref<Record<string, unknown>>({})
const replays = ref<AgentReplaySnapshot[]>([])
const replaySummary = ref<Record<string, unknown>>({})
const evalCases = ref<EvalCase[]>([])
const evalRuns = ref<EvalRun[]>([])
const evalRunSummary = ref<Record<string, unknown>>({})

const selectedLlmCall = ref<LLMCallMetric | null>(null)
const selectedRun = ref<AgentRunTraceDetail | null>(null)
const selectedReplay = ref<AgentReplaySnapshot | null>(null)
const selectedEvalCase = ref<EvalCase | null>(null)
const selectedEvalRun = ref<EvalRun | null>(null)
const selectedEvalChecks = ref<Record<string, unknown>[] | null>(null)
const selectedEvalResultMeta = ref<Record<string, unknown> | null>(null)
const exportPackage = ref<Record<string, unknown> | null>(null)
const evalActionLoading = ref(false)
const selectedEvalRunSource = ref<'replay' | 'case' | 'batch-case' | 'list' | 'agent-regression' | null>(null)
const regressionEvalLoading = ref(false)
const lastRegressionResult = ref<AgentRegressionRunResponse | null>(null)

const evalCaseEditorVisible = ref(false)
const evalCaseEditorMode = ref<'create' | 'edit'>('create')
const evalCaseEditorInitial = ref<Partial<EvalCase> | null>(null)
const evalCaseEditorSaving = ref(false)

const selectedEvalCaseIds = ref<string[]>([])
const batchEvalLoading = ref(false)

const compareBaselineRunId = ref('')
const compareCandidateRunId = ref('')
const evalRunCompareVisible = ref(false)
const evalRunCompareLoading = ref(false)
const evalRunCompareResult = ref<Record<string, unknown> | null>(null)

const llmFilters = reactive({ hours: 24, agent_name: '', prompt_key: '', model: '', ok: '', limit: 100 })
const runFilters = reactive({ hours: 24, agent_name: '', final_status: '', limit: 100 })
const replayFilters = reactive({ hours: 24, agent_name: '', final_status: '', limit: 100 })
const caseFilters = reactive({
  agent_name: '',
  source: '',
  enabled: '' as '' | 'true' | 'false',
  severity: '',
  category: '',
  tag: '',
  source_replay_id: '',
  query: '',
  limit: 100,
  eval_scope: '',
  node_name: '',
  prompt_key: '',
  model: '',
  include_archived: false,
})
const bulkEditVisible = ref(false)
const bulkEditLoading = ref(false)
const batchEvalMode = ref<'static' | 'live_mock'>('static')
const evalRunFilters = reactive({ hours: 24, agent_name: '', limit: 100 })
const coveragePanelRef = ref<InstanceType<typeof EvalCoverageMatrixPanel> | null>(null)

const feedbackList = ref<BadCaseFeedback[]>([])
const feedbackSummary = ref<Record<string, unknown>>({})
const feedbackFilters = reactive({ status: '', source_type: '', agent_name: '', severity: '', category: '', issue_type: '', tag: '', query: '', limit: 100 })
const feedbackDialogVisible = ref(false)
const feedbackDialogLoading = ref(false)
const feedbackDialogInitial = ref<Partial<BadCaseFeedbackCreatePayload> | null>(null)
const selectedFeedback = ref<BadCaseFeedback | null>(null)

const harnessTabs: { key: HarnessTab; label: string; description: string }[] = [
  {
    key: 'overview',
    label: '总览',
    description: '展示 Agent Harness 的整体运行概况，包括 Agent 执行状态、LLM 调用、工具调用、评测运行和近期异常等核心指标。',
  },
  {
    key: 'coverage',
    label: '覆盖矩阵',
    description: '展示 Eval Case 和 Eval Run 的覆盖情况，帮助判断哪些 Agent、风险等级、场景和回归用例已经被评测覆盖。',
  },
  {
    key: 'llm-calls',
    label: 'LLM 调用',
    description: '展示 LLM 调用记录，包括模型、Provider、调用类型、耗时、Token 消耗、调用状态和错误信息，用于分析模型调用成本与稳定性。',
  },
  {
    key: 'agent-runs',
    label: 'Agent 运行记录',
    description: '展示 Agent 运行记录，包括运行状态、执行耗时、调用链路、fallback、data limitations 和错误信息，用于排查单次 Agent 执行过程。',
  },
  {
    key: 'replays',
    label: '回放快照',
    description: '展示回放快照，用于还原某次 Agent 运行时的输入、上下文、工具结果和最终输出，支持问题复现与回归评测。',
  },
  {
    key: 'eval-cases',
    label: '评测用例',
    description: '管理 Agent Evaluation 的测试用例，包括输入、期望字段、禁用行为、预期工具调用和评分规则，用于沉淀 bad case 和标准样本。',
  },
  {
    key: 'eval-runs',
    label: '用例运行记录',
    description: '展示用例运行记录，包括通过率、失败用例、评分明细和错误原因，用于验证 Prompt、模型、工具或工作流变更后是否发生回归。',
  },
  {
    key: 'bad-case-feedback',
    label: '问题反馈',
    description: '记录真实 Agent 运行、Replay 或 Eval Run 中发现的问题，并将其沉淀为可回归的 Eval Case。',
  },
  {
    key: 'regression-profiles',
    label: '回归配置',
    description: '管理每个 Agent 的默认回归评测配置 Profile，包括 Gate 阈值、触发策略和回归参数，供后续自动回归和部署门禁复用。',
  },
  {
    key: 'correctness-summary',
    label: '正确性报告',
    description: '展示跨 Agent 正确性 Judge 评测的汇总报告，包括总览卡片、按 Agent / 维度聚合的失败统计和最近失败 Case，用于发现 LLM-as-Judge 中持续薄弱的维度。',
  },
]

const activeHarnessTab = computed(() => harnessTabs.find((tab) => tab.key === activeTab.value) ?? harnessTabs[0])

const overviewCards = computed(() => [
  { label: 'LLM 调用次数', value: formatNumber(summaryNumber(llmSummary.value, 'call_count', llmCalls.value.length)) },
  { label: 'LLM 成功率', value: formatRate(summaryNumber(llmSummary.value, 'success_rate', successRate(llmCalls.value, 'ok'))) },
  { label: '总 Tokens', value: formatNumber(summaryNumber(llmSummary.value, 'total_tokens', sum(llmCalls.value, 'total_tokens'))) },
  { label: '平均延迟', value: formatLatency(summaryNumber(llmSummary.value, 'avg_latency_ms', average(llmCalls.value, 'latency_ms'))) },
  { label: 'Agent Runs', value: formatNumber(summaryNumber(agentRunSummary.value, 'run_count', agentRuns.value.length)) },
  { label: 'Run 成功率', value: formatRate(summaryNumber(agentRunSummary.value, 'success_rate', statusRate(agentRuns.value, 'success'))) },
  { label: 'Replay 数量', value: formatNumber(summaryNumber(replaySummary.value, 'snapshot_count', replays.value.length)) },
  { label: 'Eval Runs', value: formatNumber(summaryNumber(evalRunSummary.value, 'run_count', evalRuns.value.length)) },
  { label: 'Eval Pass Rate', value: formatRate(latestEvalPassRate.value) },
])

const latestEvalPassRate = computed(() => {
  const latest = evalRuns.value[0]
  const summary = latest?.summary ?? {}
  return summaryNumber(summary, 'pass_rate', 0)
})

const evalRunDialogTitle = computed(() => {
  if (selectedEvalRunSource.value === 'replay') return 'Static Eval 结果'
  if (selectedEvalRunSource.value === 'case') return 'Eval Case 评测结果'
  if (selectedEvalRunSource.value === 'batch-case') return '批量 Static Eval 结果'
  if (selectedEvalRunSource.value === 'agent-regression') return 'Agent 回归评测结果'
  return 'Eval Run Detail'
})

const selectedEvalCaseCount = computed(() => selectedEvalCaseIds.value.length)

const allVisibleEvalCasesSelected = computed(() => {
  const ids = evalCases.value.map((item) => item.case_id).filter(Boolean)
  return ids.length > 0 && ids.every((id) => selectedEvalCaseIds.value.includes(id))
})

function setTab(tab: HarnessTab): void {
  activeTab.value = tab
}

function closeAllDetailDialogs(): void {
  selectedLlmCall.value = null
  selectedRun.value = null
  selectedReplay.value = null
  selectedEvalCase.value = null
  selectedEvalRun.value = null
  selectedEvalChecks.value = null
  selectedEvalResultMeta.value = null
  exportPackage.value = null
  selectedEvalRunSource.value = null
  selectedFeedback.value = null
}

async function loadCurrentTab(): Promise<void> {
  if (activeTab.value === 'overview') return loadOverview()
  if (activeTab.value === 'coverage') return loadCoverage()
  if (activeTab.value === 'llm-calls') return loadLlmCalls()
  if (activeTab.value === 'agent-runs') return loadAgentRuns()
  if (activeTab.value === 'replays') return loadReplays()
  if (activeTab.value === 'eval-cases') return loadEvalCases()
  if (activeTab.value === 'eval-runs') return loadEvalRuns()
  if (activeTab.value === 'regression-profiles') return
  if (activeTab.value === 'correctness-summary') return
  return loadFeedback()
}

async function loadOverview(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  const [llm, runs, replayList, evalRunList] = await Promise.allSettled([
    listLlmCalls({ hours: 24, limit: 100 }),
    listAgentRuns({ hours: 24, limit: 100 }),
    listAgentReplays({ hours: 24, limit: 100 }),
    listEvalRuns({ hours: 24, limit: 100 }),
  ])
  if (llm.status === 'fulfilled') {
    llmCalls.value = llm.value.items
    llmSummary.value = llm.value.summary ?? {}
  }
  if (runs.status === 'fulfilled') {
    agentRuns.value = runs.value.items
    agentRunSummary.value = runs.value.summary ?? {}
  }
  if (replayList.status === 'fulfilled') {
    replays.value = replayList.value.items
    replaySummary.value = replayList.value.summary ?? {}
  }
  if (evalRunList.status === 'fulfilled') {
    evalRuns.value = evalRunList.value.items
    evalRunSummary.value = evalRunList.value.summary ?? {}
  }
  const failed = [llm, runs, replayList, evalRunList].filter((item) => item.status === 'rejected')
  errorMessage.value = failed.length ? `${failed.length} 个 Harness 接口加载失败，其余数据已显示` : ''
  loading.value = false
}

async function loadCoverage(): Promise<void> {
  if (coveragePanelRef.value) {
    await coveragePanelRef.value.load()
  }
}

async function loadLlmCalls(): Promise<void> {
  await withLoading(async () => {
    const response = await listLlmCalls({
      ...llmFilters,
      ok: llmFilters.ok === '' ? null : llmFilters.ok === 'true',
    })
    llmCalls.value = response.items
    llmSummary.value = response.summary ?? {}
  })
}

async function loadAgentRuns(): Promise<void> {
  await withLoading(async () => {
    const response = await listAgentRuns(runFilters)
    agentRuns.value = response.items
    agentRunSummary.value = response.summary ?? {}
  })
}

async function loadReplays(): Promise<void> {
  await withLoading(async () => {
    const response = await listAgentReplays(replayFilters)
    replays.value = response.items
    replaySummary.value = response.summary ?? {}
  })
}

async function loadEvalCases(): Promise<void> {
  await withLoading(async () => {
    const params: Record<string, unknown> = { ...caseFilters }
    if (caseFilters.enabled === '') {
      delete params.enabled
    } else {
      params.enabled = caseFilters.enabled === 'true'
    }
    if (!caseFilters.include_archived) {
      delete params.include_archived
    }
    const response = await listEvalCases(params as any)
    evalCases.value = response.items
    syncEvalCaseSelectionWithList()
  })
}

async function loadEvalRuns(): Promise<void> {
  await withLoading(async () => {
    const response = await listEvalRuns(evalRunFilters)
    evalRuns.value = response.items
    evalRunSummary.value = response.summary ?? {}
  })
}

async function loadFeedback(): Promise<void> {
  await withLoading(async () => {
    const params: Record<string, unknown> = { ...feedbackFilters }
    Object.keys(params).forEach((key) => { if (params[key] === '') delete params[key] })
    const response = await listBadCaseFeedback(params as any)
    feedbackList.value = response.items
    feedbackSummary.value = response.summary ?? {}
  })
}

function openFeedbackDialog(initial?: Partial<BadCaseFeedbackCreatePayload>): void {
  closeAllDetailDialogs()
  feedbackDialogInitial.value = initial || null
  feedbackDialogVisible.value = true
}

async function handleFeedbackSave(payload: BadCaseFeedbackCreatePayload): Promise<void> {
  feedbackDialogLoading.value = true
  try {
    await createBadCaseFeedback(payload)
    feedbackDialogVisible.value = false
    noticeMessage.value = 'Bad Case 反馈已创建'
    await loadFeedback()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建反馈失败'
  } finally {
    feedbackDialogLoading.value = false
  }
}

function openFeedbackDetail(feedback: BadCaseFeedback): void {
  closeAllDetailDialogs()
  selectedFeedback.value = feedback
}

function closeFeedbackDialog(): void {
  selectedFeedback.value = null
}

async function updateFeedbackStatus(feedbackId: string, newStatus: string): Promise<void> {
  try {
    await updateBadCaseFeedback(feedbackId, { status: newStatus })
    noticeMessage.value = `反馈状态已更新为 ${newStatus}`
    selectedFeedback.value = null
    await loadFeedback()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '更新反馈状态失败'
  }
}

async function createCaseFromSelectedFeedback(): Promise<void> {
  if (!selectedFeedback.value) return
  evalActionLoading.value = true
  try {
    const caseResult = await createEvalCaseFromFeedback(selectedFeedback.value.feedback_id)
    noticeMessage.value = `Eval Case 已创建: ${caseResult.case_id}`
    selectedFeedback.value = null
    await loadFeedback()
    activeTab.value = 'eval-cases'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '从反馈创建 Eval Case 失败'
  } finally {
    evalActionLoading.value = false
  }
}

function openFeedbackFromReplay(): void {
  if (!selectedReplay.value) return
  const replay = selectedReplay.value
  openFeedbackDialog({
    source_type: 'replay',
    source_id: replay.replay_id,
    agent_name: replay.agent_name || '',
    replay_id: replay.replay_id,
    run_id: replay.run_id || undefined,
    evidence: {
      final_output: replay.final_output,
      data_limitations: replay.data_limitations,
      prompt_refs: replay.prompt_refs,
      model_config: replay.model_config,
    },
  })
}

function openFeedbackFromEvalResult(result: EvalCaseResult): void {
  if (!selectedEvalRun.value) return
  const failedChecks = (result.checks || []).filter((c) => c.passed === false).map((c) => c.check_name || '')
  openFeedbackDialog({
    source_type: 'eval_result',
    source_id: `${selectedEvalRun.value.eval_run_id}:${result.case_id}`,
    agent_name: result.agent_name || '',
    eval_run_id: selectedEvalRun.value.eval_run_id,
    case_id: result.case_id || undefined,
    result_case_id: result.case_id || undefined,
    severity: result.metadata?.severity as string || 'medium',
    category: result.metadata?.category as string || '',
    evidence: {
      status: result.status,
      score: result.score,
      max_score: result.max_score,
      failed_checks: failedChecks,
      error_code: result.error_code,
      error_message: result.error_message,
      checks: result.checks,
    },
  })
}

async function generateFeedbackFromEvalRunFailures(): Promise<void> {
  if (!selectedEvalRun.value) return
  evalActionLoading.value = true
  try {
    const result = await createFeedbackFromEvalRunFailures(selectedEvalRun.value.eval_run_id)
    noticeMessage.value = `已创建 ${result.created} 条反馈，跳过 ${result.skipped} 条重复反馈`
    await loadFeedback()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量生成反馈失败'
  } finally {
    evalActionLoading.value = false
  }
}

async function withLoading(action: () => Promise<void>): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await action()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Harness 数据加载失败'
  } finally {
    loading.value = false
  }
}

async function openRun(row: AgentRunTraceListItem): Promise<void> {
  closeAllDetailDialogs()
  selectedRun.value = await getAgentRun(row.run_id)
}

async function openReplay(row: AgentReplaySnapshot): Promise<void> {
  if (!row.replay_id) return
  closeAllDetailDialogs()
  selectedReplay.value = await getAgentReplay(row.replay_id)
}

async function openReplayByRun(runId?: string | null): Promise<void> {
  if (!runId) return
  try {
    closeAllDetailDialogs()
    const replay = await getAgentReplayByRun(runId)
    activeTab.value = 'replays'
    selectedReplay.value = replay
    noticeMessage.value = `已找到 Replay ${replay.replay_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '该 run 暂无 Replay'
  }
}

async function openEvalCase(row: EvalCase): Promise<void> {
  if (!row.case_id) return
  closeAllDetailDialogs()
  selectedEvalCase.value = await getEvalCase(row.case_id)
}

async function openEvalRun(row: EvalRun): Promise<void> {
  if (!row.eval_run_id) return
  closeAllDetailDialogs()
  selectedEvalRunSource.value = 'list'
  selectedEvalRun.value = await getEvalRun(row.eval_run_id)
}

async function openEvalRunById(evalRunId: string): Promise<void> {
  if (!evalRunId) return
  closeAllDetailDialogs()
  selectedEvalRunSource.value = 'list'
  selectedEvalRun.value = await getEvalRun(evalRunId)
  activeTab.value = 'eval-runs'
}

async function exportReplay(): Promise<void> {
  if (!selectedReplay.value?.replay_id) return
  exportPackage.value = await exportAgentReplay(selectedReplay.value.replay_id)
}

async function createCaseFromSelectedReplay(): Promise<void> {
  if (!selectedReplay.value?.replay_id) return
  try {
    const draft = await createEvalCaseFromReplay(selectedReplay.value.replay_id, false)
    closeAllDetailDialogs()
    evalCaseEditorMode.value = 'create'
    evalCaseEditorInitial.value = draft
    evalCaseEditorVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '获取 Eval Case 草稿失败'
  }
}

async function createNodeCaseFromSelectedLlmCall(): Promise<void> {
  const llm = selectedLlmCall.value
  if (!llm?.call_id || !llm?.node_name) return
  try {
    const draft = await createEvalCaseFromLlmCall(llm.call_id, false)
    closeAllDetailDialogs()
    evalCaseEditorMode.value = 'create'
    evalCaseEditorInitial.value = draft
    evalCaseEditorVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建 Node Eval Case 失败'
  }
}

async function createNodeCaseFromNodeTrace(nodeTrace: Record<string, unknown>, index: number): Promise<void> {
  const run = selectedRun.value
  if (!run?.run_id) return
  const traceId = String(
    nodeTrace.trace_id
    || nodeTrace.node_trace_id
    || nodeTrace.id
    || `index_${index}`,
  )
  if (!nodeTrace.node_name) {
    errorMessage.value = '该 node_trace 缺少 node_name，无法创建 Node Eval Case'
    return
  }
  try {
    const draft = await createEvalCaseFromNodeTrace(run.run_id, traceId, false)
    closeAllDetailDialogs()
    evalCaseEditorMode.value = 'create'
    evalCaseEditorInitial.value = draft
    evalCaseEditorVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建 Node Eval Case 失败'
  }
}

async function runEvalForReplay(): Promise<void> {
  if (!selectedReplay.value?.replay_id || evalActionLoading.value) return
  evalActionLoading.value = true
  errorMessage.value = ''
  try {
    const run = await runEval({
      replay_ids: [selectedReplay.value.replay_id],
      mode: 'static',
      name: `Static eval from replay ${selectedReplay.value.replay_id}`,
    })
    closeAllDetailDialogs()
    selectedEvalRunSource.value = 'replay'
    selectedEvalRun.value = run
    activeTab.value = 'eval-runs'
    await loadEvalRuns()
    noticeMessage.value = 'Static Eval 已完成，已打开评测结果。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Static Eval 运行失败'
  } finally {
    evalActionLoading.value = false
  }
}

async function seedCases(): Promise<void> {
  const result = await seedEvalCases(false)
  noticeMessage.value = `Seed 完成: created=${result.created_count ?? 0}, skipped=${result.skipped_count ?? 0}`
  await loadEvalCases()
}

async function runEvalForCase(caseId?: string): Promise<void> {
  if (!caseId || evalActionLoading.value) return
  evalActionLoading.value = true
  errorMessage.value = ''
  try {
    const run = await runEval({
      case_ids: [caseId],
      mode: 'static',
      name: `Static eval case ${caseId}`,
    })
    closeAllDetailDialogs()
    selectedEvalRunSource.value = 'case'
    selectedEvalRun.value = run
    activeTab.value = 'eval-runs'
    await loadEvalRuns()
    noticeMessage.value = 'Eval Case 评测已完成，已打开评测结果。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Eval Case 评测运行失败'
  } finally {
    evalActionLoading.value = false
  }
}

async function runLiveMockForCase(caseId?: string): Promise<void> {
  if (!caseId || evalActionLoading.value) return
  if (!window.confirm('确认运行 Live Mock Eval 吗？Live Mock 会基于 mock 数据用评测 Prompt 重新生成输出，不读取真实账户/行情；当前不是完整 Agent Graph 重跑。')) return
  evalActionLoading.value = true
  errorMessage.value = ''
  try {
    const run = await runEval({
      case_ids: [caseId],
      mode: 'live_mock',
      name: `Live Mock eval case ${caseId}`,
    })
    closeAllDetailDialogs()
    selectedEvalRunSource.value = 'case'
    selectedEvalRun.value = run
    activeTab.value = 'eval-runs'
    await loadEvalRuns()
    noticeMessage.value = 'Live Mock Eval 已完成，已打开评测结果。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Live Mock Eval 运行失败'
  } finally {
    evalActionLoading.value = false
  }
}

function openChecks(result: EvalCaseResult): void {
  selectedEvalChecks.value = (result.checks as Record<string, unknown>[] | undefined) ?? []
  selectedEvalResultMeta.value = result.metadata ? { ...result.metadata } : null
}

async function openEditEvalCase(): Promise<void> {
  if (!selectedEvalCase.value?.case_id) return
  evalCaseEditorMode.value = 'edit'
  evalCaseEditorInitial.value = selectedEvalCase.value
  selectedEvalCase.value = null
  evalCaseEditorVisible.value = true
}

function openEditEvalCaseDirect(evalCase: EvalCase): void {
  evalCaseEditorMode.value = 'edit'
  evalCaseEditorInitial.value = evalCase
  evalCaseEditorVisible.value = true
}

async function handleEvalCaseSave(payload: Record<string, unknown>): Promise<void> {
  evalCaseEditorSaving.value = true
  try {
    if (evalCaseEditorMode.value === 'create') {
      await createEvalCase(payload)
      noticeMessage.value = 'Eval Case 已保存'
    } else {
      const caseId = evalCaseEditorInitial.value?.case_id
      if (!caseId) return
      await updateEvalCase(caseId, payload)
      noticeMessage.value = 'Eval Case 已更新'
    }
    evalCaseEditorVisible.value = false
    await loadEvalCases()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存 Eval Case 失败'
  } finally {
    evalCaseEditorSaving.value = false
  }
}

function closeEvalCaseEditor(visible: boolean): void {
  if (!visible) {
    evalCaseEditorVisible.value = false
    evalCaseEditorInitial.value = null
  }
}

function toggleEvalCaseSelection(caseId?: string | null): void {
  if (!caseId) return
  const index = selectedEvalCaseIds.value.indexOf(caseId)
  if (index >= 0) {
    selectedEvalCaseIds.value.splice(index, 1)
  } else {
    selectedEvalCaseIds.value.push(caseId)
  }
}

function toggleAllVisibleEvalCases(): void {
  const ids = evalCases.value.map((item) => item.case_id).filter(Boolean) as string[]
  if (allVisibleEvalCasesSelected.value) {
    selectedEvalCaseIds.value = []
  } else {
    selectedEvalCaseIds.value = [...ids]
  }
}

function syncEvalCaseSelectionWithList(): void {
  const currentIds = new Set(evalCases.value.map((c) => c.case_id).filter(Boolean))
  selectedEvalCaseIds.value = selectedEvalCaseIds.value.filter((id) => currentIds.has(id))
}

async function runBatchEvalForSelectedCases(): Promise<void> {
  if (!selectedEvalCaseIds.value.length || batchEvalLoading.value) return
  const count = selectedEvalCaseIds.value.length
  const mode = batchEvalMode.value
  const modeLabel = mode === 'live_mock' ? 'Live Mock Eval' : 'Static Eval'
  const confirmMsg = mode === 'live_mock'
    ? `确认对已选择的 ${count} 个 Eval Case 运行 Live Mock Eval 吗？基于 mock 数据用评测 Prompt 重新生成输出，不读取真实数据；当前不是完整 Agent Graph 重跑。`
    : `确认对已选择的 ${count} 个 Eval Case 运行 Static Eval 吗？`
  if (!window.confirm(confirmMsg)) return
  batchEvalLoading.value = true
  errorMessage.value = ''
  try {
    const name = `Batch ${modeLabel} - ${count} cases - ${formatLocalDateTime(new Date().toISOString())}`
    const run = await runEval({
      case_ids: selectedEvalCaseIds.value,
      mode,
      name,
    })
    selectedEvalCaseIds.value = []
    activeTab.value = 'eval-runs'
    selectedEvalRunSource.value = 'batch-case'
    selectedEvalRun.value = run
    await loadEvalRuns()
    noticeMessage.value = `批量 ${modeLabel} 已完成，已打开评测结果。`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `批量 ${modeLabel} 运行失败`
  } finally {
    batchEvalLoading.value = false
  }
}

async function handleRunAgentRegression(payload: AgentRegressionRunPayload): Promise<void> {
  regressionEvalLoading.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await runAgentRegressionEval(payload)
    lastRegressionResult.value = result
    await loadEvalRuns()
    selectedEvalRunSource.value = 'agent-regression'
    selectedEvalRun.value = result.eval_run
    activeTab.value = 'eval-runs'
    noticeMessage.value = result.gate_result?.passed
      ? 'Agent 回归评测通过，已打开运行结果。'
      : 'Agent 回归评测未通过，请查看失败原因。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Agent 回归评测运行失败'
  } finally {
    regressionEvalLoading.value = false
  }
}

async function bulkEnableSelectedCases(): Promise<void> {
  if (!selectedEvalCaseIds.value.length) return
  const count = selectedEvalCaseIds.value.length
  if (!window.confirm(`确认批量启用 ${count} 个 Eval Case 吗？`)) return
  await withLoading(async () => {
    await bulkUpdateEvalCases({ case_ids: selectedEvalCaseIds.value, updates: { enabled: true } })
    selectedEvalCaseIds.value = []
    await loadEvalCases()
    noticeMessage.value = '批量启用成功'
  })
}

async function bulkDisableSelectedCases(): Promise<void> {
  if (!selectedEvalCaseIds.value.length) return
  const count = selectedEvalCaseIds.value.length
  if (!window.confirm(`确认批量禁用 ${count} 个 Eval Case 吗？`)) return
  await withLoading(async () => {
    await bulkUpdateEvalCases({ case_ids: selectedEvalCaseIds.value, updates: { enabled: false } })
    selectedEvalCaseIds.value = []
    await loadEvalCases()
    noticeMessage.value = '批量禁用成功'
  })
}

function openBulkEditDialog(): void {
  if (!selectedEvalCaseIds.value.length) return
  bulkEditVisible.value = true
}

async function handleBulkEditSave(payload: Record<string, unknown>): Promise<void> {
  bulkEditLoading.value = true
  errorMessage.value = ''
  try {
    const result = await bulkUpdateEvalCases({ case_ids: selectedEvalCaseIds.value, updates: payload as any })
    bulkEditVisible.value = false
    selectedEvalCaseIds.value = []
    await loadEvalCases()
    noticeMessage.value = `批量更新完成：${result.updated_count} 成功，${result.failed_count} 失败`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量更新失败'
  } finally {
    bulkEditLoading.value = false
  }
}

async function cloneEvalCaseFromDetail(): Promise<void> {
  if (!selectedEvalCase.value) return
  evalActionLoading.value = true
  errorMessage.value = ''
  try {
    const cloned = await cloneEvalCase(selectedEvalCase.value.case_id)
    closeEvalCaseDialog(false)
    await loadEvalCases()
    openEditEvalCaseDirect(cloned)
    noticeMessage.value = 'Eval Case 已复制，请编辑新 Case'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复制 Eval Case 失败'
  } finally {
    evalActionLoading.value = false
  }
}

async function toggleArchiveEvalCaseFromDetail(): Promise<void> {
  const current = selectedEvalCase.value
  if (!current?.case_id || evalActionLoading.value) return
  const archived = current.archived === true
  const confirmMsg = archived
    ? `确认取消归档 Eval Case ${current.case_id} 吗？`
    : `确认归档 Eval Case ${current.case_id} 吗？归档后会同时禁用该 Case，默认列表和回归评测不会再选择它。`
  if (!window.confirm(confirmMsg)) return
  evalActionLoading.value = true
  errorMessage.value = ''
  try {
    const updated = archived
      ? await unarchiveEvalCase(current.case_id)
      : await archiveEvalCase(current.case_id, 'online verification cleanup')
    selectedEvalCase.value = updated
    await loadEvalCases()
    noticeMessage.value = archived ? 'Eval Case 已取消归档' : 'Eval Case 已归档'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : archived ? '取消归档失败' : '归档 Eval Case 失败'
  } finally {
    evalActionLoading.value = false
  }
}

async function navigateToEvalCase(caseId: string): Promise<void> {
  errorMessage.value = ''
  try {
    const evalCase = await getEvalCase(caseId)
    closeAllDetailDialogs()
    activeTab.value = 'eval-cases'
    selectedEvalCase.value = evalCase
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `Eval Case ${caseId} 不存在`
  }
}

async function runEvalRunCompare(): Promise<void> {
  if (!compareBaselineRunId.value || !compareCandidateRunId.value) return
  if (compareBaselineRunId.value === compareCandidateRunId.value) {
    errorMessage.value = 'Baseline 和 Candidate 不能相同'
    return
  }
  evalRunCompareLoading.value = true
  evalRunCompareResult.value = null
  errorMessage.value = ''
  try {
    closeAllDetailDialogs()
    evalRunCompareResult.value = await compareEvalRuns({
      baseline_run_id: compareBaselineRunId.value,
      candidate_run_id: compareCandidateRunId.value,
    })
    evalRunCompareVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Eval Run 对比失败'
  } finally {
    evalRunCompareLoading.value = false
  }
}

function closeEvalRunCompareDialog(visible: boolean): void {
  if (!visible) {
    evalRunCompareVisible.value = false
    evalRunCompareResult.value = null
  }
}

function formatDateTime(value?: string | null): string {
  return formatLocalDateTime(value)
}

function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatLatency(value?: number | null): string {
  return value === null || value === undefined ? '-' : `${formatNumber(Math.round(value))} ms`
}

function formatCost(value?: number | null): string {
  return value === null || value === undefined ? '-' : `$${value.toFixed(6)}`
}

function formatRate(value?: number | null): string {
  return value === null || value === undefined || Number.isNaN(value) ? '-' : `${(value * 100).toFixed(1)}%`
}

function summaryNumber(summary: Record<string, unknown>, key: string, fallback = 0): number {
  const value = summary[key]
  return typeof value === 'number' ? value : fallback
}

function sum<T extends Record<string, unknown>>(items: T[], key: string): number {
  return items.reduce((total, item) => total + (typeof item[key] === 'number' ? (item[key] as number) : 0), 0)
}

function average<T extends Record<string, unknown>>(items: T[], key: string): number {
  return items.length ? sum(items, key) / items.length : 0
}

function successRate<T extends Record<string, unknown>>(items: T[], key: string): number {
  return items.length ? items.filter((item) => item[key] === true).length / items.length : 0
}

function statusRate(items: AgentRunTraceListItem[], status: string): number {
  return items.length ? items.filter((item) => item.final_status === status).length / items.length : 0
}

function statusClass(status?: string | null): string {
  if (status === 'success' || status === 'passed' || status === 'completed') return 'p-tag--positive'
  if (status === 'warning' || status === 'partial') return 'p-tag--warning'
  if (status === 'failed' || status === 'error') return 'p-tag--negative'
  return 'p-tag--accent'
}

function severityClass(severity?: string | null): string {
  if (severity === 'critical') return 'p-tag--negative'
  if (severity === 'high') return 'p-tag--warning'
  if (severity === 'low') return 'p-tag--positive'
  return 'p-tag--accent'
}

function compactList(value?: unknown[]): string {
  return value?.length ? value.join(', ') : '-'
}

function compactText(value: string | null | undefined, max: number): string {
  if (!value) return '-'
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

function closeLlmCallDialog(visible: boolean): void {
  if (!visible) selectedLlmCall.value = null
}

function closeRunDialog(visible: boolean): void {
  if (!visible) selectedRun.value = null
}

function closeReplayDialog(visible: boolean): void {
  if (!visible) {
    selectedReplay.value = null
    exportPackage.value = null
  }
}

function closeEvalCaseDialog(visible: boolean): void {
  if (!visible) selectedEvalCase.value = null
}

function closeEvalRunDialog(visible: boolean): void {
  if (!visible) {
    selectedEvalRun.value = null
    selectedEvalChecks.value = null
    selectedEvalResultMeta.value = null
  }
}

onMounted(() => {
  void loadOverview()
})

watch(activeTab, () => {
  void loadCurrentTab()
})
</script>

<template>
  <section class="page-section admin-harness-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-harness-page__title">Harness 控制台</h2>
            <p class="panel-subtitle">观察 Agent 的 LLM 调用、运行链路、Replay 快照和 Eval 结果。时间按浏览器本地时区展示。</p>
          </div>
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="系统状态" icon="pi pi-heart" class="terminal-nav__button" @click="router.push('/admin/system')" />
          <Button label="Agent 监控" icon="pi pi-chart-line" class="terminal-nav__button" @click="router.push('/admin/agent-monitoring')" />
          <Button label="Prompt 管理" icon="pi pi-file-edit" class="terminal-nav__button" @click="router.push('/admin/prompts')" />
          <Button label="Harness 控制台" icon="pi pi-sitemap" class="terminal-nav__button is-active" />
        </nav>
      </div>
    </section>

    <section class="surface-panel">
      <div class="surface-panel__content harness-tab-panel">
        <div class="harness-toolbar">
          <div class="harness-tabs">
            <button
              v-for="tab in harnessTabs"
              :key="tab.key"
              type="button"
              :class="{ 'is-active': activeTab === tab.key }"
              @click="setTab(tab.key)"
            >
              {{ tab.label }}
            </button>
          </div>
          <Button label="Reload" icon="pi pi-refresh" severity="secondary" :loading="loading" @click="loadCurrentTab" />
        </div>
        <article class="harness-tab-description">
          <strong>{{ activeHarnessTab.label }}</strong>
          <p>{{ activeHarnessTab.description }}</p>
        </article>
      </div>
    </section>

    <p v-if="noticeMessage" class="harness-message harness-message--notice">{{ noticeMessage }}</p>
    <p v-if="errorMessage" class="harness-message harness-message--error">{{ errorMessage }}</p>

    <section v-if="activeTab === 'overview'" class="harness-stack">
      <div class="overview-grid">
        <article v-for="card in overviewCards" :key="card.label" class="surface-panel overview-card">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </article>
      </div>

      <section class="overview-columns">
        <article class="surface-panel">
          <div class="surface-panel__content">
            <h3 class="panel-title">最近 LLM Calls</h3>
            <table class="harness-table">
              <tbody>
                <tr v-for="item in llmCalls.slice(0, 5)" :key="item.call_id" @click="selectedLlmCall = item">
                  <td>{{ formatDateTime(item.created_at) }}</td>
                  <td>{{ item.agent_name || '-' }}</td>
                  <td>{{ item.model || '-' }}</td>
                  <td>{{ formatNumber(item.total_tokens) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!llmCalls.length" class="empty-state">暂无 LLM 调用</div>
          </div>
        </article>
        <article class="surface-panel">
          <div class="surface-panel__content">
            <h3 class="panel-title">最近 Agent Runs</h3>
            <table class="harness-table">
              <tbody>
                <tr v-for="item in agentRuns.slice(0, 5)" :key="item.run_id" @click="openRun(item)">
                  <td>{{ formatDateTime(item.started_at) }}</td>
                  <td>{{ item.agent_name || '-' }}</td>
                  <td><Tag :value="item.final_status || '-'" :class="statusClass(item.final_status)" /></td>
                  <td>{{ formatLatency(item.latency_ms) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!agentRuns.length" class="empty-state">暂无 Agent Run</div>
          </div>
        </article>
        <article class="surface-panel">
          <div class="surface-panel__content">
            <h3 class="panel-title">最近 Eval Runs</h3>
            <table class="harness-table">
              <tbody>
                <tr v-for="item in evalRuns.slice(0, 5)" :key="item.eval_run_id" @click="openEvalRun(item)">
                  <td>{{ formatDateTime(item.started_at) }}</td>
                  <td>{{ item.name || '-' }}</td>
                  <td><Tag :value="item.status || '-'" :class="statusClass(item.status)" /></td>
                  <td>{{ formatRate(summaryNumber(item.summary || {}, 'pass_rate', 0)) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!evalRuns.length" class="empty-state">暂无 Eval Run</div>
          </div>
        </article>
      </section>
    </section>

    <section v-else-if="activeTab === 'coverage'" class="surface-panel">
      <div class="surface-panel__content">
        <EvalCoverageMatrixPanel
          ref="coveragePanelRef"
          @open-case="(caseId) => { activeTab = 'eval-cases'; navigateToEvalCase(caseId) }"
          @open-run="openEvalRunById"
          @filter-agent="(agent) => { coveragePanelRef?.$el; }"
        />
      </div>
    </section>

    <section v-else-if="activeTab === 'llm-calls'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <input v-model.number="llmFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="llmFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="llmFilters.prompt_key" placeholder="prompt_key" />
          <InputText v-model="llmFilters.model" placeholder="model" />
          <select v-model="llmFilters.ok"><option value="">ok: all</option><option value="true">success</option><option value="false">failed</option></select>
          <input v-model.number="llmFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadLlmCalls" />
        </div>
        <table class="harness-table">
          <thead><tr><th>created_at</th><th>agent</th><th>node</th><th>model</th><th>prompt</th><th>version</th><th>tokens</th><th>latency</th><th>cost</th><th>ok</th><th>error</th></tr></thead>
          <tbody>
            <tr v-for="item in llmCalls" :key="item.call_id" @click="selectedLlmCall = item">
              <td>{{ formatDateTime(item.created_at) }}</td><td>{{ item.agent_name || '-' }}</td><td>{{ item.node_name || '-' }}</td><td>{{ item.model || '-' }}</td><td>{{ item.prompt_key || '-' }}</td><td>{{ item.prompt_version || '-' }}</td><td>{{ formatNumber(item.total_tokens) }}</td><td>{{ formatLatency(item.latency_ms) }}</td><td>{{ formatCost(item.estimated_cost) }}</td><td><Tag :value="item.ok ? 'SUCCESS' : 'FAILED'" :class="item.ok ? 'p-tag--positive' : 'p-tag--negative'" /></td><td>{{ item.error_code || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!llmCalls.length" class="empty-state">暂无 LLM 调用</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'agent-runs'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <input v-model.number="runFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="runFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="runFilters.final_status" placeholder="final_status" />
          <input v-model.number="runFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadAgentRuns" />
        </div>
        <table class="harness-table">
          <thead><tr><th>started_at</th><th>agent</th><th>status</th><th>latency</th><th>llm</th><th>tools</th><th>tokens</th><th>cost</th><th>prompts</th><th>run_id</th></tr></thead>
          <tbody>
            <tr v-for="item in agentRuns" :key="item.run_id" @click="openRun(item)">
              <td>{{ formatDateTime(item.started_at) }}</td><td>{{ item.agent_name || '-' }}</td><td><Tag :value="item.final_status || '-'" :class="statusClass(item.final_status)" /></td><td>{{ formatLatency(item.latency_ms) }}</td><td>{{ item.llm_call_count ?? 0 }}</td><td>{{ item.tool_call_count ?? 0 }}</td><td>{{ formatNumber(item.total_tokens) }}</td><td>{{ formatCost(item.estimated_cost) }}</td><td>{{ compactList(item.prompt_keys) }}</td><td><code>{{ item.run_id }}</code></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!agentRuns.length" class="empty-state">暂无 Agent Run</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'replays'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <input v-model.number="replayFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="replayFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="replayFilters.final_status" placeholder="final_status" />
          <input v-model.number="replayFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadReplays" />
        </div>
        <table class="harness-table">
          <thead><tr><th>created_at</th><th>agent</th><th>status</th><th>run_id</th><th>replay_id</th><th>prompts</th><th>model</th><th>document</th></tr></thead>
          <tbody>
            <tr v-for="item in replays" :key="item.replay_id" @click="openReplay(item)">
              <td>{{ formatDateTime(item.created_at) }}</td><td>{{ item.agent_name || '-' }}</td><td><Tag :value="item.final_status || '-'" :class="statusClass(item.final_status)" /></td><td><code>{{ item.run_id || '-' }}</code></td><td><code>{{ item.replay_id }}</code></td><td>{{ compactList((item.prompt_refs || []).map((p) => String(p.prompt_key || ''))) }}</td><td>{{ item.model_config?.model || '-' }}</td><td>{{ item.persisted_document_id || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!replays.length" class="empty-state">暂无 Replay Snapshot</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'eval-cases'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <InputText v-model="caseFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="caseFilters.source" placeholder="source" />
          <select v-model="caseFilters.enabled"><option value="">enabled: all</option><option value="true">启用</option><option value="false">禁用</option></select>
          <select v-model="caseFilters.severity"><option value="">severity: all</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="critical">critical</option></select>
          <InputText v-model="caseFilters.category" placeholder="category" />
          <InputText v-model="caseFilters.tag" placeholder="tag" />
          <InputText v-model="caseFilters.source_replay_id" placeholder="source_replay_id" />
          <select v-model="caseFilters.eval_scope" data-testid="case-filter-eval-scope">
            <option value="">scope: all</option>
            <option value="agent">agent</option>
            <option value="node">node</option>
          </select>
          <InputText v-model="caseFilters.node_name" placeholder="node_name" data-testid="case-filter-node-name" />
          <InputText v-model="caseFilters.prompt_key" placeholder="prompt_key" />
          <InputText v-model="caseFilters.model" placeholder="model" />
          <InputText v-model="caseFilters.query" placeholder="搜索 title/case_id/notes" />
          <input v-model.number="caseFilters.limit" type="number" placeholder="limit" />
          <label class="checkbox-filter">
            <input v-model="caseFilters.include_archived" type="checkbox" />
            <span>Include Archived</span>
          </label>
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadEvalCases" />
          <Button label="Seed 内置 Cases" icon="pi pi-database" severity="secondary" @click="seedCases" />
        </div>
        <div v-if="selectedEvalCaseCount > 0" class="batch-actions">
          <span>已选择 {{ selectedEvalCaseCount }} 个 Eval Case</span>
          <select v-model="batchEvalMode">
            <option value="static">Static Eval</option>
            <option value="live_mock">Live Mock Eval</option>
          </select>
          <Button :label="`运行 ${batchEvalMode === 'live_mock' ? 'Live Mock' : 'Static'} Eval`" icon="pi pi-play" class="p-button--accent" :loading="batchEvalLoading" :disabled="batchEvalLoading" @click="runBatchEvalForSelectedCases" />
          <Button label="批量启用" icon="pi pi-check" severity="secondary" :disabled="loading" @click="bulkEnableSelectedCases" />
          <Button label="批量禁用" icon="pi pi-ban" severity="secondary" :disabled="loading" @click="bulkDisableSelectedCases" />
          <Button label="批量编辑" icon="pi pi-pencil" severity="secondary" :disabled="loading" @click="openBulkEditDialog" />
        </div>
        <table class="harness-table">
          <thead>
            <tr>
              <th class="harness-table__checkbox-col"><input type="checkbox" :checked="allVisibleEvalCasesSelected" @change="toggleAllVisibleEvalCases" @click.stop /></th>
              <th>case_id</th><th>agent</th><th>scope</th><th>node_name</th><th>title</th><th>enabled</th><th>archived</th><th>severity</th><th>category</th><th>source</th><th>prompt_key</th><th>model</th><th>tags</th><th>judge</th><th>updated_at</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in evalCases" :key="item.case_id" @click="openEvalCase(item)">
              <td class="harness-table__checkbox-col"><input type="checkbox" :checked="selectedEvalCaseIds.includes(item.case_id)" @change="toggleEvalCaseSelection(item.case_id)" @click.stop /></td>
              <td><code>{{ item.case_id }}</code></td>
              <td>{{ item.agent_name || '-' }}</td>
              <td>
                <Tag v-if="item.eval_scope === 'node'" value="NODE" class="p-tag--info" data-testid="case-scope-node" />
                <Tag v-else value="AGENT" class="p-tag--secondary" data-testid="case-scope-agent" />
              </td>
              <td>{{ item.node_name || '-' }}</td>
              <td>{{ item.title || '-' }}</td>
              <td><Tag :value="item.enabled === false ? '禁用' : '启用'" :class="item.enabled === false ? 'p-tag--warning' : 'p-tag--positive'" /></td>
              <td><Tag v-if="item.archived" value="已归档" class="p-tag--secondary" /><span v-else>-</span></td>
              <td>{{ item.severity || '-' }}</td>
              <td>{{ item.category || '-' }}</td>
              <td>{{ item.source || '-' }}</td>
              <td :title="item.prompt_key || ''">{{ compactText(item.prompt_key, 24) }}</td>
              <td>{{ item.model || '-' }}</td>
              <td>{{ compactList(item.tags) }}</td>
              <td><Tag v-if="item.judge_enabled" value="LLM Judge" class="p-tag--info" /><span v-else>-</span></td>
              <td>{{ formatDateTime(item.updated_at || item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!evalCases.length" class="empty-state">暂无 Eval Case</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'eval-runs'" class="surface-panel">
      <div class="surface-panel__content">
        <AgentRegressionRunPanel
          :eval-runs="evalRuns"
          :loading="regressionEvalLoading"
          @run="handleRunAgentRegression"
        />
        <div class="filter-row">
          <input v-model.number="evalRunFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="evalRunFilters.agent_name" placeholder="agent_name" />
          <input v-model.number="evalRunFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadEvalRuns" />
        </div>
        <div class="filter-row">
          <select v-model="compareBaselineRunId">
            <option value="">Baseline Run</option>
            <option v-for="run in evalRuns" :key="run.eval_run_id" :value="run.eval_run_id">{{ run.name || run.eval_run_id }}</option>
          </select>
          <select v-model="compareCandidateRunId">
            <option value="">Candidate Run</option>
            <option v-for="run in evalRuns" :key="run.eval_run_id" :value="run.eval_run_id">{{ run.name || run.eval_run_id }}</option>
          </select>
          <Button label="对比 Eval Run" icon="pi pi-objects-column" class="p-button--accent" :loading="evalRunCompareLoading" :disabled="!compareBaselineRunId || !compareCandidateRunId || compareBaselineRunId === compareCandidateRunId" @click="runEvalRunCompare" />
        </div>
        <table class="harness-table">
          <thead><tr><th>started_at</th><th>name</th><th>agent</th><th>status</th><th>cases</th><th>passed</th><th>warning</th><th>failed</th><th>error</th><th>pass_rate</th><th>eval_run_id</th></tr></thead>
          <tbody>
            <tr v-for="item in evalRuns" :key="item.eval_run_id" @click="openEvalRun(item)">
              <td>{{ formatDateTime(item.started_at) }}</td><td>{{ item.name || '-' }}</td><td>{{ item.agent_name || '-' }}</td><td><Tag :value="item.status || '-'" :class="statusClass(item.status)" /></td><td>{{ item.summary?.case_count ?? '-' }}</td><td>{{ item.summary?.passed_count ?? '-' }}</td><td>{{ item.summary?.warning_count ?? '-' }}</td><td>{{ item.summary?.failed_count ?? '-' }}</td><td>{{ item.summary?.error_count ?? '-' }}</td><td>{{ formatRate(summaryNumber(item.summary || {}, 'pass_rate', 0)) }}</td><td><code>{{ item.eval_run_id }}</code></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!evalRuns.length" class="empty-state">暂无 Eval Run</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'bad-case-feedback'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <select v-model="feedbackFilters.status">
            <option value="">全部状态</option>
            <option value="open">open</option>
            <option value="triaged">triaged</option>
            <option value="converted">converted</option>
            <option value="ignored">ignored</option>
            <option value="resolved">resolved</option>
          </select>
          <select v-model="feedbackFilters.source_type">
            <option value="">全部来源</option>
            <option value="replay">replay</option>
            <option value="agent_run">agent_run</option>
            <option value="eval_result">eval_result</option>
            <option value="manual">manual</option>
          </select>
          <select v-model="feedbackFilters.severity">
            <option value="">全部等级</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
          <select v-model="feedbackFilters.issue_type">
            <option value="">全部问题类型</option>
            <option value="wrong_answer">wrong_answer</option>
            <option value="missing_risk">missing_risk</option>
            <option value="overconfident">overconfident</option>
            <option value="tool_error">tool_error</option>
            <option value="format_error">format_error</option>
            <option value="hallucination">hallucination</option>
            <option value="bad_reasoning">bad_reasoning</option>
            <option value="unsafe_investment_advice">unsafe_investment_advice</option>
            <option value="other">other</option>
          </select>
          <InputText v-model="feedbackFilters.query" placeholder="搜索标题/描述" @keyup.enter="loadFeedback" />
          <Button label="搜索" icon="pi pi-search" severity="secondary" @click="loadFeedback" />
          <Button label="新建反馈" icon="pi pi-plus" class="p-button--accent" @click="openFeedbackDialog()" />
        </div>
        <table class="harness-table">
          <thead><tr><th>created_at</th><th>status</th><th>severity</th><th>issue_type</th><th>agent</th><th>title</th><th>source</th><th>converted</th></tr></thead>
          <tbody>
            <tr v-for="fb in feedbackList" :key="fb.feedback_id" @click="openFeedbackDetail(fb)">
              <td>{{ formatDateTime(fb.created_at) }}</td>
              <td><Tag :value="fb.status || '-'" :class="statusClass(fb.status)" /></td>
              <td><Tag :value="fb.severity || '-'" :class="severityClass(fb.severity)" /></td>
              <td>{{ fb.issue_type || '-' }}</td>
              <td>{{ fb.agent_name || '-' }}</td>
              <td>{{ fb.title || '-' }}</td>
              <td>{{ fb.source_type || '-' }}</td>
              <td><code v-if="fb.converted_case_id" class="clickable" @click.stop="navigateToEvalCase(fb.converted_case_id)">{{ fb.converted_case_id }}</code><span v-else>-</span></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!feedbackList.length" class="empty-state">暂无 Bad Case 反馈</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'regression-profiles'" class="harness-stack">
      <div class="surface-panel">
        <div class="surface-panel__content">
          <h3 class="panel-title">回归配置</h3>
          <RegressionProfilePanel />
        </div>
      </div>
      <div class="surface-panel">
        <div class="surface-panel__content">
          <h3 class="panel-title">代码变更影响分析</h3>
          <ImpactAnalysisPanel />
        </div>
      </div>
      <div class="surface-panel">
        <div class="surface-panel__content">
          <h3 class="panel-title">部署 Gate 报告</h3>
          <GateReportsPanel />
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'correctness-summary'" class="harness-stack">
      <div class="surface-panel">
        <div class="surface-panel__content">
          <h3 class="panel-title">跨 Agent 正确性报告</h3>
          <p class="panel-description">
            基于 LLM-as-Judge（correctness_judge_enabled）的最近评测汇总。展示每个 Agent / 维度的失败统计和最近失败 Case，用于发现持续薄弱的维度。
          </p>
          <CorrectnessSummaryPanel />
        </div>
      </div>
    </section>

    <HarnessDetailDialog :visible="Boolean(selectedLlmCall)" header="LLM Call Detail" @update:visible="closeLlmCallDialog">
      <template #default="{ registerBlock }">
        <template v-if="selectedLlmCall">
          <div class="dialog-actions">
            <Button
              label="创建 Node Eval Case"
              icon="pi pi-sitemap"
              severity="secondary"
              :disabled="!selectedLlmCall.node_name"
              :title="selectedLlmCall.node_name ? '基于该 LLM Call 创建 Node Eval Case' : '该 LLM Call 缺少 node_name，无法创建 Node Eval Case'"
              @click="createNodeCaseFromSelectedLlmCall"
            />
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="LLM Call" :value="selectedLlmCall" collapsed />
        </template>
      </template>
    </HarnessDetailDialog>

    <HarnessDetailDialog :visible="Boolean(selectedRun)" header="Agent Run Detail" @update:visible="closeRunDialog">
      <template #default="{ registerBlock }">
        <template v-if="selectedRun">
          <div class="dialog-actions">
            <Button label="查看 Replay" icon="pi pi-history" severity="secondary" @click="openReplayByRun(selectedRun.run_id)" />
            <Button label="标记 Bad Case" icon="pi pi-exclamation-triangle" severity="warning" @click="openFeedbackDialog({ source_type: 'agent_run', source_id: selectedRun.run_id, agent_name: selectedRun.agent_name || '', run_id: selectedRun.run_id, evidence: { final_status: selectedRun.final_status, error_code: selectedRun.error_code, error_message: selectedRun.error_message, data_limitations: selectedRun.metadata?.data_limitations } })" />
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="基本信息" :value="{ run_id: selectedRun.run_id, agent_name: selectedRun.agent_name, final_status: selectedRun.final_status, latency_ms: selectedRun.latency_ms }" />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="prompt_metadata" :value="selectedRun.prompt_metadata" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="llm_calls" :value="selectedRun.llm_calls" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="tool_calls" :value="selectedRun.tool_calls" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="validation / fallback" :value="{ validation: selectedRun.validation, fallback: selectedRun.fallback, repair_attempts: selectedRun.repair_attempts }" collapsed />
          <div v-if="Array.isArray(selectedRun.node_traces) && selectedRun.node_traces.length" class="node-traces-actions">
            <div class="node-traces-actions__title">Node Traces（点击节点创建 Node Eval Case）</div>
            <table class="node-traces-table">
              <thead>
                <tr>
                  <th>node_name</th>
                  <th>status</th>
                  <th>latency_ms</th>
                  <th>trace_id</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(trace, idx) in (selectedRun.node_traces as Record<string, unknown>[])" :key="String(trace.trace_id || trace.node_trace_id || trace.id || `index_${idx}`)">
                  <td>{{ trace.node_name || '-' }}</td>
                  <td>{{ trace.status || '-' }}</td>
                  <td>{{ trace.latency_ms ?? '-' }}</td>
                  <td>{{ String(trace.trace_id || trace.node_trace_id || trace.id || `index_${idx}`) }}</td>
                  <td>
                    <Button
                      label="创建 Node Eval Case"
                      icon="pi pi-sitemap"
                      size="small"
                      severity="secondary"
                      :disabled="!trace.node_name"
                      @click="createNodeCaseFromNodeTrace(trace, idx)"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="node_traces (raw)" :value="selectedRun.node_traces" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="metadata" :value="selectedRun.metadata" collapsed />
        </template>
      </template>
    </HarnessDetailDialog>

    <HarnessDetailDialog :visible="Boolean(selectedReplay)" header="Replay Snapshot" @update:visible="closeReplayDialog">
      <template #default="{ registerBlock }">
        <template v-if="selectedReplay">
          <div class="dialog-actions">
            <Button label="导出 Replay" icon="pi pi-download" severity="secondary" @click="exportReplay" />
            <Button label="创建 Eval Case" icon="pi pi-plus" severity="secondary" @click="createCaseFromSelectedReplay" />
            <Button label="标记 Bad Case" icon="pi pi-exclamation-triangle" severity="warning" @click="openFeedbackFromReplay" />
            <Button label="运行 Static Eval" icon="pi pi-play" class="p-button--accent" :loading="evalActionLoading" :disabled="evalActionLoading" @click="runEvalForReplay" />
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="request" :value="selectedReplay.request" />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="prompt_refs" :value="selectedReplay.prompt_refs" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="model_config" :value="selectedReplay.model_config" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="context_snapshot" :value="selectedReplay.context_snapshot" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="tool_snapshots" :value="selectedReplay.tool_snapshots" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="llm_snapshots" :value="selectedReplay.llm_snapshots" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="final_output" :value="selectedReplay.final_output" />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="data_limitations / trace_ref" :value="{ data_limitations: selectedReplay.data_limitations, trace_ref: selectedReplay.trace_ref }" collapsed />
          <JsonBlock v-if="exportPackage" :ref="(el: any) => registerBlock(el)" title="export package" :value="exportPackage" collapsed />
        </template>
      </template>
    </HarnessDetailDialog>

    <HarnessDetailDialog :visible="Boolean(selectedEvalCase)" header="Eval Case" @update:visible="closeEvalCaseDialog">
      <template #default="{ registerBlock }">
        <template v-if="selectedEvalCase">
          <div class="dialog-actions">
            <Button label="编辑 Eval Case" icon="pi pi-pencil" severity="secondary" @click="openEditEvalCase" />
            <Button label="复制 Eval Case" icon="pi pi-clone" severity="secondary" :loading="evalActionLoading" :disabled="evalActionLoading" @click="cloneEvalCaseFromDetail" />
            <Button
              :label="selectedEvalCase.archived ? '取消归档' : '归档'"
              :icon="selectedEvalCase.archived ? 'pi pi-folder-open' : 'pi pi-box'"
              severity="secondary"
              :loading="evalActionLoading"
              :disabled="evalActionLoading"
              @click="toggleArchiveEvalCaseFromDetail"
            />
            <Button label="运行 Static Eval" icon="pi pi-play" class="p-button--accent" :loading="evalActionLoading" :disabled="evalActionLoading" @click="runEvalForCase(selectedEvalCase?.case_id)" />
            <Button label="运行 Live Mock Eval" icon="pi pi-refresh" severity="secondary" :loading="evalActionLoading" :disabled="evalActionLoading" @click="runLiveMockForCase(selectedEvalCase?.case_id)" />
          </div>
          <div v-if="selectedEvalCase.eval_scope === 'node'" class="node-eval-summary">
            <div class="node-eval-summary__title">Node Eval Case</div>
            <div class="node-eval-summary__grid">
              <div><span>Agent</span><strong>{{ selectedEvalCase.agent_name || '-' }}</strong></div>
              <div><span>Node</span><strong>{{ selectedEvalCase.node_name || '-' }}</strong></div>
              <div><span>Prompt</span><strong>{{ selectedEvalCase.prompt_key || '-' }} / {{ selectedEvalCase.prompt_version || '-' }}</strong></div>
              <div><span>Model</span><strong>{{ selectedEvalCase.model || '-' }}</strong></div>
              <div><span>Source</span><strong>{{ selectedEvalCase.source || '-' }}{{ selectedEvalCase.source_llm_call_id ? ` (llm_call)` : selectedEvalCase.source_node_trace_id ? ` (node_trace)` : '' }}</strong></div>
            </div>
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="基础信息" :value="{ case_id: selectedEvalCase.case_id, agent_name: selectedEvalCase.agent_name, title: selectedEvalCase.title, description: selectedEvalCase.description, enabled: selectedEvalCase.enabled, archived: selectedEvalCase.archived, archived_at: selectedEvalCase.archived_at, archived_reason: selectedEvalCase.archived_reason, severity: selectedEvalCase.severity, category: selectedEvalCase.category, tags: selectedEvalCase.tags, source: selectedEvalCase.source, source_replay_id: selectedEvalCase.source_replay_id, eval_scope: selectedEvalCase.eval_scope, node_name: selectedEvalCase.node_name, source_run_id: selectedEvalCase.source_run_id, source_llm_call_id: selectedEvalCase.source_llm_call_id, source_node_trace_id: selectedEvalCase.source_node_trace_id, prompt_key: selectedEvalCase.prompt_key, prompt_version: selectedEvalCase.prompt_version, prompt_hash: selectedEvalCase.prompt_hash, model: selectedEvalCase.model, notes: selectedEvalCase.notes, version: selectedEvalCase.version, updated_at: selectedEvalCase.updated_at }" />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="input" :value="selectedEvalCase.input" />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="mock_context" :value="selectedEvalCase.mock_context" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="expected_behavior" :value="selectedEvalCase.expected_behavior" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="expected_output_fields" :value="selectedEvalCase.expected_output_fields" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="expected_tools" :value="selectedEvalCase.expected_tools" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="expected_data_limitations" :value="selectedEvalCase.expected_data_limitations" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="forbidden_behavior" :value="selectedEvalCase.forbidden_behavior" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="scoring_rubric" :value="selectedEvalCase.scoring_rubric" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="metadata" :value="selectedEvalCase.metadata" collapsed />
        </template>
      </template>
    </HarnessDetailDialog>

    <EvalCaseEditorDialog
      :visible="evalCaseEditorVisible"
      :initial-case="evalCaseEditorInitial"
      :mode="evalCaseEditorMode"
      :saving="evalCaseEditorSaving"
      @update:visible="closeEvalCaseEditor"
      @save="handleEvalCaseSave"
    />

    <HarnessDetailDialog :visible="Boolean(selectedEvalRun)" :header="evalRunDialogTitle" @update:visible="closeEvalRunDialog">
      <template #default="{ registerBlock }">
        <template v-if="selectedEvalRun">
          <div v-if="selectedEvalRun.config?.run_type === 'agent_regression'" class="regression-info">
            <div class="regression-info__row">
              <span class="regression-info__label">Agent Regression Eval</span>
              <Tag :value="(selectedEvalRun.config?.gate_result as Record<string, unknown>)?.passed ? 'Gate Passed' : 'Gate Failed'" :class="(selectedEvalRun.config?.gate_result as Record<string, unknown>)?.passed ? 'p-tag--positive' : 'p-tag--negative'" />
            </div>
            <div class="regression-info__detail">
              <span>Trigger: {{ selectedEvalRun.config?.trigger || '-' }}</span>
              <span>Agent: {{ selectedEvalRun.config?.agent_name || '-' }}</span>
              <span>Mode: {{ selectedEvalRun.config?.mode || '-' }}</span>
              <span>Selected Cases: {{ selectedEvalRun.config?.selected_case_count ?? '-' }}</span>
              <span>Selected Agent Cases: {{ selectedEvalRun.config?.selected_agent_case_count ?? '-' }}</span>
              <span>Selected Node Cases: {{ selectedEvalRun.config?.selected_node_case_count ?? '-' }}</span>
              <span>Skipped Judge: {{ selectedEvalRun.config?.skipped_judge_case_count ?? '-' }}</span>
            </div>
            <div v-if="(selectedEvalRun.config?.case_selector as Record<string, unknown>)?.include_node_eval" class="regression-info__detail">
              <span>Include Node Eval: true{{ (selectedEvalRun.config?.case_selector as Record<string, unknown>)?.node_name ? ` / ${(selectedEvalRun.config?.case_selector as Record<string, unknown>)?.node_name}` : '（全部节点）' }}</span>
            </div>
            <div v-if="(selectedEvalRun.config?.scope_breakdown as Record<string, unknown>)" class="regression-info__detail">
              <span>Scope Breakdown:</span>
              <span>Agent: {{ ((selectedEvalRun.config?.scope_breakdown as Record<string, Record<string, number>>)?.agent?.passed_count ?? '-') }} / {{ (selectedEvalRun.config?.scope_breakdown as Record<string, Record<string, number>>)?.agent?.case_count ?? '-' }}</span>
              <span>Node: {{ ((selectedEvalRun.config?.scope_breakdown as Record<string, Record<string, number>>)?.node?.passed_count ?? '-') }} / {{ (selectedEvalRun.config?.scope_breakdown as Record<string, Record<string, number>>)?.node?.case_count ?? '-' }}</span>
            </div>
            <div v-if="(selectedEvalRun.config?.prompt as Record<string, unknown>)?.prompt_key" class="regression-info__detail">
              <span>Prompt: {{ (selectedEvalRun.config?.prompt as Record<string, unknown>)?.prompt_key }}{{ (selectedEvalRun.config?.prompt as Record<string, unknown>)?.prompt_version ? ` / ${(selectedEvalRun.config?.prompt as Record<string, unknown>)?.prompt_version}` : '' }}{{ (selectedEvalRun.config?.prompt as Record<string, unknown>)?.prompt_hash ? ` / ${(selectedEvalRun.config?.prompt as Record<string, unknown>)?.prompt_hash}` : '' }}</span>
            </div>
            <div v-if="((selectedEvalRun.config?.gate_result as Record<string, unknown>)?.reasons as string[])?.length" class="regression-info__reasons">
              <div v-for="reason in ((selectedEvalRun.config?.gate_result as Record<string, unknown>)?.reasons as string[])" :key="reason" class="regression-info__reason">- {{ reason }}</div>
            </div>
          </div>
          <EvalRunAnalysisPanel :run="selectedEvalRun" />
          <div class="dialog-actions">
            <Button label="将失败项生成反馈" icon="pi pi-exclamation-triangle" severity="warning" :loading="evalActionLoading" :disabled="evalActionLoading" @click="generateFeedbackFromEvalRunFailures" />
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="summary" :value="selectedEvalRun.summary" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="config" :value="selectedEvalRun.config" collapsed />
          <table class="harness-table">
            <thead><tr><th>case_id</th><th>agent</th><th>status</th><th>severity</th><th>category</th><th>score</th><th>failed_checks</th><th>error</th><th></th></tr></thead>
            <tbody>
              <tr v-for="result in selectedEvalRun.results || []" :key="`${result.case_id}-${result.replay_id}`" @click="openChecks(result)">
                <td><code :class="result.case_id ? 'clickable' : ''" @click.stop="result.case_id && navigateToEvalCase(result.case_id)">{{ result.case_id || '-' }}</code></td><td>{{ result.agent_name || '-' }}</td><td><Tag :value="result.status || '-'" :class="statusClass(result.status)" /></td><td>{{ result.metadata?.severity || '-' }}</td><td>{{ result.metadata?.category || '-' }}</td><td>{{ result.score ?? 0 }}/{{ result.max_score ?? 0 }}</td><td>{{ (result.checks || []).filter(c => c.passed === false).map(c => c.check_name).join(', ') || '-' }}</td><td>{{ result.error_code || '-' }}</td><td><Button icon="pi pi-flag" severity="warning" size="small" text @click.stop="openFeedbackFromEvalResult(result)" title="标记 Bad Case" /></td>
              </tr>
            </tbody>
          </table>
          <JsonBlock v-if="selectedEvalChecks" :ref="(el: any) => registerBlock(el)" title="checks" :value="selectedEvalChecks" />
          <JsonBlock v-if="selectedEvalResultMeta?.actual_output" :ref="(el: any) => registerBlock(el)" title="actual_output (Live Mock)" :value="selectedEvalResultMeta.actual_output" />
        </template>
      </template>
    </HarnessDetailDialog>

    <EvalRunCompareDialog
      :visible="evalRunCompareVisible"
      :result="evalRunCompareResult"
      :loading="evalRunCompareLoading"
      @update:visible="closeEvalRunCompareDialog"
    />

    <EvalCaseBulkEditDialog
      :visible="bulkEditVisible"
      :case-count="selectedEvalCaseCount"
      :loading="bulkEditLoading"
      @update:visible="bulkEditVisible = $event"
      @save="handleBulkEditSave"
    />

    <BadCaseFeedbackDialog
      :visible="feedbackDialogVisible"
      :initial="feedbackDialogInitial || undefined"
      :loading="feedbackDialogLoading"
      @update:visible="feedbackDialogVisible = $event"
      @save="handleFeedbackSave"
    />

    <HarnessDetailDialog :visible="Boolean(selectedFeedback)" header="Bad Case 反馈详情" @update:visible="closeFeedbackDialog">
      <template #default="{ registerBlock }">
        <template v-if="selectedFeedback">
          <div class="dialog-actions">
            <Button v-if="selectedFeedback.status === 'open'" label="标记 triaged" icon="pi pi-check" severity="secondary" @click="updateFeedbackStatus(selectedFeedback.feedback_id, 'triaged')" />
            <Button v-if="selectedFeedback.status !== 'ignored' && selectedFeedback.status !== 'resolved'" label="标记 ignored" severity="secondary" @click="updateFeedbackStatus(selectedFeedback.feedback_id, 'ignored')" />
            <Button v-if="selectedFeedback.status !== 'resolved' && selectedFeedback.status !== 'converted'" label="标记 resolved" severity="secondary" @click="updateFeedbackStatus(selectedFeedback.feedback_id, 'resolved')" />
            <Button v-if="!selectedFeedback.converted_case_id" label="创建 Eval Case" icon="pi pi-plus" class="p-button--accent" :loading="evalActionLoading" :disabled="evalActionLoading" @click="createCaseFromSelectedFeedback" />
            <Button v-if="selectedFeedback.converted_case_id" label="查看 Eval Case" icon="pi pi-external-link" severity="secondary" @click="navigateToEvalCase(selectedFeedback.converted_case_id)" />
          </div>
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="基础信息" :value="{ feedback_id: selectedFeedback.feedback_id, source_type: selectedFeedback.source_type, source_id: selectedFeedback.source_id, agent_name: selectedFeedback.agent_name, title: selectedFeedback.title, description: selectedFeedback.description, issue_type: selectedFeedback.issue_type, severity: selectedFeedback.severity, category: selectedFeedback.category, tags: selectedFeedback.tags, status: selectedFeedback.status, notes: selectedFeedback.notes, converted_case_id: selectedFeedback.converted_case_id, created_at: selectedFeedback.created_at, updated_at: selectedFeedback.updated_at }" />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="evidence" :value="selectedFeedback.evidence" collapsed />
          <JsonBlock :ref="(el: any) => registerBlock(el)" title="metadata" :value="selectedFeedback.metadata" collapsed />
        </template>
      </template>
    </HarnessDetailDialog>
  </section>
</template>

<style scoped>
.admin-harness-page__title {
  font-size: 1.5rem;
}

.admin-tabs,
.harness-tabs,
.filter-row,
.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.node-traces-actions {
  display: grid;
  gap: 8px;
}

.checkbox-filter {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
  font-size: 0.85rem;
  white-space: nowrap;
}

.node-traces-actions__title {
  color: var(--color-text-secondary);
  font-size: 0.85rem;
  font-weight: 600;
}

.node-traces-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
  color: var(--color-text-primary);
}

.node-traces-table th,
.node-traces-table td {
  border: 1px solid rgba(129, 160, 207, 0.18);
  padding: 6px 10px;
  text-align: left;
}

.node-traces-table th {
  background: rgba(10, 18, 32, 0.72);
  color: var(--color-text-secondary);
  font-weight: 600;
}

.node-eval-summary {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
}

.node-eval-summary__title {
  color: var(--color-accent);
  font-weight: 700;
  font-size: 0.9rem;
}

.node-eval-summary__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
}

.node-eval-summary__grid > div {
  display: grid;
  gap: 2px;
  font-size: 0.82rem;
  color: var(--color-text-secondary);
}

.node-eval-summary__grid strong {
  color: var(--color-text-primary);
  font-weight: 600;
}

.harness-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.harness-tab-panel {
  display: grid;
  gap: 14px;
}

.harness-tabs button {
  padding: 8px 12px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.harness-tabs button.is-active,
.harness-tabs button:hover {
  border-color: rgba(86, 213, 255, 0.36);
  color: var(--color-text-primary);
}

.harness-tab-description {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid rgba(86, 213, 255, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.42);
  color: var(--color-text-secondary);
}

.harness-tab-description strong {
  color: var(--color-text-primary);
  font-size: 0.95rem;
}

.harness-tab-description p {
  margin: 0;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.harness-message {
  margin: 0;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
}

.harness-message--notice {
  background: rgba(88, 214, 161, 0.12);
  color: var(--color-positive);
}

.harness-message--error {
  background: rgba(255, 107, 122, 0.12);
  color: var(--color-negative);
}

.harness-stack,
.dialog-stack {
  display: grid;
  gap: var(--space-4);
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
}

.overview-card {
  display: grid;
  gap: 8px;
  padding: 16px;
}

.overview-card span {
  color: var(--color-text-secondary);
}

.overview-card strong {
  font-size: 1.35rem;
}

.overview-columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.filter-row {
  margin-bottom: var(--space-4);
}

.batch-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin-bottom: var(--space-4);
  border: 1px solid rgba(86, 213, 255, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.42);
  color: var(--color-text-primary);
}

.harness-table__checkbox-col {
  width: 36px;
  text-align: center;
}

.harness-table__checkbox-col input[type="checkbox"] {
  cursor: pointer;
  accent-color: var(--color-accent-strong);
}

.filter-row input,
.filter-row select {
  min-height: 38px;
  max-width: 180px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.72);
  color: var(--color-text-primary);
}

.harness-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}

.harness-table th,
.harness-table td {
  padding: 10px 8px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.1);
  text-align: left;
  vertical-align: top;
}

.harness-table th {
  color: var(--color-text-secondary);
  font-weight: 700;
}

.harness-table tr {
  cursor: pointer;
}

.harness-table tbody tr:hover {
  background: rgba(19, 42, 70, 0.54);
}

code {
  color: var(--color-accent-strong);
  overflow-wrap: anywhere;
}

.clickable {
  cursor: pointer;
  color: var(--color-accent-strong);
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 2px;
}

.clickable:hover {
  color: var(--color-positive);
}

@media (max-width: 1100px) {
  .overview-columns {
    grid-template-columns: 1fr;
  }

  .harness-toolbar {
    display: grid;
  }

  .harness-table {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }
}

.regression-info {
  border: 1px solid rgba(129, 160, 207, 0.2);
  border-radius: var(--radius-sm);
  padding: 0.75rem;
  margin-bottom: 0.75rem;
  background: rgba(10, 18, 32, 0.3);
}

.regression-info__row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.4rem;
}

.regression-info__label {
  font-weight: 600;
  font-size: 0.95rem;
}

.regression-info__detail {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  margin-bottom: 0.25rem;
}

.regression-info__reasons {
  margin-top: 0.35rem;
  font-size: 0.8rem;
  color: #f87171;
}

.regression-info__reason {
  margin-bottom: 0.15rem;
}
</style>
