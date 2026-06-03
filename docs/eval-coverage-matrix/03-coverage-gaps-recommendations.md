# 03 - Coverage Gap 和回归建议

## 阶段目标

在 Eval 覆盖矩阵基础上，增加 Coverage Gap 和回归建议能力。

前两个阶段已经完成：

```text
01 - Eval 覆盖矩阵后端 API
02 - Harness 覆盖矩阵 UI
```

现在系统已经能展示：

```text
每个 Agent 有多少 Eval Case
每个 category / severity / tag 覆盖情况
最近 EvalRun 通过率
哪些 case 在统计窗口内未运行
哪些 case 启用了 LLM Judge
case 来源分布
```

本阶段目标是进一步回答：

```text
哪些地方覆盖不足？
哪些 high / critical 风险没有保护？
哪些 Agent 缺少 regression case？
哪些 case 应该尽快补充？
哪些回归结果说明 Agent 可能退化？
```

最终在 Harness「覆盖矩阵」页面中新增：

```text
Coverage Gaps
Regression Recommendations
```

---

## 当前背景

当前 Coverage API 已返回：

```text
summary
by_agent
by_agent_category
by_agent_severity
by_agent_tag
by_source
case_coverage
```

本阶段在此基础上新增：

```json
{
  "gaps": [],
  "recommendations": []
}
```

注意：

```text
本阶段不做节点级评测。
本阶段不做 Graph Mock Replay。
本阶段不自动创建 Eval Case。
本阶段只做覆盖诊断和建议展示。
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
ibkr_show_frontend/src/views/AdminHarnessView.vue
ibkr_show_frontend/src/components/admin/EvalCoverageMatrixPanel.vue
ibkr_show_frontend/src/api/adminHarness.ts
ibkr_show_frontend/src/types/adminHarness.ts
```

如第 02 阶段没有抽组件，则在 `AdminHarnessView.vue` 中完成，但建议本阶段顺手把 Coverage UI 相关逻辑收敛到 `EvalCoverageMatrixPanel.vue`。

---

## 一、核心概念

### 1. Coverage Gap 是什么

Coverage Gap 指评测覆盖上的缺口，例如：

```text
某个 Agent 没有任何 enabled Eval Case
某个 Agent 没有 regression tag case
某个 Agent 没有 high / critical case
某个 Agent 的某个 category 完全没有 case
某些 enabled case 在统计窗口内从未运行
某些 high / critical case 最近运行失败
```

### 2. Recommendation 是什么

Recommendation 是基于 gap 的行动建议，例如：

```text
为 trade_decision 增加 investment_risk/high Eval Case
为 daily_position_review 增加 regression tag
优先修复 critical failed case
把 replay/bad_case 来源的高风险 case 加入 regression 集
运行某个 Agent 的回归评测
```

### 3. Gap 和 Recommendation 的区别

```text
Gap：发现问题
Recommendation：建议做什么
```

例如：

```json
{
  "gap": "trade_decision 缺少 critical case",
  "recommendation": "新增至少 1 个 critical severity 的 regression Eval Case"
}
```

---

## 二、后端返回结构要求

在 `GET /api/admin/agent-eval/coverage` 返回中新增：

```json
{
  "gaps": [
    {
      "gap_id": "gap_trade_decision_no_critical_cases",
      "agent_name": "trade_decision",
      "gap_type": "missing_critical_cases",
      "severity": "high",
      "category": "coverage",
      "title": "trade_decision 缺少 critical Eval Case",
      "description": "该 Agent 当前没有 critical severity 的 enabled Eval Case，无法保护最高风险场景。",
      "evidence": {
        "critical_case_count": 0,
        "enabled_case_count": 12
      },
      "suggested_action": "新增至少 1 个 critical severity 的 regression Eval Case。"
    }
  ],
  "recommendations": [
    {
      "recommendation_id": "rec_trade_decision_add_critical_regression_case",
      "agent_name": "trade_decision",
      "priority": "high",
      "title": "补充 trade_decision 的 critical regression case",
      "description": "trade_decision 缺少 critical case，建议优先从历史 Bad Case 或 Replay 中沉淀。",
      "action_type": "create_eval_case",
      "related_gap_ids": ["gap_trade_decision_no_critical_cases"],
      "metadata": {
        "target_severity": "critical",
        "target_tag": "regression"
      }
    }
  ]
}
```

---

## 三、Gap 字段定义

新增类型概念：

```python
gap = {
    "gap_id": str,
    "agent_name": str | None,
    "gap_type": str,
    "severity": "low" | "medium" | "high" | "critical",
    "category": str,
    "title": str,
    "description": str,
    "evidence": dict,
    "suggested_action": str,
}
```

### gap_type 可选值

至少支持：

```text
no_enabled_cases
no_regression_cases
no_high_cases
no_critical_cases
low_recent_pass_rate
high_critical_failures
never_evaluated_cases
uncategorized_cases
untagged_cases
judge_not_configured_for_critical
```

---

## 四、Recommendation 字段定义

新增类型概念：

```python
recommendation = {
    "recommendation_id": str,
    "agent_name": str | None,
    "priority": "low" | "medium" | "high" | "critical",
    "title": str,
    "description": str,
    "action_type": str,
    "related_gap_ids": list[str],
    "metadata": dict,
}
```

### action_type 可选值

至少支持：

```text
create_eval_case
add_regression_tag
run_agent_regression
fix_failed_cases
enable_judge
categorize_cases
tag_cases
review_coverage
```

---

## 五、Gap 规则要求

### 1. no_enabled_cases

如果某个 agent：

```text
enabled_case_count == 0
```

生成 gap：

```text
gap_type = no_enabled_cases
severity = critical
```

说明：

```text
该 Agent 没有任何启用的 Eval Case，无法进行有效回归。
```

Recommendation：

```text
create_eval_case
```

---

### 2. no_regression_cases

如果某个 agent 没有 tag 包含：

```text
regression
```

的 enabled case，生成 gap：

```text
gap_type = no_regression_cases
severity = high
```

说明：

```text
该 Agent 没有专门的 regression 回归集，Prompt 或代码变更后难以一键验证。
```

Recommendation：

```text
add_regression_tag
```

---

### 3. no_high_cases

如果某个 agent：

```text
high_case_count == 0
```

生成 gap：

```text
gap_type = no_high_cases
severity = medium
```

说明：

```text
缺少 high severity 用例，无法覆盖高风险但非致命场景。
```

Recommendation：

```text
create_eval_case
```

---

### 4. no_critical_cases

如果某个 agent：

```text
critical_case_count == 0
```

生成 gap：

```text
gap_type = no_critical_cases
severity = high
```

说明：

```text
缺少 critical severity 用例，无法保护最高风险场景。
```

Recommendation：

```text
create_eval_case
```

---

### 5. low_recent_pass_rate

如果某个 agent：

```text
recent_pass_rate != null
recent_pass_rate < 0.9
```

生成 gap：

```text
gap_type = low_recent_pass_rate
severity = high
```

如果：

```text
recent_pass_rate < 0.8
```

severity 升为：

```text
critical
```

Recommendation：

```text
fix_failed_cases
run_agent_regression
```

---

### 6. high_critical_failures

如果某个 agent：

```text
high_critical_failure_count > 0
```

生成 gap：

```text
gap_type = high_critical_failures
severity = critical
```

Recommendation：

```text
fix_failed_cases
```

---

### 7. never_evaluated_cases

如果某个 agent：

```text
never_evaluated_case_count > 0
```

生成 gap：

```text
gap_type = never_evaluated_cases
severity = medium
```

如果其中 high / critical case 未运行，可以升为 high。

第一版可以只按 agent 聚合，不必逐个 case 做 gap。

Recommendation：

```text
run_agent_regression
```

---

### 8. uncategorized_cases

如果 case_coverage 中某个 agent 有 category 为：

```text
uncategorized
空字符串
null
```

的 enabled case，生成 gap：

```text
gap_type = uncategorized_cases
severity = low
```

Recommendation：

```text
categorize_cases
```

---

### 9. untagged_cases

如果 case_coverage 中某个 agent 有 tags 为空或只有 `untagged` 的 enabled case，生成 gap：

```text
gap_type = untagged_cases
severity = low
```

Recommendation：

```text
tag_cases
```

---

### 10. judge_not_configured_for_critical

如果某个 critical case：

```text
judge_enabled != true
```

可以生成 agent 级 gap：

```text
gap_type = judge_not_configured_for_critical
severity = medium
```

说明：

```text
critical case 建议启用 LLM Judge，补充规则检查无法覆盖的推理质量评估。
```

Recommendation：

```text
enable_judge
```

注意：

```text
这条规则不要太激进，不要要求所有 case 都开启 Judge。
只建议 critical case 开启。
```

---

## 六、Recommendation 规则要求

Recommendation 可以由 Gap 派生。

建议每个 gap 至少生成 1 条 recommendation。

### priority 映射

```text
gap.severity = critical -> recommendation.priority = critical
gap.severity = high -> recommendation.priority = high
gap.severity = medium -> recommendation.priority = medium
gap.severity = low -> recommendation.priority = low
```

### 去重规则

如果同一个 agent 下出现多个相似 gap，不要生成太多重复 recommendation。

可以通过：

```text
agent_name + action_type + metadata target
```

去重。

例如：

```text
trade_decision no_high_cases
trade_decision no_critical_cases
```

可以分别保留，因为目标 severity 不同。

但多个 untagged case 只生成一条：

```text
为 trade_decision 补充 tags
```

---

## 七、Service 层实现建议

在 `AgentEvalService.get_eval_coverage()` 中：

1. 先生成原有 coverage。
2. 调用 helper：

```python
gaps = self._build_coverage_gaps(coverage)
recommendations = self._build_coverage_recommendations(gaps)
```

3. 将结果写入返回：

```python
coverage["gaps"] = gaps
coverage["recommendations"] = recommendations
```

也可以把 helper 做成独立纯函数，便于测试：

```python
def build_coverage_gaps(coverage: dict) -> list[dict]:
    ...

def build_coverage_recommendations(gaps: list[dict]) -> list[dict]:
    ...
```

推荐放在：

```text
ibkr_show_backend/app/agents/eval_coverage.py
```

这样 `AgentEvalService` 不会过大。

---

## 八、前端类型要求

在 `adminHarness.ts` 类型中新增：

```ts
export interface EvalCoverageGap {
  gap_id: string
  agent_name?: string | null
  gap_type: string
  severity: string
  category?: string
  title: string
  description?: string
  evidence?: Record<string, unknown>
  suggested_action?: string
}

export interface EvalCoverageRecommendation {
  recommendation_id: string
  agent_name?: string | null
  priority: string
  title: string
  description?: string
  action_type?: string
  related_gap_ids?: string[]
  metadata?: Record<string, unknown>
}
```

并扩展：

```ts
export interface EvalCoverageResponse {
  ...
  gaps?: EvalCoverageGap[]
  recommendations?: EvalCoverageRecommendation[]
}
```

---

## 九、前端 UI 要求

在「覆盖矩阵」页面顶部 Summary Cards 下面新增两个区域：

```text
Coverage Gaps
回归建议
```

### 1. Coverage Gaps 表

列：

```text
severity
agent_name
gap_type
title
description
suggested_action
```

展示规则：

- severity 用 Tag 样式。
- critical/high 放前面。
- 如果没有 gaps，显示：

```text
暂无明显覆盖缺口
```

### 2. Recommendations 表

列：

```text
priority
agent_name
action_type
title
description
```

展示规则：

- priority 用 Tag 样式。
- critical/high 放前面。
- 如果没有 recommendations，显示：

```text
暂无回归建议
```

### 3. 行为按钮

本阶段可以只展示，不做自动操作。

可选轻量按钮：

- `查看相关 Agent`：自动填充 coverage filter 的 agent_name 并刷新。
- `去评测用例`：切换到「评测用例」tab。

不要求本阶段自动创建 Eval Case。

---

## 十、排序规则

后端或前端都可以排序，但建议后端返回时排序。

排序优先级：

```text
critical
high
medium
low
```

同 severity 下：

```text
agent_name
gap_type
```

Recommendation 同理：

```text
critical
high
medium
low
```

---

## 十一、测试要求

### 后端测试

在 `test_agent_eval_service.py` 中新增：

1. agent 没有 enabled case 时生成 no_enabled_cases gap。
2. agent 没有 regression case 时生成 no_regression_cases gap。
3. agent 没有 high case 时生成 no_high_cases gap。
4. agent 没有 critical case 时生成 no_critical_cases gap。
5. recent_pass_rate < 0.9 生成 low_recent_pass_rate gap。
6. high_critical_failure_count > 0 生成 high_critical_failures gap。
7. never_evaluated_case_count > 0 生成 never_evaluated_cases gap。
8. critical case 未启用 judge 生成 judge_not_configured_for_critical gap。
9. 每个 gap 至少生成一个 recommendation。
10. recommendation 去重生效。
11. 没有 gap 时返回空数组，不报错。

### API 测试

在 `test_admin_agent_eval.py` 中新增：

1. coverage response 包含 gaps。
2. coverage response 包含 recommendations。
3. gaps / recommendations 字段为空时也返回空数组。

### 前端测试

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
2. 进入「覆盖矩阵」tab。
3. 页面中能看到：

```text
Coverage Gaps
回归建议
```

4. 如果某个 agent 没有 regression case，能看到对应 gap。
5. 如果某个 agent 没有 high / critical case，能看到对应 gap。
6. 如果某个 agent 最近通过率低于 90%，能看到对应 gap。
7. 如果某个 agent 有统计窗口内未运行 case，能看到对应 gap。
8. Recommendations 中能看到对应行动建议。
9. critical / high 建议排在前面。
10. 无 gap 时显示"暂无明显覆盖缺口"。
11. 原有覆盖矩阵表格不受影响。
12. 原有 Harness 其他 tab 不受影响。

---

## 十三、不允许做什么

- 不要做节点级评测。
- 不要做 Graph Mock Replay。
- 不要自动创建 Eval Case。
- 不要自动修改 tags。
- 不要自动启用 LLM Judge。
- 不要引入 LLM 来生成建议。
- 不要引入新依赖。
- 不要改 EvalRun / EvalCase 存储结构。
- 不要破坏 Coverage API 原有字段。
- 不要破坏 Harness 原有功能。

---

## 十四、提交要求

完成本阶段后：

1. 运行后端和前端相关测试。
2. 修复所有失败。
3. 单独提交一个 commit。

commit message 建议：

```text
feat(eval): add coverage gaps and recommendations
```

阶段总结必须包含：

```text
阶段：03 - Coverage Gap 和回归建议
commit sha:
修改文件:
新增 gap_type:
新增 action_type:
后端返回字段:
前端展示位置:
测试命令:
测试结果:
遗留问题:
后续可优化点:
```
