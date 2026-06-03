# 04 - Harness 支持 Node Eval 筛选和展示

## 阶段目标

在 Harness 控制台中支持 Node Eval 的筛选、展示和覆盖分析。

前 3 个阶段已经完成：

```text
01 - Node Eval 数据模型扩展
02 - 从 Agent Run / LLM Call 创建 Node Eval Case
03 - 交易决策关键节点规则检查
```

现在系统后端已经能区分：

```text
eval_scope = agent
eval_scope = node
```

本阶段要把这些能力展示到 Harness UI 中，让用户能在前端清楚看到：

```text
哪些 Eval Case 是 Agent 级
哪些 Eval Case 是 Node 级
某个 node_name 有多少 case
某个 node_name 最近通过率如何
某次 EvalRun 是 Agent Eval 还是 Node Eval
trade_decision 哪些节点比较薄弱
```

本阶段只做前端 UI 和必要的 API 参数接入，不做 include_node_eval，不做新的后端评测逻辑。

---

## 当前背景

当前 Harness 已有：

```text
评测用例 tab
用例运行记录 tab
覆盖矩阵 tab
LLM 调用详情
Agent 运行记录详情
Eval Case 编辑弹窗
Eval Run 详情弹窗
```

第 01 阶段已经让 EvalCase 支持：

```text
eval_scope
node_name
source_run_id
source_llm_call_id
source_node_trace_id
prompt_key
prompt_version
prompt_hash
model
```

第 02 阶段已经让用户可以从 LLM Call / node_trace 创建 Node Eval Case。

第 03 阶段已经让 Node Eval Case 能触发节点级规则检查。

本阶段目标是：**让这些字段在 Harness 里可见、可筛选、可分析。**

---

## 重点文件

前端重点文件：

```text
ibkr_show_frontend/src/views/AdminHarnessView.vue
ibkr_show_frontend/src/types/adminHarness.ts
ibkr_show_frontend/src/api/adminHarness.ts
ibkr_show_frontend/src/components/admin/EvalCaseEditorDialog.vue
ibkr_show_frontend/src/components/admin/EvalCoverageMatrixPanel.vue
ibkr_show_frontend/src/components/admin/EvalRunAnalysisPanel.vue
```

如果项目实际组件名不同，请先搜索：

```text
EvalCaseEditorDialog
EvalCoverage
CoverageMatrix
EvalRunAnalysis
eval_scope
node_name
caseFilters
coverageFilters
```

---

## 一、评测用例 tab 支持 Node Eval 筛选

### 1. 筛选区新增字段

在「评测用例」tab 的筛选区新增：

```text
Eval Scope
Node Name
Prompt Key
Model
```

对应参数：

```ts
caseFilters.eval_scope
caseFilters.node_name
caseFilters.prompt_key
caseFilters.model
```

UI 建议：

```text
Eval Scope: [全部 / agent / node]
Node Name: [输入框]
Prompt Key: [输入框]
Model: [输入框]
```

### 2. 调用 listEvalCases 时带上参数

在 `loadEvalCases()` 中追加：

```ts
eval_scope: caseFilters.eval_scope || undefined
node_name: caseFilters.node_name || undefined
prompt_key: caseFilters.prompt_key || undefined
model: caseFilters.model || undefined
```

### 3. 表格新增列

「评测用例」表格新增列：

```text
scope
node_name
prompt_key
model
```

展示规则：

- eval_scope = node 时显示 Tag：`NODE`
- eval_scope = agent 或空时显示 Tag：`AGENT`
- node_name 为空显示 `-`
- prompt_key 过长时可以用 compact text，完整内容放 title
- model 为空显示 `-`

---

## 二、Eval Case 详情展示 Node 字段

在 Eval Case 详情弹窗的「基础信息」JsonBlock 中增加：

```text
eval_scope
node_name
source_run_id
source_llm_call_id
source_node_trace_id
prompt_key
prompt_version
prompt_hash
model
```

如果是 Node Eval Case，详情顶部建议额外显示一个摘要块：

```text
Node Eval Case
Agent: trade_decision
Node: event_catalyst
Prompt: xxx / v3
Model: xxx
Source: llm_call / node_trace
```

最低要求：

```text
JsonBlock 中能看到这些字段
```

---

## 三、EvalCaseEditorDialog 支持 Node 字段编辑

如果第 02 阶段已经做过，这里只检查和补齐。

编辑弹窗需要支持：

```text
eval_scope
node_name
source_run_id
source_llm_call_id
source_node_trace_id
prompt_key
prompt_version
prompt_hash
model
```

### 1. 表单字段

建议放在基础信息区：

```text
Eval Scope: [agent / node]
Node Name
Prompt Key
Prompt Version
Prompt Hash
Model
Source Run ID
Source LLM Call ID
Source Node Trace ID
```

### 2. 校验规则

前端校验：

```text
eval_scope=node 时 node_name 必填
eval_scope 只能是 agent/node
```

不要只依赖后端 400。

### 3. 保存 payload

保存时必须把这些字段带到 payload。

---

## 四、用例运行记录 tab 展示 Node Eval 信息

### 1. EvalRun 列表新增 scope 摘要

如果 EvalRun.config 或 results metadata 中能推断 scope：

```text
agent / node / mixed
```

可以在 EvalRun 表格增加一列：

```text
scope
```

规则：

```ts
如果 config.eval_scope 存在，用 config.eval_scope
否则根据 results[].metadata.eval_scope 聚合：
- 全是 node -> node
- 全是 agent -> agent
- 混合 -> mixed
- 无法判断 -> -
```

最低要求：

```text
EvalRun 详情能展示 node_name
```

列表列可选。

### 2. EvalRun 详情结果表新增列

在 EvalRun 详情的 results 表格中新增：

```text
scope
node_name
```

列位置建议：

```text
case_id
agent
scope
node_name
status
severity
category
score
failed_checks
error
```

展示规则：

- result.metadata.eval_scope 显示 agent/node
- result.metadata.node_name 显示节点名
- node case 用 Tag 标记

### 3. EvalRun 详情摘要块

如果某次 EvalRun 包含 node case，详情顶部展示：

```text
Node Eval Summary
Node Cases: x
Nodes: event_catalyst, risk_control
```

可以简单从 results metadata 聚合。

---

## 五、覆盖矩阵支持 Node Coverage

当前覆盖矩阵已经有：

```text
summary
by_agent
by_agent_category
by_agent_severity
by_agent_tag
by_source
case_coverage
gaps
recommendations
```

本阶段需要在 UI 上展示 Node 维度。

### 1. Case Coverage 明细表新增列

新增：

```text
eval_scope
node_name
prompt_key
model
```

展示规则：

- node case 显示 `NODE`
- agent case 显示 `AGENT`

### 2. 新增 Node Coverage 区域

在覆盖矩阵页面增加一个区域：

```text
Node Coverage
```

如果后端已经返回了 `by_agent_node`，则直接展示。

如果后端暂时没有 `by_agent_node`，前端可以从 `case_coverage` 聚合出简单表格。

表格列：

```text
agent_name
node_name
case_count
enabled_case_count
recent_pass_rate
recent_failed_count
never_evaluated_case_count
judge_case_count
```

前端聚合规则：

- 只统计 `eval_scope === 'node'`
- 按 `agent_name + node_name` 分组
- `case_count`：总数
- `enabled_case_count`：enabled=true 数量
- `judge_case_count`：judge_enabled=true 数量
- `recent_pass_rate`：recent_pass_count / recent_run_count
- `recent_failed_count`：recent_failed_count 求和
- `never_evaluated_case_count`：never_evaluated=true 数量

如果没有 Node Eval Case，显示：

```text
暂无 Node Eval 覆盖数据
```

---

## 六、Coverage Gaps / Recommendations 展示 Node 信息

如果 gaps / recommendations 中存在：

```text
node_name
metadata.node_name
gap_type 与 node eval 相关
```

前端表格要展示 node_name。

新增列：

```text
node_name
```

如果没有 node_name，显示 `-`。

不要因为旧数据没有 node_name 报错。

---

## 七、LLM 调用详情和 Agent Run 详情入口复核

第 02 阶段已经新增：

```text
创建 Node Eval Case
```

本阶段需要复核 UI 可用性：

1. LLM Call Detail 中按钮文案清楚。
2. node_name 缺失时按钮禁用或隐藏。
3. Agent Run Detail 中 node_traces 表格能看到 node_name。
4. 点击创建后打开 EvalCaseEditorDialog。
5. 弹窗不重叠。

如果第 02 阶段实现已经完整，本阶段不要重复大改。

---

## 八、前端类型补齐

在 `adminHarness.ts` 中确认这些类型存在：

### EvalCase

```ts
eval_scope?: string
node_name?: string | null
source_run_id?: string | null
source_llm_call_id?: string | null
source_node_trace_id?: string | null
prompt_key?: string | null
prompt_version?: string | null
prompt_hash?: string | null
model?: string | null
```

### EvalCasesListParams

```ts
eval_scope?: string
node_name?: string
source_run_id?: string
source_llm_call_id?: string
prompt_key?: string
model?: string
```

### EvalCaseResult metadata

不一定需要强类型，但展示时要安全访问：

```ts
const meta = result.metadata || {}
meta.eval_scope
meta.node_name
```

### EvalCaseCoverageRow

```ts
eval_scope?: string
node_name?: string | null
prompt_key?: string | null
model?: string | null
```

---

## 九、交互验收标准

### 1. 评测用例 tab

1. 打开 `/admin/harness`。
2. 进入「评测用例」tab。
3. 能看到 Eval Scope 筛选。
4. 选择 `node` 后，只展示 node eval case。
5. 输入 node_name，例如 `event_catalyst`，能筛选对应 case。
6. 表格能看到 scope / node_name / prompt_key / model。
7. 点击 node eval case，详情能看到 node 字段。
8. 编辑 node eval case 时，eval_scope/node_name 等字段可见且可保存。

### 2. 用例运行记录 tab

1. 打开包含 node case 的 EvalRun。
2. 详情 results 表能看到 scope 和 node_name。
3. Node Eval 的 checks 正常展示。
4. Agent EvalRun 不受影响。

### 3. 覆盖矩阵 tab

1. Case Coverage 明细能看到 eval_scope / node_name。
2. Node Coverage 区域能看到按 agent + node_name 聚合的数据。
3. 没有 node case 时显示空状态，不报错。
4. Gaps / Recommendations 表兼容 node_name。

### 4. 创建 Node Eval Case 链路

1. 从 LLM Call Detail 创建 Node Eval Case。
2. 保存后能在「评测用例」tab 通过 eval_scope=node 筛出来。
3. 从 Agent Run node_trace 创建 Node Eval Case。
4. 保存后 node_name 正确。

---

## 十、测试要求

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

1. EvalCaseEditorDialog 在 eval_scope=node 且 node_name 为空时阻止保存。
2. coverage node aggregation 正常。
3. caseFilters 能传 eval_scope/node_name。

如果补测试成本高，本阶段至少保证：

```text
vue-tsc -b
npm run build
vitest run
```

全部通过。

---

## 十一、不允许做什么

- 不要做 include_node_eval，这个第 05 阶段做。
- 不要做新的后端节点规则检查。
- 不要做 Graph Mock Replay。
- 不要引入图表库。
- 不要重构整个 AdminHarnessView。
- 不要破坏现有 Agent Eval Case 编辑。
- 不要破坏 Replay → Eval Case。
- 不要破坏 Agent Regression Eval。
- 不要破坏 Coverage Matrix 原有字段。
- 不要引入新依赖。
- 不要合入 main。
- 不要创建 PR 自动合并。
- 不要 force push main。

---

## 十二、提交要求

完成本阶段后：

1. 运行相关前端测试。
2. 修复所有失败。
3. 单独提交一个 commit。
4. 推送到远程 feature/node-eval 分支。
5. 不要合入 main。

commit message 建议：

```text
feat(eval): expose node eval in harness
```

阶段总结必须包含：

```text
阶段：04 - Harness 支持 Node Eval 筛选和展示
当前分支：
commit sha：
修改文件：
新增筛选：
新增展示列：
Node Coverage 展示方式：
测试命令：
测试结果：
遗留问题：
下一阶段风险：
是否已推送远程：
是否合入 main：否
```
