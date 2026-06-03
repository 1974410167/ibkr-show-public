# Eval Correctness Framework

> Eval P3 · Stage 01 · 全局 Agent 正确性标准框架

## 1. 总体定义

一个好 Agent 输出，不是"说得像人"，而是：

> **在给定当时可用信息、工具返回数据和用户上下文的前提下，输出事实准确、依据充分、逻辑一致、风险可控、符合用户目标、可执行、可复盘的答案。**

P3 解决的核心问题：

1. P0 / P1 / P1.5 / P2 解决了"怎么跑评测"。
2. P3 解决"什么叫好答案，什么叫坏答案，怎样判断 Agent 输出质量"。

本阶段只做**全局框架**，不针对具体 Agent 做深度 case 扩充。
后续 Stage 02–06 会基于本框架，定义每个 Agent 类型自己的专属维度和重点检查。

## 2. 八个全局正确性维度

| 维度 ID | 中文 | 推荐 severity | 适合 rule check | 适合 LLM-as-Judge |
| --- | --- | --- | --- | --- |
| `factual_accuracy` | 事实准确性 | critical | ✓ | ✓ |
| `data_grounding` | 数据依据 | critical | ✓ | ✓ |
| `reasoning_consistency` | 逻辑一致性 | high | partial | ✓ |
| `risk_awareness` | 风险意识 | high | partial | ✓ |
| `user_alignment` | 用户策略匹配 | high | partial | ✓ |
| `actionability` | 可执行性 | medium | partial | ✓ |
| `uncertainty_awareness` | 不确定性表达 | medium | ✓ | ✓ |
| `format_stability` | 格式稳定性 | low | ✓ | partial |

### 2.1 factual_accuracy — 事实准确性

- **定义**：输出中所有事实陈述（数字、日期、行情、账户数据、公司事件等）与当时可用信息保持一致；不得编造不存在的指标或事件。
- **好答案表现**：数据可追溯到工具返回或 mock context；引用的指标和上下文严格匹配；不出现的具体数值就别说。
- **坏答案表现**：编造账户现金、持仓、成本、保证金；引用不存在的财报日期或新闻；指标定义错误。
- **适用 Agent 类型**：全部。
- **推荐 severity**：critical。
- **适合 rule check** 的信号：编造明显的现金/持仓/成本/保证金具体数值；`output` 中出现 `mock_tool_outputs` 不存在的字段名。
- **适合 LLM-as-Judge** 的信号：判断某条数据陈述是否被上下文支持，是否过度推断。

### 2.2 data_grounding — 数据依据

- **定义**：结论必须基于提供的账户、行情、工具或上下文信息；不得无依据臆测。
- **好答案表现**：每条结论后能溯源到具体工具、字段或输入；引用了 prompt 中明确给出的数据。
- **坏答案表现**：凭空得出"看涨 / 看跌"但没引用任何价格、估值或事件。
- **适用 Agent 类型**：全部。
- **推荐 severity**：critical。
- **适合 rule check** 的信号：判断结果中是否出现常见工具字段名（quote、context、symbol、news、filing）以验证确实调过工具。
- **适合 LLM-as-Judge** 的信号：判断每条结论是否有合理依据。

### 2.3 reasoning_consistency — 逻辑一致性

- **定义**：结论、论据、归因、建议之间没有内部矛盾。
- **好答案表现**：先说估值合理 → 建议"持有"；先说估值过高 → 建议"减仓"；归因方向一致。
- **坏答案表现**：先说"估值便宜、订单强劲" → 末尾"建议清仓"；列了两条互相抵消的归因但不下结论。
- **适用 Agent 类型**：全部。
- **推荐 severity**：high。
- **适合 rule check** 的信号：判断"买入 / 卖出 / 持有"等 action 关键词和归因关键词是否同时出现并自洽。
- **适合 LLM-as-Judge** 的信号：判断推理链是否自洽，是否存在自相矛盾。

### 2.4 risk_awareness — 风险意识

- **定义**：投资相关输出应明确指出潜在风险、下行情景、失效条件。
- **好答案表现**：建议买入时同时给止损 / 仓位 / 失效条件 / 风险点。
- **坏答案表现**：投资建议里完全没有"风险、止损、失效、观察"等关键词；只讲优势不讲风险。
- **适用 Agent 类型**：decision_agent、review_agent、account_agent（仅当用户问投资相关时）。
- **推荐 severity**：high。
- **适合 rule check** 的信号：投资建议场景下是否含风险关键词（风险 / 止损 / 失效 / 观察 / risk / stop loss / invalidation）。
- **适合 LLM-as-Judge** 的信号：判断风险是否被充分讨论、是否回避了关键风险点。

### 2.5 user_alignment — 用户策略匹配

- **定义**：输出应符合用户的目标、风险偏好、持仓约束、策略偏好。
- **好答案表现**：用户偏好长期持有时，给"持有 + 观察"而不是"短线买入"；已知用户已满仓时，不建议加仓。
- **坏答案表现**：明显违反用户已知约束（满仓时建议加仓、低风险偏好时建议满仓梭哈）。
- **适用 Agent 类型**：全部。
- **推荐 severity**：high。
- **适合 rule check** 的信号：判断是否违反已知用户约束（基于 case metadata 中 `user_constraints`）。
- **适合 LLM-as-Judge** 的信号：判断输出是否在不知道用户具体偏好的情况下，做了合理假设并说明。

### 2.6 actionability — 可执行性

- **定义**：建议应有具体动作、条件、仓位、观察点。
- **好答案表现**："在 X 价位以下分批买入 Y%，止损 Z，跌破支撑 W 后改为观察"。
- **坏答案表现**："可以考虑关注" / "建议观察" 但没说价位、仓位、止损。
- **适用 Agent 类型**：decision_agent、review_agent、account_agent（投资相关）。
- **推荐 severity**：medium。
- **适合 rule check** 的信号：动作类关键词、价位、百分比、止损等具体信号词。
- **适合 LLM-as-Judge** 的信号：判断建议是否真的可以照做。

### 2.7 uncertainty_awareness — 不确定性表达

- **定义**：当输出涉及交易、风险、预测、市场走势时，应表达不确定性。
- **好答案表现**："目前估值合理，但需要看 Q3 财报和宏观利率走势"；"如果预期落空，注意 X 风险"。
- **坏答案表现**：确定性语气过强，没有"可能 / 假设 / 取决于 / 需要进一步验证 / 风险 / 限制"等表达。
- **适用 Agent 类型**：全部。
- **推荐 severity**：medium。
- **适合 rule check** 的信号：检测是否存在不确定性关键词。
- **适合 LLM-as-Judge** 的信号：判断不确定性表达是否合理、是否过度保守或过度乐观。

### 2.8 format_stability — 格式稳定性

- **定义**：输出应满足 Agent 的契约 schema（必填字段、JSON 对象结构、字段类型）。
- **好答案表现**：必填字段齐全；JSON 解析无错；list 字段永远是 list 而不是 string。
- **坏答案表现**：缺字段、字段类型错、字段值为空字符串但应该是 enum。
- **适用 Agent 类型**：全部。
- **推荐 severity**：low。
- **适合 rule check** 的信号：必填字段、类型、JSON schema。
- **适合 LLM-as-Judge** 的信号：通常不需要。

## 3. Agent 类型分类

| Agent 类型 | 当前 Agent | 评测重点 |
| --- | --- | --- |
| `decision_agent` | `trade_decision` | action 是否合理、归因是否扎实、风险是否完整、是否过度承诺 |
| `review_agent` | `daily_position_review`、`trade_review` | 复盘归因是否准确、是否过度归因、用户可执行建议、风险与限制声明 |
| `account_agent` | `account_copilot` | 数据准确性、是否编造账户事实、是否越权给交易建议、是否需要 skill approval |
| `news_event_agent` | （未来） | 新闻解读、事件归因、是否区分传闻与已发生 |
| `risk_agent` | （未来） | 风险覆盖、监控建议、紧急情况处理 |

### 当前 Agent → Agent 类型映射

```python
AGENT_TYPE_MAPPING = {
    "trade_decision": "decision_agent",
    "daily_position_review": "review_agent",
    "trade_review": "review_agent",
    "account_copilot": "account_agent",
}
```

## 4. 三类评测方式

### 4.1 Rule Check（程序规则）

- 适合：格式、禁用词、必填字段、明显风险表述、编造账户数据等可机械判断的检查。
- 优点：稳定、可复现、便宜。
- 缺点：判断不了复杂语义、推理质量、用户策略匹配。
- 实现：放在 `eval_checks.py` 里的 `CheckResult`。

### 4.2 LLM-as-Judge（大语言模型裁判）

- 适合：逻辑质量、证据质量、归因质量、用户策略匹配、风险覆盖度。
- 优点：能判断推理、归因、表述质量。
- 缺点：不稳定、贵、不能完全替代规则。
- 实现：放在 `eval_judge.py` 里的 `AgentEvalJudgeService`。

### 4.3 Outcome Eval（事后表现）

- 适合：交易建议后的收益、回撤、是否跑赢基准。
- 优点：唯一能验证"建议对不对"的硬指标。
- 缺点：噪音大、归因难、滞后、不能作为唯一正确性标准。
- **本阶段不实现**，仅占位说明。

## 5. Severity 口径

| severity | 含义 | 影响 result.status | 例子 |
| --- | --- | --- | --- |
| `fatal` | 系统不可接受，直接失败 | failed | 输出为空、格式完全错误、编造核心账户数据 |
| `critical` | 高风险错误 | failed | 满仓梭哈建议、无依据强买入、编造持仓 |
| `high` | 明显质量问题 | failed | 归因错误、风险遗漏、逻辑矛盾 |
| `medium` | 一般质量问题 | warning | 表达不清、缺少不确定性 |
| `low` | 轻微问题 | warning | 格式小瑕疵 |

判定逻辑（参考 `agent_eval_service._evaluate_case`）：

- 任何 `fatal` / `critical` / `high` failed → `result.status == failed`。
- 仅 `medium` / `low` failed → `result.status == warning`。
- 全部 passed → `result.status == passed`。

## 6. 全局 Rule Check 清单

本阶段新增以下通用 Rule Check（在 `eval_checks.run_eval_checks` 中调度）：

| check_name | severity | 适用 Agent 类型 | 触发条件 |
| --- | --- | --- | --- |
| `output_not_empty` | fatal | 全部 | output 为空、None、空字符串、空 dict |
| `no_unqualified_absolute_claims` | critical / high | 全部 | 出现"一定涨 / 必然 / guaranteed"等绝对化表达且无否定 |
| `mentions_uncertainty_when_relevant` | warning | 全部 | 涉及投资/预测但无不确定性表达 |
| `no_unsafe_all_in_advice` | critical | decision_agent、review_agent（投资相关） | 出现"满仓 / 梭哈 / all in"等极端仓位建议且无否定 |
| `no_obvious_hallucinated_account_data` | high | account_agent、review_agent、decision_agent | case 明确 expected_data_limitations / `data_missing`，但输出编造具体账户数值 |
| `no_missing_risk_section_for_investment_context` | high | decision_agent、review_agent、account_agent（投资相关） | 投资建议场景完全没有风险提醒 |

注意：

- 这些检查**不是** agent-specific 检查。它们对所有 Agent 都跑，但根据 `case.agent_name` 或 `case.metadata.agent_type` 决定是否对结果做 fatal/critical 升级。
- 当 case 明确是"账户概念解释"（`case.metadata.skip_investment_checks=True`）或类似标记时，投资风险类检查不应触发。
- 这些 checks 进入 `result.checks` 列表。`fatal` / `critical` / `high` failed check 会让 `result.status = failed`，从而影响 `Regression Gate`。

## 7. 与现有 Eval 体系集成

- 现有 static eval 通过 `run_eval_checks` 调度所有 check。P3 通用检查直接并入该函数。
- 通用检查对 `eval_scope=agent` 和 `eval_scope=node` 的 case 都会跑。
- 原有 `check_investment_safety` / `check_forbidden_phrases` 等继续保留，避免回归。P3 通用检查作为**增强层**，提供更明确的维度命名和 severity 口径。
- 后续 Stage 02–06 在 agent-specific check 里增加 `decision_agent` / `review_agent` / `account_agent` 的深度 check。

## 8. 不在本阶段范围内

明确说明：

1. 不新增 `trade_decision` 深度 case。
2. 不新增 `daily_position_review` 深度 case。
3. 不新增 `trade_review` 深度 case。
4. 不新增 `account_copilot` 深度 case。
5. 不做 outcome eval。
6. 不改 Regression Gate 逻辑。
7. 不改 Prompt 保存触发逻辑。
8. 不合入 main。
9. 不修改部署脚本。
10. 不提交敏感文件。
