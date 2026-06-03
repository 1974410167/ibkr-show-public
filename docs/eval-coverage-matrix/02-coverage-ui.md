# 02 - Harness 覆盖矩阵 UI

## 阶段目标

在 Harness 控制台新增「覆盖矩阵」页面，用于展示 Eval Case 和 Eval Run 的覆盖情况。

当前第 01 阶段已经新增后端 API：

```text
GET /api/admin/agent-eval/coverage
```

本阶段目标是接入这个 API，并在前端展示：

```text
我们到底覆盖了哪些 Agent？
哪些 Agent 的 high / critical case 不足？
哪些 category 覆盖较弱？
哪些 case 最近没有被运行？
哪些 case 来自 replay / feedback / manual / builtin？
哪些 case 启用了 LLM Judge？
最近通过率如何？
```

本阶段只做前端 UI，不做 Gap 规则和 Recommendation 规则，那部分放到第 03 阶段。

---

## 当前背景

当前 Harness 已有 tab：

```text
总览
LLM 调用
Agent 运行记录
回放快照
评测用例
用例运行记录
问题反馈
```

本阶段新增一个 tab：

```text
覆盖矩阵
```

建议位置：

```text
总览之后，LLM 调用之前
```

也就是：

```text
总览
覆盖矩阵
LLM 调用
Agent 运行记录
回放快照
评测用例
用例运行记录
问题反馈
```

---

## 重点文件

前端重点文件：

```text
ibkr_show_frontend/src/views/AdminHarnessView.vue
ibkr_show_frontend/src/api/adminHarness.ts
ibkr_show_frontend/src/types/adminHarness.ts
```

建议新增组件：

```text
ibkr_show_frontend/src/components/admin/EvalCoverageMatrixPanel.vue
```

如有必要可新增：

```text
ibkr_show_frontend/src/components/admin/EvalCoverageSummaryCards.vue
```

但优先控制组件数量，不要过度拆分。

---

## 一、前端 API 要求

### 1. 新增 API 方法

在：

```text
ibkr_show_frontend/src/api/adminHarness.ts
```

新增：

```ts
export function getEvalCoverage(params: EvalCoverageParams = {}): Promise<EvalCoverageResponse>
```

请求：

```text
GET /api/admin/agent-eval/coverage
```

参数：

```ts
export interface EvalCoverageParams {
  agent_name?: string
  hours?: number
  limit?: number
  include_disabled?: boolean
}
```

---

## 二、前端类型要求

在：

```text
ibkr_show_frontend/src/types/adminHarness.ts
```

新增类型：

```ts
export interface EvalCoverageSummary {
  case_count?: number
  enabled_case_count?: number
  disabled_case_count?: number
  agent_count?: number
  judge_case_count?: number
  bad_case_source_count?: number
  replay_source_count?: number
  manual_source_count?: number
  recent_eval_run_count?: number
  recent_evaluated_case_count?: number
  never_evaluated_case_count?: number
}

export interface EvalCoverageAgentRow {
  agent_name: string
  case_count?: number
  enabled_case_count?: number
  disabled_case_count?: number
  judge_case_count?: number
  recent_eval_run_count?: number
  recent_pass_rate?: number | null
  recent_failed_count?: number
  recent_error_count?: number
  high_case_count?: number
  critical_case_count?: number
  high_critical_failure_count?: number
  never_evaluated_case_count?: number
}

export interface EvalCoverageCategoryRow {
  agent_name: string
  category: string
  case_count?: number
  enabled_case_count?: number
  recent_pass_rate?: number | null
  recent_failed_count?: number
  high_case_count?: number
  critical_case_count?: number
}

export interface EvalCoverageSeverityRow {
  agent_name: string
  severity: string
  case_count?: number
  enabled_case_count?: number
  recent_pass_rate?: number | null
  recent_failed_count?: number
}

export interface EvalCoverageTagRow {
  agent_name: string
  tag: string
  case_count?: number
  enabled_case_count?: number
  recent_pass_rate?: number | null
}

export interface EvalCoverageSourceRow {
  source: string
  case_count?: number
  enabled_case_count?: number
}

export interface EvalCaseCoverageRow {
  case_id: string
  agent_name?: string
  title?: string
  enabled?: boolean
  severity?: string
  category?: string
  tags?: string[]
  source?: string
  judge_enabled?: boolean
  last_eval_run_id?: string | null
  last_status?: string | null
  last_score?: number | null
  last_max_score?: number | null
  last_evaluated_at?: string | null
  recent_run_count?: number
  recent_pass_count?: number
  recent_failed_count?: number
  never_evaluated?: boolean
}

export interface EvalCoverageResponse {
  summary: EvalCoverageSummary
  by_agent: EvalCoverageAgentRow[]
  by_agent_category: EvalCoverageCategoryRow[]
  by_agent_severity: EvalCoverageSeverityRow[]
  by_agent_tag: EvalCoverageTagRow[]
  by_source: EvalCoverageSourceRow[]
  case_coverage: EvalCaseCoverageRow[]
}
```

---

## 三、UI 入口要求

### 1. 新增 Harness Tab

在 `AdminHarnessView.vue` 中新增 tab key：

```ts
'coverage'
```

tab 配置：

```ts
{
  key: 'coverage',
  label: '覆盖矩阵',
  description: '展示 Eval Case 和 Eval Run 的覆盖情况，帮助判断哪些 Agent、风险等级、场景和回归用例已经被评测覆盖。'
}
```

### 2. loadCurrentTab 接入

当 activeTab 为 `coverage` 时，调用：

```ts
loadEvalCoverage()
```

新增状态：

```ts
const coverage = ref<EvalCoverageResponse | null>(null)
const coverageLoading = ref(false)
const coverageFilters = reactive({
  agent_name: '',
  hours: 24 * 30,
  limit: 1000,
  include_disabled: true,
})
```

---

## 四、覆盖矩阵页面布局

建议页面分成 5 个区域：

```text
1. 筛选区
2. Summary Cards
3. Agent 覆盖总表
4. Category / Severity / Tag / Source 分组表
5. Case Coverage 明细表
```

---

## 五、筛选区

字段：

```text
agent_name
hours
limit
include_disabled
```

UI：

```text
Agent: [input/select]
Hours: [number]
Limit: [number]
[包含禁用 Case checkbox]
[刷新覆盖矩阵]
```

规则：

- `hours` 默认 720，也就是 30 天。
- `limit` 默认 1000。
- `include_disabled` 默认 true。
- agent_name 为空时查全部 Agent。
- 点击刷新调用 API。
- 切到 tab 时自动加载一次。

---

## 六、Summary Cards

展示以下指标：

```text
Case 总数
Enabled Case
Disabled Case
Agent 数
Judge Case
Replay 来源
Manual 来源
Bad Case 来源
最近 Eval Run 数
最近被评测 Case 数
窗口内未运行 Case 数
```

注意：

- `never_evaluated_case_count` 文案要写成：

```text
统计窗口内未运行 Case
```

不要写成"从未运行"，避免语义误导。

---

## 七、Agent 覆盖总表

表格标题：

```text
Agent 覆盖总览
```

列：

```text
agent_name
case_count
enabled_case_count
judge_case_count
high_case_count
critical_case_count
recent_eval_run_count
recent_pass_rate
recent_failed_count
recent_error_count
high_critical_failure_count
never_evaluated_case_count
```

展示规则：

- `recent_pass_rate === null` 显示 `-`
- pass_rate 使用现有 `formatRate`
- high/critical 数量为 0 时正常显示 0
- high_critical_failure_count > 0 时使用 warning / danger 样式

---

## 八、Category / Severity / Tag / Source 表

### 1. Agent × Category

标题：

```text
Agent × Category
```

列：

```text
agent_name
category
case_count
enabled_case_count
high_case_count
critical_case_count
recent_pass_rate
recent_failed_count
```

### 2. Agent × Severity

标题：

```text
Agent × Severity
```

列：

```text
agent_name
severity
case_count
enabled_case_count
recent_pass_rate
recent_failed_count
```

severity 建议用 Tag 样式：

```text
low / medium / high / critical
```

### 3. Agent × Tag

标题：

```text
Agent × Tag
```

列：

```text
agent_name
tag
case_count
enabled_case_count
recent_pass_rate
```

### 4. Source 分布

标题：

```text
Case 来源分布
```

列：

```text
source
case_count
enabled_case_count
```

---

## 九、Case Coverage 明细表

标题：

```text
Case 覆盖明细
```

列：

```text
case_id
agent_name
title
enabled
severity
category
tags
source
judge_enabled
last_status
last_score
last_evaluated_at
recent_run_count
recent_failed_count
never_evaluated
```

要求：

- case_id 可点击，点击后打开对应 Eval Case 详情。
- last_eval_run_id 如果存在，可点击打开对应 Eval Run 详情。
- never_evaluated=true 时使用醒目标记：

```text
统计窗口内未运行
```

- judge_enabled=true 时显示：

```text
LLM Judge
```

- enabled=false 时显示：

```text
禁用
```

---

## 十、复用现有能力

尽量复用已有方法：

```ts
formatRate
formatDateTime
statusClass
severityClass
navigateToEvalCase
openEvalRun
getEvalRun
```

如果当前只能从 evalRuns 列表打开 EvalRun，新增一个方法：

```ts
async function openEvalRunById(evalRunId: string): Promise<void>
```

逻辑：

```ts
const run = await getEvalRun(evalRunId)
closeAllDetailDialogs()
selectedEvalRunSource.value = 'list'
selectedEvalRun.value = run
activeTab.value = 'eval-runs'
```

---

## 十一、空状态和错误状态

如果 coverage 为空：

```text
暂无覆盖数据
```

如果 API 失败：

```text
加载覆盖矩阵失败：xxx
```

如果某个分组为空：

```text
暂无数据
```

---

## 十二、样式要求

保持 Harness 现有风格。

可以新增 class：

```css
.coverage-summary-grid
.coverage-card
.coverage-section
.coverage-section__title
.coverage-warning
.coverage-danger
.coverage-muted
.coverage-table
```

不要引入新 UI 依赖。

不要引入图表库。

本阶段只做表格和卡片，不做图表。

---

## 十三、手工验收标准

1. 打开 `/admin/harness`。
2. 可以看到新增 tab：

```text
覆盖矩阵
```

3. 点击「覆盖矩阵」后自动加载数据。
4. 顶部有筛选区：
   - agent_name
   - hours
   - limit
   - include_disabled
5. Summary Cards 显示：
   - case 总数
   - enabled case
   - judge case
   - 最近 EvalRun
   - 统计窗口内未运行 case
6. Agent 覆盖总览表能看到每个 Agent 的覆盖数量和最近通过率。
7. Agent × Category 表能看到不同 category 覆盖情况。
8. Agent × Severity 表能看到 high / critical 覆盖情况。
9. Agent × Tag 表能看到 regression 等 tag 覆盖情况。
10. Source 分布表能看到 replay/manual/feedback/builtin 分布。
11. Case Coverage 明细表能看到每个 case 的最近运行状态。
12. 点击 case_id 可以打开 Eval Case 详情。
13. 点击 last_eval_run_id 可以打开 Eval Run 详情。
14. include_disabled=false 时禁用 case 不展示。
15. 原有 Harness 其他 tab 不受影响。

---

## 十四、测试要求

运行：

```bash
npm run build
vitest run
```

如果项目有类型检查：

```bash
vue-tsc -b
```

如果已有前端测试体系，可以补轻量测试：

1. coverage API 参数构造正确。
2. coverage tab 渲染 summary。
3. case_id 点击触发详情打开。

如果补测试成本太高，本阶段至少保证 build 和 vitest 全通过。

---

## 十五、不允许做什么

- 不要改后端 API，除非发现第 01 阶段明显 bug。
- 不要做 Coverage Gap / Recommendation，这个第 03 阶段做。
- 不要引入图表库。
- 不要新增复杂可视化。
- 不要破坏现有 Harness tab。
- 不要破坏 Eval Case 详情弹窗。
- 不要破坏 Eval Run 详情弹窗。
- 不要做节点级评测。
- 不要做 Graph Mock Replay。

---

## 十六、提交要求

完成本阶段后：

1. 运行相关前端测试。
2. 修复所有失败。
3. 单独提交一个 commit。

commit message 建议：

```text
feat(eval): add coverage matrix ui
```

阶段总结必须包含：

```text
阶段：02 - Harness 覆盖矩阵 UI
commit sha:
修改文件:
新增 API/type:
新增组件:
UI 入口:
展示区域:
测试命令:
测试结果:
遗留问题:
下一阶段风险:
```
