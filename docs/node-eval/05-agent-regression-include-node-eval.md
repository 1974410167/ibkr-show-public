# 05 - Agent 回归时可选同时运行 Node Eval

## 阶段目标

在 Agent Regression Eval 中增加可选参数：

```text
include_node_eval
```

让用户在运行某个 Agent 回归评测时，可以选择是否同时运行该 Agent 下的 Node Eval Case。

前 4 个阶段已经完成：

```text
01 - Node Eval 数据模型扩展
02 - 从 Agent Run / LLM Call 创建 Node Eval Case
03 - 交易决策关键节点规则检查
04 - Harness 支持 Node Eval 筛选和展示
```

现在系统已经支持：

```text
Agent Eval Case
Node Eval Case
Node-specific checks
Harness 中查看和筛选 Node Eval
```

本阶段目标是把 Node Eval 接入 Agent Regression 工作流：

```text
修改 trade_decision Prompt
→ 运行 Agent Regression Eval
→ 默认只跑 Agent Eval Case
→ 勾选 include_node_eval 后，同时跑 Node Eval Case
→ EvalRun 结果中展示 agent/node/mixed
→ gate 可以识别 node eval 失败
```

---

## 当前背景

当前 Agent Regression Eval 已有后端入口：

```text
POST /api/admin/agent-eval/regression-runs
```

当前请求大致包含：

```json
{
  "agent_name": "trade_decision",
  "mode": "static",
  "case_tag": "regression",
  "include_disabled": false,
  "include_judge": false,
  "gate": {},
  "trigger": "manual",
  "prompt": {},
  "model": {},
  "git": {}
}
```

第 01 阶段要求：

```text
Agent Regression Eval 默认只跑 eval_scope=agent
```

本阶段要在这个基础上新增：

```text
include_node_eval = false 默认
include_node_eval = true 时同时跑 eval_scope=node
```

---

## 重点文件

后端重点文件：

```text
ibkr_show_backend/app/services/agent_eval_service.py
ibkr_show_backend/app/api/routes/admin_agent_eval.py
ibkr_show_backend/tests/test_agent_eval_service.py
ibkr_show_backend/tests/test_admin_agent_eval.py
```

前端重点文件：

```text
ibkr_show_frontend/src/components/admin/AgentRegressionRunPanel.vue
ibkr_show_frontend/src/views/AdminHarnessView.vue
ibkr_show_frontend/src/api/adminHarness.ts
ibkr_show_frontend/src/types/adminHarness.ts
```

如果 Prompt 保存后触发回归也需要默认保持不跑 Node Eval，可能涉及：

```text
ibkr_show_frontend/src/views/AdminPromptsView.vue
```

---

## 一、后端请求参数

### 1. AgentRegressionRunRequest 新增字段

在后端 request model 中新增：

```python
include_node_eval: bool = False
node_name: str | None = None
```

含义：

```text
include_node_eval=false:
  只运行 eval_scope=agent 的 case

include_node_eval=true:
  运行 eval_scope=agent + eval_scope=node 的 case

node_name:
  可选，只在 include_node_eval=true 时生效
  如果传了 node_name，只额外运行该 node_name 的 node case
```

### 2. 默认行为必须保持不变

如果请求不传 include_node_eval：

```text
只跑 agent eval case
```

这是强约束，避免现有 Agent 回归结果被突然污染。

---

## 二、后端 Case 选择逻辑

### 1. include_node_eval=false

选择逻辑：

```text
agent_cases = select_cases_for_eval(
  agent_name=agent_name,
  eval_scope="agent",
  tag=case_tag,
  severity=severity,
  category=category,
  ...
)
```

不选择 node case。

### 2. include_node_eval=true

选择逻辑：

```text
agent_cases = select_cases_for_eval(eval_scope="agent", ...)
node_cases = select_cases_for_eval(eval_scope="node", node_name=node_name, ...)
selected_cases = agent_cases + node_cases
```

要求：

- 去重 case_id。
- agent case 和 node case 都要遵守 enabled / include_disabled。
- agent case 和 node case 都要遵守 include_judge。
- case_tag / severity / category 应同时作用于 agent 和 node case。
- node_name 只作用于 node case。

### 3. 没有匹配 case 的处理

如果 agent case 为空，但 node case 不为空：

```text
include_node_eval=true 时允许运行
```

也就是说，只要 selected_cases 非空即可。

如果两者都为空：

```text
返回 400 No eval cases matched regression selector
```

---

## 三、skipped 统计

返回和 config 中新增：

```text
selected_agent_case_count
selected_node_case_count
selected_case_count
skipped_judge_case_count
include_node_eval
node_name
```

示例：

```json
{
  "selected_case_count": 18,
  "selected_agent_case_count": 10,
  "selected_node_case_count": 8,
  "skipped_judge_case_count": 2
}
```

EvalRun.config 中写入：

```json
{
  "run_type": "agent_regression",
  "include_node_eval": true,
  "node_name": null,
  "selected_agent_case_count": 10,
  "selected_node_case_count": 8,
  "selected_case_count": 18,
  "case_selector": {
    "eval_scope": "mixed",
    "include_node_eval": true,
    "node_name": null
  }
}
```

如果 include_node_eval=false：

```json
{
  "include_node_eval": false,
  "selected_agent_case_count": 10,
  "selected_node_case_count": 0,
  "case_selector": {
    "eval_scope": "agent",
    "include_node_eval": false
  }
}
```

---

## 四、Gate 行为

### 1. 默认 Gate 计算包含所有 selected cases

如果 include_node_eval=true，Gate 应同时考虑 Agent Eval 和 Node Eval 的结果。

也就是说：

```text
任何 node case 的 failed/error 都会计入 failed_count/error_count
critical/high node failure 也会影响 fail_on_critical / fail_on_high
```

### 2. Gate result 增加 breakdown

在 gate_result 中新增：

```json
{
  "agent_case_count": 10,
  "node_case_count": 8,
  "agent_failed_count": 1,
  "node_failed_count": 2,
  "agent_pass_rate": 0.9,
  "node_pass_rate": 0.75
}
```

如果没有 node case：

```text
node_pass_rate = null
```

### 3. Gate reasons 要说明 Node Eval

如果 node failure 导致 gate failed，reasons 中要包含清晰原因：

```text
node_failed_count 2 > 0
node_pass_rate 0.75 indicates node eval regression
```

不要求新增复杂 gate 规则，先做 breakdown 即可。

---

## 五、EvalRun Summary 增强

如果当前 summary 没有 scope 分解，本阶段可以在 EvalRun.config 中补。

建议新增 helper：

```python
_build_scope_breakdown(results) -> dict
```

返回：

```json
{
  "agent": {
    "case_count": 10,
    "passed_count": 9,
    "failed_count": 1,
    "error_count": 0,
    "pass_rate": 0.9
  },
  "node": {
    "case_count": 8,
    "passed_count": 6,
    "failed_count": 2,
    "error_count": 0,
    "pass_rate": 0.75
  },
  "mixed": true
}
```

写入：

```text
EvalRun.config.scope_breakdown
```

---

## 六、API Response 增强

`POST /regression-runs` 响应中新增：

```json
{
  "selected_agent_case_count": 10,
  "selected_node_case_count": 8,
  "scope_breakdown": {}
}
```

保持原字段不变：

```text
eval_run
gate_result
baseline_compare_result
selected_case_count
skipped_judge_case_count
```

不要破坏现有前端。

---

## 七、前端类型更新

在：

```text
ibkr_show_frontend/src/types/adminHarness.ts
```

更新：

### AgentRegressionRunPayload

新增：

```ts
include_node_eval?: boolean
node_name?: string | null
```

### AgentRegressionRunResponse

新增：

```ts
selected_agent_case_count?: number
selected_node_case_count?: number
scope_breakdown?: Record<string, unknown>
```

### AgentRegressionGateResult

新增：

```ts
agent_case_count?: number
node_case_count?: number
agent_failed_count?: number
node_failed_count?: number
agent_pass_rate?: number | null
node_pass_rate?: number | null
```

---

## 八、Harness 手动回归入口 UI

在：

```text
AgentRegressionRunPanel.vue
```

新增表单字段：

```text
Include Node Eval
Node Name
```

### 1. Include Node Eval

checkbox：

```text
Include Node Eval
```

默认：

```text
false
```

说明文案：

```text
勾选后会同时运行该 Agent 下的 Node Eval Case，用于定位关键 LLM 节点是否退化。
```

### 2. Node Name

输入框或 select：

```text
Node Name，可选
```

只有 include_node_eval=true 时启用。

placeholder：

```text
可选，如 event_catalyst
```

如果为空：

```text
运行该 agent 下所有 node eval case
```

### 3. 确认弹窗增强

如果 include_node_eval=true，确认文案增加：

```text
本次将同时运行 Node Eval Case。Node Eval 失败也会计入 Gate 结果。
```

如果 node_name 有值：

```text
Node Name：event_catalyst
```

---

## 九、EvalRun 详情展示增强

在 Agent Regression Eval 详情里，如果 config.include_node_eval=true，展示：

```text
Include Node Eval: true
Selected Agent Cases: x
Selected Node Cases: y
Node Pass Rate: xx%
Node Failed: x
```

如果 config.scope_breakdown 存在，展示一个小摘要：

```text
Scope Breakdown
Agent: 9/10 passed
Node: 6/8 passed
```

EvalRun results 表中第 04 阶段已经展示 scope/node_name，本阶段只需要确认无遗漏。

---

## 十、Prompt 保存后触发回归

Prompt 保存后触发回归默认仍然：

```text
include_node_eval = false
```

不要自动跑 Node Eval，避免成本和评测范围突然扩大。

可以在 payload 中显式传：

```ts
include_node_eval: false
```

也可以不传，使用后端默认。

本阶段不做 Prompt 保存弹窗的高级选项。

---

## 十一、测试要求

### 1. 后端 Service 测试

在 `test_agent_eval_service.py` 中新增：

1. run_agent_regression_eval 默认只选择 eval_scope=agent case。
2. include_node_eval=true 时选择 agent + node case。
3. include_node_eval=true 且 node_name=event_catalyst 时只选择该 node 的 node case。
4. selected_agent_case_count / selected_node_case_count 统计正确。
5. scope_breakdown 统计 agent/node pass_rate 正确。
6. node case failed 时 gate_result.node_failed_count 正确。
7. node case failed 且 fail_on_high=true 时 gate_result.passed=false。
8. 没有 agent case 但有 node case 且 include_node_eval=true 时可以运行。
9. include_node_eval=false 时 node case 不影响 gate。

### 2. API 测试

在 `test_admin_agent_eval.py` 中新增：

1. POST /regression-runs 不传 include_node_eval 时不跑 node case。
2. POST /regression-runs include_node_eval=true 时返回 selected_node_case_count。
3. POST /regression-runs include_node_eval=true,node_name=xxx 时筛选生效。
4. response 包含 scope_breakdown。
5. EvalRun.config 包含 include_node_eval / scope_breakdown。

### 3. 前端验证

运行：

```bash
npm run build
vitest run
```

如果项目有类型检查：

```bash
vue-tsc -b
```

---

## 十二、手工验收标准

1. 打开 `/admin/harness`。
2. 进入「用例运行记录」tab。
3. Agent 回归评测表单中能看到：
   - Include Node Eval
   - Node Name
4. 默认 Include Node Eval 未勾选。
5. 运行一次普通 Agent Regression：
   - EvalRun.config.include_node_eval=false
   - selected_node_case_count=0
6. 勾选 Include Node Eval。
7. 运行一次 Agent Regression：
   - EvalRun.config.include_node_eval=true
   - selected_agent_case_count 正确
   - selected_node_case_count 正确
   - scope_breakdown 中有 agent/node 分解
8. 如果填写 node_name=event_catalyst：
   - 只运行该 node_name 的 node eval case
9. Node Eval 失败时：
   - gate_result 中 node_failed_count > 0
   - 页面能展示 Gate 未通过原因
10. Prompt 保存后触发回归仍然默认不跑 Node Eval。
11. 原有 Agent Regression 行为不受影响。
12. 原有 EvalRun Compare 不受影响。
13. 原有 Coverage Matrix 不受影响。

---

## 十三、不允许做什么

- 不要让 Agent Regression 默认 include_node_eval=true。
- 不要改 Prompt 保存后默认行为。
- 不要做新的 Node Eval UI，大部分已在第 04 阶段完成。
- 不要做 Graph Mock Replay。
- 不要引入新依赖。
- 不要让 Node Eval 影响未勾选 include_node_eval 的回归结果。
- 不要破坏 Agent Regression 现有 API 返回字段。
- 不要破坏 Eval Run Compare。
- 不要合入 main。
- 不要创建 PR 自动合并。
- 不要 force push main。

---

## 十四、提交要求

完成本阶段后：

1. 运行相关测试。
2. 修复所有失败。
3. 单独提交一个 commit。
4. 推送到远程 feature/node-eval 分支。
5. 不要合入 main。

commit message 建议：

```text
feat(eval): include node eval in agent regression
```

阶段总结必须包含：

```text
阶段：05 - Agent 回归时可选同时运行 Node Eval
当前分支：
commit sha：
修改文件：
新增参数：
默认行为：
Gate breakdown：
前端入口：
测试命令：
测试结果：
遗留问题：
是否已推送远程：
是否合入 main：否
```
