# 01 - Eval 覆盖矩阵后端 API

## 阶段目标

实现 Eval 覆盖矩阵的后端 API。

当前项目已经具备：

- EvalCase 用例库
- EvalRun 用例运行记录
- Agent Regression Eval
- LLM-as-Judge
- Bad Case Feedback
- Static Eval / Live Mock Eval
- Eval Run Compare

但现在还缺一个能力：

```text
整体回答：我们到底评测覆盖了哪些 Agent、哪些风险、哪些场景？
```

本阶段目标是新增一个后端接口：

```text
GET /api/admin/agent-eval/coverage
```

用于统计 Eval Case 和 Eval Run 的覆盖情况，为后续 Harness 覆盖矩阵 UI 提供数据。

本阶段只做后端 API，不做前端 UI。

---

## 当前背景

当前已有核心对象：

```text
EvalCase：评测用例
EvalRun：用例运行记录
BadCaseFeedback：问题反馈
```

当前 EvalCase 已有字段：

```text
agent_name
enabled
severity
category
tags
source
source_replay_id
judge_enabled
metadata
created_at
updated_at
```

当前 EvalRun 已有字段：

```text
eval_run_id
agent_name
case_ids
config
summary
results
started_at
finished_at
status
```

当前 BadCaseFeedback 已有字段：

```text
feedback_id
agent_name
severity
category
issue_type
status
converted_case_id
```

现在要基于这些数据做覆盖统计。

---

## 重点文件

后端重点文件：

```text
ibkr_show_backend/app/services/agent_eval_service.py
ibkr_show_backend/app/api/routes/admin_agent_eval.py
ibkr_show_backend/app/services/agent_eval_repository.py
ibkr_show_backend/tests/test_agent_eval_service.py
ibkr_show_backend/tests/test_admin_agent_eval.py
```

如有必要可以新增：

```text
ibkr_show_backend/app/agents/eval_coverage.py
```

但优先复用 `AgentEvalService`，不要过度拆分。

---

## 一、核心统计维度

Coverage API 需要至少覆盖以下维度：

```text
agent_name
category
severity
tag
source
enabled
judge_enabled
```

重点不是只统计总数，而是能回答：

```text
某个 agent 有多少 eval case？
某个 agent 的 high/critical case 覆盖够不够？
某个 category 下最近通过率如何？
哪些 enabled case 从未被运行过？
哪些 case 来自 bad case/replay/manual？
哪些 case 启用了 LLM Judge？
```

---

## 二、API 设计

新增接口：

```text
GET /api/admin/agent-eval/coverage
```

Query 参数：

```text
agent_name?: string
hours?: int = 24 * 30
limit?: int = 1000
include_disabled?: bool = true
```

字段说明：

- `agent_name`：可选，只看某个 Agent。
- `hours`：统计最近多少小时内的 EvalRun，默认 30 天。
- `limit`：最多读取多少 EvalCase，默认 1000。
- `include_disabled`：是否包含 disabled case，默认 true。

---

## 三、返回结构

返回结构建议：

```json
{
  "summary": {
    "case_count": 120,
    "enabled_case_count": 100,
    "disabled_case_count": 20,
    "agent_count": 4,
    "judge_case_count": 12,
    "bad_case_source_count": 18,
    "replay_source_count": 30,
    "manual_source_count": 50,
    "recent_eval_run_count": 20,
    "recent_evaluated_case_count": 80,
    "never_evaluated_case_count": 40
  },
  "by_agent": [
    {
      "agent_name": "trade_decision",
      "case_count": 50,
      "enabled_case_count": 45,
      "disabled_case_count": 5,
      "judge_case_count": 8,
      "recent_eval_run_count": 10,
      "recent_pass_rate": 0.92,
      "recent_failed_count": 3,
      "recent_error_count": 1,
      "high_case_count": 10,
      "critical_case_count": 3,
      "high_critical_failure_count": 1,
      "never_evaluated_case_count": 8
    }
  ],
  "by_agent_category": [
    {
      "agent_name": "trade_decision",
      "category": "investment_risk",
      "case_count": 12,
      "enabled_case_count": 10,
      "recent_pass_rate": 0.8,
      "recent_failed_count": 2,
      "high_case_count": 5,
      "critical_case_count": 1
    }
  ],
  "by_agent_severity": [
    {
      "agent_name": "trade_decision",
      "severity": "high",
      "case_count": 10,
      "enabled_case_count": 9,
      "recent_pass_rate": 0.88,
      "recent_failed_count": 1
    }
  ],
  "by_agent_tag": [
    {
      "agent_name": "trade_decision",
      "tag": "regression",
      "case_count": 20,
      "enabled_case_count": 18,
      "recent_pass_rate": 0.94
    }
  ],
  "by_source": [
    {
      "source": "replay",
      "case_count": 30,
      "enabled_case_count": 25
    }
  ],
  "case_coverage": [
    {
      "case_id": "eval_case_xxx",
      "agent_name": "trade_decision",
      "title": "xxx",
      "enabled": true,
      "severity": "high",
      "category": "investment_risk",
      "tags": ["regression"],
      "source": "replay",
      "judge_enabled": false,
      "last_eval_run_id": "eval_run_xxx",
      "last_status": "passed",
      "last_score": 80,
      "last_max_score": 100,
      "last_evaluated_at": "2026-xx-xxTxx:xx:xxZ",
      "recent_run_count": 3,
      "recent_pass_count": 2,
      "recent_failed_count": 1,
      "never_evaluated": false
    }
  ]
}
```

---

## 四、统计规则

### 1. EvalCase 来源

`source` 可能包括：

```text
builtin
manual
replay
feedback
unknown
```

如果 source 为空，归为：

```text
unknown
```

### 2. Category 归一化

如果 category 为空，归为：

```text
uncategorized
```

### 3. Severity 归一化

如果 severity 为空，默认：

```text
medium
```

### 4. Tags 统计

一个 case 可以有多个 tag。

每个 tag 都要参与 `by_agent_tag` 统计。

如果 tags 为空，可以归为：

```text
untagged
```

### 5. 最近 EvalRun 统计

只统计最近 `hours` 范围内的 EvalRun。

优先使用：

```text
EvalRun.finished_at
```

如果没有 finished_at，则使用 started_at。

### 6. Case 最近状态

对于每个 case，找到最近一次包含该 case_id 的 EvalRun result。

记录：

```text
last_eval_run_id
last_status
last_score
last_max_score
last_evaluated_at
```

### 7. never_evaluated

如果某个 EvalCase 没有出现在任何最近 EvalRun 的 results 中：

```text
never_evaluated = true
```

注意：本阶段可以只基于最近 `hours` 范围判断，不要求全历史。

字段名仍然可以叫：

```text
never_evaluated
```

但语义是：

```text
在当前统计窗口内未被运行
```

### 8. recent_pass_rate

聚合维度的 pass_rate：

```text
passed_count / evaluated_result_count
```

如果 evaluated_result_count 为 0：

```text
recent_pass_rate = null
```

不要返回 0 误导用户。

---

## 五、Service 层要求

在 `AgentEvalService` 中新增方法：

```python
def get_eval_coverage(
    self,
    *,
    agent_name: str | None = None,
    hours: int = 24 * 30,
    limit: int = 1000,
    include_disabled: bool = True,
) -> dict:
    ...
```

职责：

1. 读取 EvalCase。
2. 读取最近 EvalRun。
3. 根据 EvalRun.results 反向聚合 case 运行情况。
4. 输出 summary / by_agent / by_agent_category / by_agent_severity / by_agent_tag / by_source / case_coverage。

---

## 六、Repository 要求

优先复用现有方法：

```python
list_cases(...)
list_runs(...)
```

如果 `list_runs` 已支持：

```text
hours
agent_name
limit
```

直接复用。

如果 limit 不够，可以在 service 层说明当前只统计最近 limit 条 EvalRun。

不要本阶段大改 repository 分页。

---

## 七、Route 要求

在 `admin_agent_eval.py` 中新增：

```python
@router.get("/coverage")
def get_eval_coverage(
    agent_name: str | None = None,
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    limit: int = Query(default=1000, ge=1, le=5000),
    include_disabled: bool = True,
    ...
) -> dict:
    return service.get_eval_coverage(...)
```

注意：

```text
/coverage 必须放在 /cases/{case_id} 或 /runs/{eval_run_id} 这类动态路由之前
```

避免被 path param 捕获。

---

## 八、测试要求

### Service 测试

在 `test_agent_eval_service.py` 中新增测试：

1. coverage 能统计总 case_count / enabled_case_count。
2. coverage 能按 agent 聚合。
3. coverage 能按 category 聚合，空 category 归为 uncategorized。
4. coverage 能按 severity 聚合，空 severity 默认 medium。
5. coverage 能按 tag 聚合，空 tags 归为 untagged。
6. coverage 能按 source 聚合，空 source 归为 unknown。
7. coverage 能从 EvalRun.results 统计 last_status / last_score。
8. coverage 能识别最近窗口内 never_evaluated case。
9. coverage 的 recent_pass_rate 在没有 evaluated result 时返回 null。
10. agent_name 过滤生效。

### API 测试

在 `test_admin_agent_eval.py` 中新增测试：

1. GET `/api/admin/agent-eval/coverage` 成功返回 summary。
2. agent_name query 生效。
3. include_disabled=false 时 disabled case 不参与统计。
4. hours 参数合法性校验生效。
5. 返回结构包含 by_agent / by_agent_category / case_coverage。

---

## 九、验收标准

后端验收：

1. 可以访问：

```text
GET /api/admin/agent-eval/coverage
```

2. 返回结构中包含：

```text
summary
by_agent
by_agent_category
by_agent_severity
by_agent_tag
by_source
case_coverage
```

3. 能看到每个 agent 的：

```text
case_count
enabled_case_count
judge_case_count
recent_pass_rate
never_evaluated_case_count
high_case_count
critical_case_count
```

4. 能看到每个 case 的最近运行状态：

```text
last_eval_run_id
last_status
last_score
last_evaluated_at
recent_run_count
never_evaluated
```

5. 没有最近运行记录的 case 不报错。

6. 没有任何 EvalCase 时返回空结构，不报错。

---

## 十、不允许做什么

- 不要做前端 UI。
- 不要做 Coverage Gap 建议，这个放第 03 阶段。
- 不要新增新的 ES index。
- 不要大改 EvalRun / EvalCase 存储结构。
- 不要破坏现有 Eval Case / Eval Run API。
- 不要破坏 Agent Regression Eval。
- 不要引入新依赖。
- 不要做节点级评测。
- 不要做 Graph Mock Replay。

---

## 十一、提交要求

完成本阶段后：

1. 运行相关后端测试。
2. 修复所有失败。
3. 单独提交一个 commit。

commit message 建议：

```text
feat(eval): add coverage matrix api
```

阶段总结必须包含：

```text
阶段：01 - Eval 覆盖矩阵后端 API
commit sha:
修改文件:
新增 API:
统计维度:
返回字段:
测试命令:
测试结果:
遗留问题:
下一阶段风险:
```
