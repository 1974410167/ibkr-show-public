# 01 - Node Eval 数据模型扩展

## 阶段目标

实现 Node Eval 的基础数据模型扩展，让现有 EvalCase / EvalRun 支持「节点级评测」。

当前系统主要支持 Agent 级评测：

```text
agent_name = trade_decision
评估整个交易决策 Agent 的最终输出
```

本阶段要扩展为同时支持：

```text
eval_scope = agent
eval_scope = node
```

也就是：

```text
Agent Eval：评估整个 Agent 最终输出
Node Eval：评估某个关键 LLM 节点的输出
```

LLM 是 Large Language Model，大语言模型。

本阶段只做数据模型、后端筛选、API 类型、Repository 映射和基础测试。

不做从 trace 创建 Node Eval Case，不做节点规则检查，不做前端 UI。

---

## 当前背景

当前 EvalCase 已有字段大致包括：

```text
case_id
agent_name
title
description
tags
source
input
mock_context
mock_tool_outputs
expected_behavior
expected_output_fields
expected_tools
expected_data_limitations
forbidden_behavior
scoring_rubric
metadata
enabled
severity
category
source_replay_id
judge_enabled
judge_rubric
judge_model_config
version
created_at
updated_at
```

当前 EvalRun 已支持：

```text
case_ids
agent_name
mode
summary
results
config
```

现在需要在不破坏现有 Agent Eval 的前提下，为 Node Eval 增加一组字段。

---

## 重点文件

后端重点文件：

```text
ibkr_show_backend/app/agents/eval_harness.py
ibkr_show_backend/app/services/agent_eval_repository.py
ibkr_show_backend/app/services/agent_eval_service.py
ibkr_show_backend/app/api/routes/admin_agent_eval.py
ibkr_show_backend/tests/test_agent_eval_service.py
ibkr_show_backend/tests/test_admin_agent_eval.py
```

前端类型文件：

```text
ibkr_show_frontend/src/types/adminHarness.ts
ibkr_show_frontend/src/api/adminHarness.ts
```

本阶段前端只改类型，不做 UI。

---

## 一、新增 EvalCase 字段

在 EvalCase 数据结构中新增以下字段：

```python
eval_scope: str = "agent"
node_name: str | None = None
source_run_id: str | None = None
source_llm_call_id: str | None = None
source_node_trace_id: str | None = None
prompt_key: str | None = None
prompt_version: str | None = None
prompt_hash: str | None = None
model: str | None = None
```

字段含义：

```text
eval_scope:
  agent = Agent 级评测
  node = 节点级评测

node_name:
  节点名称，例如 market_trend / fundamental_valuation / event_catalyst / risk_control / final_decision

source_run_id:
  来源 Agent Run ID

source_llm_call_id:
  来源 LLM Call ID

source_node_trace_id:
  来源 node_trace ID

prompt_key:
  节点使用的 prompt key

prompt_version:
  节点使用的 prompt version

prompt_hash:
  节点使用的 prompt hash

model:
  节点调用的模型名称
```

---

## 二、默认兼容规则

### 1. 老 EvalCase 默认是 agent scope

所有老数据没有 `eval_scope` 时，默认视为：

```text
eval_scope = agent
```

不要让历史数据报错。

### 2. node scope 必须有 node_name

如果：

```text
eval_scope = node
```

则：

```text
node_name 必填
```

否则创建或更新时返回 400。

### 3. agent scope 可以没有 node_name

如果：

```text
eval_scope = agent
```

则 node_name 可以为空。

### 4. eval_scope 合法值

只允许：

```text
agent
node
```

其他值返回 400。

---

## 三、EvalCase.from_dict / to_dict 要求

在 `EvalCase.from_dict()` 中：

1. 读取新增字段。
2. 对缺失字段给默认值。
3. eval_scope 缺失时默认 `agent`。
4. eval_scope 非法时抛 `ValueError`。
5. eval_scope=node 但 node_name 为空时抛 `ValueError`。

在 `to_dict()` 中输出新增字段。

---

## 四、Repository 映射要求

如果 EvalCase 存在 Elasticsearch mapping，需要增加字段：

```json
{
  "eval_scope": { "type": "keyword" },
  "node_name": { "type": "keyword" },
  "source_run_id": { "type": "keyword" },
  "source_llm_call_id": { "type": "keyword" },
  "source_node_trace_id": { "type": "keyword" },
  "prompt_key": { "type": "keyword" },
  "prompt_version": { "type": "keyword" },
  "prompt_hash": { "type": "keyword" },
  "model": { "type": "keyword" }
}
```

注意：

```text
不要重建 index
不要删除旧数据
只更新代码里的 mapping 定义
```

---

## 五、list_cases / select_cases_for_eval 筛选增强

### 1. list_cases 增加参数

在 Service 和 Repository 中支持筛选：

```python
eval_scope: str | None = None
node_name: str | None = None
source_run_id: str | None = None
source_llm_call_id: str | None = None
prompt_key: str | None = None
model: str | None = None
```

### 2. select_cases_for_eval 增加参数

新增：

```python
eval_scope: str | None = None
node_name: str | None = None
```

这样后续可以运行：

```text
某个 agent 的全部 node eval case
某个 agent 下某个 node_name 的 eval case
```

### 3. 默认行为不变

如果不传 eval_scope，则返回 agent + node 两类 case。

但为了避免现有 Agent 回归被 Node Eval 混入，本阶段需要特别注意：

```text
Agent Regression Eval 默认只跑 eval_scope=agent
```

也就是说，现有 `run_agent_regression_eval()` 在没有显式 include_node_eval 之前，应该只选择：

```text
eval_scope = agent
```

否则后续新增 Node Eval Case 后，Agent 回归会被污染。

这是本阶段的关键兼容点。

---

## 六、API 要求

### 1. GET /cases 支持新筛选参数

在：

```text
GET /api/admin/agent-eval/cases
```

新增 query 参数：

```text
eval_scope
node_name
source_run_id
source_llm_call_id
prompt_key
model
```

### 2. POST /cases 支持新增字段

创建 EvalCase 时允许传：

```json
{
  "eval_scope": "node",
  "node_name": "event_catalyst",
  "source_run_id": "run_xxx",
  "source_llm_call_id": "llm_xxx",
  "prompt_key": "trade_decision_event_catalyst_prompt",
  "prompt_version": "v3",
  "prompt_hash": "abc123",
  "model": "gpt-5.5"
}
```

### 3. PATCH /cases/{case_id} 支持新增字段

允许更新：

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

校验规则同创建。

---

## 七、EvalRun / EvalCaseResult 元数据要求

本阶段不需要大改 EvalRun 结构。

但 `_evaluate_case()` 生成 result metadata 时，建议把以下字段带进去：

```text
eval_scope
node_name
prompt_key
prompt_version
model
severity
category
tags
```

这样 EvalRun 详情和后续 Coverage 能知道这是 Node Eval。

---

## 八、Coverage API 兼容要求

如果项目已有 coverage API，本阶段需要让 case_coverage 中包含：

```text
eval_scope
node_name
prompt_key
model
```

并支持按 eval_scope / node_name 统计可以后续阶段再做。

本阶段最低要求：

```text
不破坏现有 coverage API
case_coverage 中能看到 eval_scope 和 node_name
```

---

## 九、前端类型要求

在：

```text
ibkr_show_frontend/src/types/adminHarness.ts
```

给 EvalCase 增加字段：

```ts
eval_scope?: 'agent' | 'node' | string
node_name?: string | null
source_run_id?: string | null
source_llm_call_id?: string | null
source_node_trace_id?: string | null
prompt_key?: string | null
prompt_version?: string | null
prompt_hash?: string | null
model?: string | null
```

给 EvalCaseUpdatePayload 增加同样字段。

给 EvalCasesListParams 增加：

```ts
eval_scope?: string
node_name?: string
source_run_id?: string
source_llm_call_id?: string
prompt_key?: string
model?: string
```

如果有 EvalCaseCoverageRow，也增加：

```ts
eval_scope?: string
node_name?: string | null
prompt_key?: string | null
model?: string | null
```

---

## 十、测试要求

### 1. 后端 Service 测试

在 `test_agent_eval_service.py` 中新增：

1. 老 case 没有 eval_scope 时默认 agent。
2. 创建 agent scope case 成功。
3. 创建 node scope case 且有 node_name 成功。
4. 创建 node scope case 但没有 node_name 抛 ValueError。
5. 创建非法 eval_scope 抛 ValueError。
6. list_cases(eval_scope="node") 只返回 node case。
7. list_cases(node_name="event_catalyst") 能筛选。
8. select_cases_for_eval(eval_scope="node") 能筛选。
9. run_agent_regression_eval 默认不选择 node case。
10. _evaluate_case result metadata 包含 eval_scope / node_name。

### 2. API 测试

在 `test_admin_agent_eval.py` 中新增：

1. POST /cases 创建 node eval case 成功。
2. POST /cases 创建 node eval case 缺 node_name 返回 400。
3. POST /cases 非法 eval_scope 返回 400。
4. GET /cases?eval_scope=node 返回 node case。
5. GET /cases?node_name=event_catalyst 返回对应 case。
6. PATCH /cases/{case_id} 可以更新 node_name。
7. PATCH 非法 eval_scope 返回 400。

### 3. 前端检查

运行：

```bash
npm run build
vitest run
```

如果项目有类型检查：

```bash
vue-tsc -b
```

### 4. 后端测试命令

至少运行：

```bash
pytest ibkr_show_backend/tests/test_agent_eval_service.py
pytest ibkr_show_backend/tests/test_admin_agent_eval.py
```

如果时间允许，运行全量：

```bash
pytest
```

---

## 十一、验收标准

1. 可以创建 agent scope EvalCase。
2. 可以创建 node scope EvalCase。
3. node scope 必须有 node_name。
4. GET /cases 支持 eval_scope / node_name 筛选。
5. 老 EvalCase 不受影响。
6. Agent Regression Eval 默认不跑 node case。
7. EvalRun result metadata 能看到 eval_scope / node_name。
8. 前端类型编译通过。
9. 现有 Harness、Coverage、Regression 功能不受影响。

---

## 十二、不允许做什么

- 不要做从 Agent Run / LLM Call 创建 Node Eval Case。
- 不要做节点级 UI。
- 不要做 trade_decision 节点规则检查。
- 不要做 include_node_eval。
- 不要新增新的 NodeEvalCase 表或 index。
- 不要破坏现有 EvalCase 结构。
- 不要破坏 Agent Regression Eval。
- 不要让 Agent Regression 默认跑 node case。
- 不要引入新依赖。
- 不要合入 main。
- 不要创建 PR 自动合并。
- 不要 force push main。

---

## 十三、提交要求

完成本阶段后：

1. 运行相关测试。
2. 修复所有失败。
3. 单独提交一个 commit。
4. 推送到远程 feature/node-eval 分支。
5. 不要合入 main。

commit message 建议：

```text
feat(eval): add node eval data model
```

阶段总结必须包含：

```text
阶段：01 - Node Eval 数据模型扩展
当前分支：
commit sha：
修改文件：
新增字段：
新增筛选：
兼容策略：
Agent Regression 是否默认排除 node case：
测试命令：
测试结果：
遗留问题：
下一阶段风险：
是否已推送远程：
是否合入 main：否
```
