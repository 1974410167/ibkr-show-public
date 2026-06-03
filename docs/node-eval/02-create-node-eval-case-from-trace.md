# 02 - 从 Agent Run / LLM Call 创建 Node Eval Case

## 阶段目标

实现从真实 Agent 运行记录、LLM 调用记录、node_trace 中一键创建 Node Eval Case 的能力。

第 01 阶段已经完成 Node Eval 数据模型扩展，EvalCase 已支持：

```text
eval_scope = agent | node
node_name
source_run_id
source_llm_call_id
source_node_trace_id
prompt_key
prompt_version
prompt_hash
model
```

本阶段目标是打通：

```text
真实 Agent Run / LLM Call / node_trace
→ 提取某个节点的输入和输出
→ 生成 Node Eval Case 草稿
→ 用户编辑后保存
→ 后续可以作为 Node Eval Case 运行
```

本阶段重点是 **case 沉淀链路**，不是节点规则检查。

---

## 当前背景

当前 Harness 已经有：

```text
Agent 运行记录
LLM 调用记录
Replay 快照
Eval Case 管理
Eval Case Editor
```

当前 Agent Run Detail 里通常包含：

```text
run_id
agent_name
prompt_metadata
llm_calls
tool_calls
validation
fallback
node_traces
metadata
```

当前 LLM Call Detail 里通常包含：

```text
call_id
run_id
agent_name
node_name
prompt_key
prompt_version
prompt_hash
model
call_type
latency_ms
total_tokens
ok
error_code
error_message
created_at
```

本阶段要基于这些已有记录生成 Node Eval Case。

---

## 重点文件

后端重点文件：

```text
ibkr_show_backend/app/api/routes/admin_agent_eval.py
ibkr_show_backend/app/api/routes/admin_agent_runs.py
ibkr_show_backend/app/api/routes/admin_llm_calls.py
ibkr_show_backend/app/services/agent_eval_service.py
ibkr_show_backend/app/services/agent_run_trace_repository.py
ibkr_show_backend/app/services/llm_call_repository.py
ibkr_show_backend/tests/test_agent_eval_service.py
ibkr_show_backend/tests/test_admin_agent_eval.py
```

前端重点文件：

```text
ibkr_show_frontend/src/views/AdminHarnessView.vue
ibkr_show_frontend/src/api/adminHarness.ts
ibkr_show_frontend/src/types/adminHarness.ts
ibkr_show_frontend/src/components/admin/EvalCaseEditorDialog.vue
```

如果当前项目里 repository 文件名不同，请先搜索：

```text
agent runs
agent_run
node_traces
llm_calls
LLMCallMetric
call_id
node_name
```

---

## 一、核心能力

### 1. 从 LLM Call 创建 Node Eval Case

用户在 LLM 调用详情里点击：

```text
创建 Node Eval Case
```

系统根据 LLM Call 生成一个 Eval Case 草稿：

```json
{
  "eval_scope": "node",
  "agent_name": "trade_decision",
  "node_name": "event_catalyst",
  "source": "llm_call",
  "source_run_id": "run_xxx",
  "source_llm_call_id": "llm_xxx",
  "prompt_key": "trade_decision_event_catalyst_prompt",
  "prompt_version": "v3",
  "prompt_hash": "abc123",
  "model": "gpt-5.5",
  "title": "Node Eval - trade_decision / event_catalyst",
  "input": {},
  "metadata": {
    "source_type": "llm_call",
    "llm_call_id": "llm_xxx"
  }
}
```

### 2. 从 Agent Run 的 node_trace 创建 Node Eval Case

用户在 Agent Run 详情的 node_traces 区域里，对某个节点点击：

```text
创建 Node Eval Case
```

系统根据 node_trace 生成 Eval Case 草稿：

```json
{
  "eval_scope": "node",
  "agent_name": "trade_decision",
  "node_name": "fundamental_valuation",
  "source": "node_trace",
  "source_run_id": "run_xxx",
  "source_node_trace_id": "trace_xxx",
  "title": "Node Eval - trade_decision / fundamental_valuation",
  "input": {},
  "metadata": {
    "source_type": "node_trace",
    "node_trace_id": "trace_xxx"
  }
}
```

### 3. 草稿不直接保存

和 Replay → Eval Case 当前流程保持一致。

点击创建时应：

```text
生成 draft
→ 打开 EvalCaseEditorDialog
→ 用户确认/编辑
→ 点击保存
→ POST /cases
```

不要静默保存。

---

## 二、后端 API 要求

### 1. 从 LLM Call 生成草稿

新增接口：

```text
POST /api/admin/agent-eval/cases/from-llm-call/{call_id}
```

Query 参数：

```text
save?: bool = false
```

行为：

- `save=false`：返回 Eval Case 草稿，不保存。
- `save=true`：直接保存 Eval Case。
- 第一版前端使用 `save=false`。

返回 EvalCase dict。

如果找不到 call：

```text
404 LLM call not found
```

如果 call 缺少 node_name：

```text
400 LLM call has no node_name
```

### 2. 从 Agent Run node_trace 生成草稿

新增接口：

```text
POST /api/admin/agent-eval/cases/from-node-trace/{run_id}/{node_trace_id}
```

Query 参数：

```text
save?: bool = false
```

行为：

- 根据 run_id 找 Agent Run。
- 从 node_traces 中找到指定 node_trace_id。
- 生成 Node Eval Case 草稿。
- `save=false` 时不保存。
- `save=true` 时保存。

如果找不到 run：

```text
404 Agent run not found
```

如果找不到 node_trace：

```text
404 Node trace not found
```

如果 node_trace 缺少 node_name：

```text
400 node_trace has no node_name
```

---

## 三、Node Eval Case 草稿构建规则

### 1. 通用字段

生成的 case 必须包含：

```python
{
    "case_id": new_eval_case_id(agent_name),
    "eval_scope": "node",
    "agent_name": agent_name,
    "node_name": node_name,
    "title": f"Node Eval - {agent_name} / {node_name}",
    "description": "...",
    "source": "llm_call" 或 "node_trace",
    "enabled": False,
    "severity": "medium",
    "category": "node_quality",
    "tags": ["node_eval", node_name],
    "input": {},
    "mock_context": {},
    "mock_tool_outputs": {},
    "expected_behavior": {},
    "expected_output_fields": [],
    "forbidden_behavior": [],
    "scoring_rubric": {},
    "metadata": {}
}
```

注意：

```text
默认 enabled=false
```

因为刚从 trace 生成的 case 需要人工编辑确认后再启用。

### 2. input 字段

`input` 应尽量包含节点输入摘要。

从 LLM Call 可以提取：

```text
messages
prompt
request
input
```

具体字段根据现有 LLM call 数据结构决定。

建议：

```json
{
  "node_input": {},
  "messages_summary": "...",
  "user_query": "...",
  "context_summary": "..."
}
```

不要保存完整敏感账户数据。

如果只能拿到少量信息，也可以：

```json
{
  "source_call_id": "xxx",
  "note": "原始输入请查看 source llm call"
}
```

### 3. metadata 字段

metadata 中可以保存来源引用和必要摘要：

```json
{
  "source_type": "llm_call",
  "source_run_id": "run_xxx",
  "source_llm_call_id": "llm_xxx",
  "node_name": "event_catalyst",
  "prompt_key": "...",
  "prompt_version": "...",
  "prompt_hash": "...",
  "model": "...",
  "call_type": "...",
  "created_from_trace_at": "..."
}
```

不要把完整 prompt 文本、API key、token、secret 写入 metadata。

### 4. expected_behavior 默认值

根据 node_name 给一个轻量默认 expected_behavior。

例如：

```json
{
  "node_name": "event_catalyst",
  "should": [
    "输出应围绕该节点职责展开",
    "应说明不确定性和数据限制"
  ]
}
```

如果暂时无法识别具体 node_name，使用通用规则。

---

## 四、Service 层要求

在 `AgentEvalService` 中新增：

```python
def build_case_from_llm_call(self, call_id: str, *, save: bool = False) -> dict | None:
    ...

def build_case_from_node_trace(self, run_id: str, node_trace_id: str, *, save: bool = False) -> dict | None:
    ...
```

如果需要区分错误原因，可以抛 ValueError，route 层转换 400/404。

建议新增纯函数：

```python
def build_node_eval_case_from_llm_call(call: dict) -> EvalCase:
    ...

def build_node_eval_case_from_node_trace(run: dict, node_trace: dict) -> EvalCase:
    ...
```

可以放在：

```text
ibkr_show_backend/app/agents/eval_harness.py
```

或者新建：

```text
ibkr_show_backend/app/agents/eval_node_case_builder.py
```

推荐新建 `eval_node_case_builder.py`，避免 `eval_harness.py` 继续膨胀。

---

## 五、数据来源要求

### 1. LLM Call 来源

优先从现有 LLM Call Repository 获取。

如果当前 service 没有注入 LLM Call Repository，需要：

- 在依赖注入中加入。
- 不要为了这个功能大改 LLM Call 存储。
- 如果注入复杂，可以先通过已有 Admin API service 复用已有 repository。

需要字段：

```text
call_id
run_id
agent_name
node_name
prompt_key
prompt_version
prompt_hash
model
call_type
created_at
metadata
```

如果缺少部分字段，用空值，不要报错。

但：

```text
node_name 必须存在
```

### 2. Agent Run node_trace 来源

从 Agent Run detail 的 `node_traces` 中找节点。

node_trace_id 的识别优先级：

```text
trace_id
node_trace_id
id
```

如果都没有，可以用数组 index 作为兜底：

```text
index_0
index_1
```

但前后端必须保持一致。

---

## 六、前端 API 要求

在：

```text
ibkr_show_frontend/src/api/adminHarness.ts
```

新增：

```ts
export function createEvalCaseFromLlmCall(callId: string, save = false): Promise<EvalCase>

export function createEvalCaseFromNodeTrace(
  runId: string,
  nodeTraceId: string,
  save = false,
): Promise<EvalCase>
```

请求：

```text
POST /api/admin/agent-eval/cases/from-llm-call/{call_id}?save=false
POST /api/admin/agent-eval/cases/from-node-trace/{run_id}/{node_trace_id}?save=false
```

---

## 七、前端 UI 要求

### 1. LLM Call Detail 增加按钮

在 LLM Call 详情弹窗顶部增加按钮：

```text
创建 Node Eval Case
```

显示条件：

```text
selectedLlmCall.agent_name 存在
selectedLlmCall.node_name 存在
```

如果 node_name 不存在，按钮禁用，tooltip 或文案：

```text
该 LLM Call 缺少 node_name，无法创建 Node Eval Case
```

点击后：

```text
调用 createEvalCaseFromLlmCall(call_id, false)
关闭当前详情弹窗
打开 EvalCaseEditorDialog
mode=create
initialCase=draft
```

### 2. Agent Run Detail 的 node_traces 增加创建入口

当前 node_traces 可能是 JsonBlock 展示。

本阶段可以先做一个简单区域：

```text
Node Traces
```

如果 selectedRun.node_traces 是数组，则在 JsonBlock 前面展示一个小表格：

```text
node_name | status | latency_ms | trace_id | 操作
```

每行按钮：

```text
创建 Node Eval Case
```

点击后：

```text
调用 createEvalCaseFromNodeTrace(run_id, node_trace_id, false)
关闭当前详情弹窗
打开 EvalCaseEditorDialog
mode=create
initialCase=draft
```

如果 node_trace 没有 id，使用 index fallback：

```text
index_0
index_1
```

但要和后端识别逻辑一致。

### 3. EvalCaseEditorDialog 兼容 Node 字段

如果第 01 阶段只是加了类型，没有 UI 字段，本阶段需要确保编辑弹窗能展示/保存以下字段：

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

可以放在「基础信息」区域：

```text
Eval Scope: agent/node
Node Name
Prompt Key
Prompt Version
Model
Source Run ID
Source LLM Call ID
Source Node Trace ID
```

要求：

- eval_scope=node 时 node_name 必填。
- 保存 payload 必须包含这些字段。
- 不要破坏 agent scope case 编辑。

---

## 八、单例弹窗规则

保持 Harness 当前单例弹窗原则。

点击创建 Node Eval Case 时：

```text
先拿到 draft
closeAllDetailDialogs()
打开 EvalCaseEditorDialog
```

不要让 LLM Call Detail、Agent Run Detail、EvalCaseEditorDialog 三层重叠。

---

## 九、测试要求

### 1. 后端 Service 测试

在 `test_agent_eval_service.py` 中新增：

1. 从 LLM Call 构建 node eval case 草稿成功。
2. 构建结果 eval_scope=node。
3. 构建结果 node_name 正确。
4. 构建结果 source_llm_call_id 正确。
5. LLM Call 缺 node_name 时抛 ValueError。
6. LLM Call 不存在时返回 None 或抛 NotFound。
7. 从 node_trace 构建 node eval case 草稿成功。
8. node_trace index fallback 生效。
9. save=true 时 case 被保存。
10. 草稿默认 enabled=false。

### 2. API 测试

在 `test_admin_agent_eval.py` 中新增：

1. POST /cases/from-llm-call/{call_id}?save=false 返回草稿。
2. POST /cases/from-llm-call/{call_id}?save=true 保存 case。
3. LLM Call 不存在返回 404。
4. LLM Call 缺 node_name 返回 400。
5. POST /cases/from-node-trace/{run_id}/{node_trace_id}?save=false 返回草稿。
6. node_trace 不存在返回 404。
7. node_trace 缺 node_name 返回 400。

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

## 十、手工验收标准

1. 打开 `/admin/harness`。
2. 进入「LLM 调用」tab。
3. 点击一条包含 agent_name 和 node_name 的 LLM Call。
4. 详情弹窗顶部能看到「创建 Node Eval Case」按钮。
5. 点击按钮后，打开 Eval Case 编辑弹窗。
6. 草稿中：
   - eval_scope = node
   - node_name 正确
   - source_llm_call_id 正确
   - prompt_key / prompt_version / model 尽量带出
   - enabled 默认 false
7. 保存后，在「评测用例」tab 能看到该 Node Eval Case。
8. 进入「Agent 运行记录」tab。
9. 点击一条包含 node_traces 的 run。
10. node_traces 区域能看到每个节点的「创建 Node Eval Case」按钮。
11. 点击后能生成 Node Eval Case 草稿。
12. 弹窗不重叠。
13. 原有 Replay → Eval Case 不受影响。
14. 原有 Agent Eval Case 编辑不受影响。

---

## 十一、不允许做什么

- 不要做节点规则检查，这个第 03 阶段做。
- 不要做 Node Eval 覆盖矩阵 UI，这个第 04 阶段做。
- 不要做 include_node_eval，这个第 05 阶段做。
- 不要自动启用新生成的 Node Eval Case。
- 不要静默保存，前端默认必须打开 editor 让用户确认。
- 不要保存完整敏感账户原始数据。
- 不要保存 API key、token、secret。
- 不要破坏现有 EvalCaseEditorDialog。
- 不要破坏 LLM Call Detail。
- 不要破坏 Agent Run Detail。
- 不要引入新依赖。
- 不要合入 main。
- 不要创建 PR 自动合并。
- 不要 force push main。

---

## 十二、提交要求

完成本阶段后：

1. 运行相关测试。
2. 修复所有失败。
3. 单独提交一个 commit。
4. 推送到远程 feature/node-eval 分支。
5. 不要合入 main。

commit message 建议：

```text
feat(eval): create node eval cases from traces
```

阶段总结必须包含：

```text
阶段：02 - 从 Agent Run / LLM Call 创建 Node Eval Case
当前分支：
commit sha：
修改文件：
新增 API：
新增前端入口：
Node Eval Case 草稿字段：
敏感数据处理方式：
测试命令：
测试结果：
遗留问题：
下一阶段风险：
是否已推送远程：
是否合入 main：否
```
