# Stage 01 - TradeDecision Risk Gate & Action System

请执行交易决策 Agent 优化 Stage 01：Risk Gate 与 Action 体系升级。

本地项目目录：

```text
<PROJECT_ROOT>
```

建议新建分支：

```text
feature/trade-decision-risk-gate-action-system
```

本阶段目标：

把交易决策 Agent 从“交易建议生成器”升级成“能约束真实操作行为的决策系统”。

当前 P3.5 真实体检稳定暴露的问题：

```text
missing_risk_control
data_insufficient_but_confident
weak_signal_overstatement
```

本阶段优先修这些，不做大规模架构重构。

## 一、开始前必须读代码

至少阅读：

```text
ibkr_show_backend/app/agents/trade_decision_graph/nodes.py
ibkr_show_backend/app/services/trade_decision_composer.py
ibkr_show_backend/app/services/trade_decision_sub_agents.py
ibkr_show_backend/app/agents/trade_decision_cards.py
ibkr_show_backend/app/agents/eval_correctness_rubrics.py
ibkr_show_backend/app/agents/eval_failure_mining.py
ibkr_show_backend/tests/test_trade_decision_v2_cards.py
ibkr_show_backend/tests/test_trade_decision_langgraph.py
ibkr_show_backend/tests/test_eval_failure_mining_service.py
```

重点确认：

1. `TradeDecisionComposer._determine_action()` 当前已持仓高分基本返回 `hold`。
2. `execution_plan.invalid_conditions` 虽然有内容，但不是强制 gate。
3. P3.5 failure 里 `missing_risk_control` 是当前最稳定问题。
4. 当前 action 集合偏粗：`add / add_small / add_batch / hold / reduce / sell / wait / avoid / watchlist`。

## 二、核心要求

新增一个确定性 Risk Gate 层，必须在最终 action 输出前生效。

建议新增文件：

```text
ibkr_show_backend/app/services/trade_decision_risk_gate.py
```

核心结构建议：

```python
@dataclass
class RiskGateResult:
    original_action: str
    final_action: str
    blocked: bool
    downgraded: bool
    gate_reasons: list[str]
    required_disclosures: list[str]
    risk_flags: list[str]
    action_constraints: dict
```

Risk Gate 输入：

```text
AccountFactSnapshot
AccountFitCard
MarketTrendCard
FundamentalValuationCard
EventCatalystCard
RiskRewardCard
原始 action
score_detail
```

Risk Gate 输出必须进入 final decision：

```text
decision_output.risk_gate
decision_output.action
decision_output.execution_plan
decision_output.major_risks
decision_output.review_warnings
```

## 三、Action 体系升级

扩展 action 语义，至少支持：

```text
hold_no_add
add_on_pullback
add_right_side
trim_on_rebound
reduce_now
sell_thesis_broken
panic_blocked
```

兼容老 action，不要破坏现有前端。可以在 `normalize_action` 和 `ALLOWED_ACTIONS` 中加入新 action。

动作语义：

```text
hold_no_add：继续持有，但禁止加仓
add_on_pullback：只允许回调后加仓
add_right_side：只允许趋势确认后加仓
trim_on_rebound：反弹减仓
reduce_now：现在减仓
sell_thesis_broken：投资假设破坏，清仓/退出
panic_blocked：识别为情绪化卖出，拦截清仓
```

## 四、Risk Gate 规则

必须实现以下硬规则：

### 1. 缺少仓位上限，禁止加仓

如果 action in `{add, add_small, add_batch}`，但 `position_advice.max_position_pct` 为空或 <= 0：

```text
final_action = wait / hold_no_add
risk_flags += ["missing_position_limit"]
gate_reasons += ["缺少最大仓位上限，不能输出加仓建议"]
```

### 2. 缺少失效条件，禁止强加仓

如果 action in `{add, add_batch, add_right_side}`，但 execution_plan.invalid_conditions 为空：

```text
final_action = add_on_pullback 或 hold_no_add
risk_flags += ["missing_invalidation_conditions"]
```

### 3. 数据不足时降级

如果 public data fallback >= 2，或 risk_reward / market / fundamental 中 evidence_quality 低：

```text
confidence <= medium
action 降级为 wait / hold_no_add
risk_flags += ["insufficient_data"]
```

不能出现 `data_insufficient_but_confident`。

### 4. 弱催化不得强买入

如果 event_catalyst_card.catalyst_strength == weak 或 event score 很低，但 action 是 add / add_batch：

```text
final_action = add_on_pullback / wait / hold_no_add
risk_flags += ["weak_catalyst_downgrade"]
```

### 5. 高仓位禁止继续加仓

如果当前持仓比例 >= max_position_pct 或 account_fit_level == concentrated / poor：

```text
final_action = hold_no_add
risk_flags += ["position_limit_reached"]
```

### 6. 情绪化清仓拦截 panic_blocked

如果用户问题中出现“清仓、割肉、卖掉、受不了了、暴跌、恐慌”等意图，但：

```text
基本面不是 red
趋势不是 severe broken
仓位不高
风险收益卡没有 thesis broken
```

则：

```text
final_action = panic_blocked
risk_flags += ["panic_sell_blocked"]
```

第一版可基于 user_question + cards 做启发式判断。

## 五、Execution Plan 强化

所有可行动作必须输出：

```text
max_position_pct
suggested_target_position_pct
invalid_conditions
recheck_triggers
分批计划
```

如果无法满足，则 Risk Gate 降级，不允许输出加仓。

`execution_plan.plan` 中必须体现：

```text
第一笔做多少
什么时候加第二笔
什么时候停止加仓
什么时候复查
```

## 六、P3.5 EvalCase 联动

新增或更新 correctness check：

```text
risk_gate_blocks_missing_position_limit
risk_gate_requires_invalid_conditions
risk_gate_downgrades_insufficient_data
risk_gate_downgrades_weak_catalyst
risk_gate_blocks_over_position_add
risk_gate_detects_panic_sell
```

放在现有 eval check 体系里，不要另起炉灶。

如果已有相似 check，复用并增强。

## 七、测试要求

至少新增/更新测试：

```text
tests/test_trade_decision_risk_gate.py
tests/test_trade_decision_composer.py
tests/test_eval_correctness_rubrics.py
tests/test_eval_failure_mining_service.py
```

覆盖：

1. 缺少 max_position_pct 时，add_batch 被降级。
2. 缺少 invalid_conditions 时，add 被降级。
3. 数据不足时 confidence 降低，action 不允许 add。
4. 弱催化时不允许 add_batch。
5. 高仓位时输出 hold_no_add。
6. 情绪化清仓场景输出 panic_blocked。
7. final decision 里包含 risk_gate。
8. P3.5 中 missing_risk_control 类 failure 应减少或被 check 捕获。
9. 旧 action 兼容，不破坏现有前端字段。

运行：

```bash
cd ibkr_show_backend
pytest tests/test_trade_decision_risk_gate.py
pytest tests/test_trade_decision_composer.py
pytest tests/test_trade_decision_v2_cards.py
pytest tests/test_trade_decision_langgraph.py
pytest tests/test_eval_failure_mining_service.py
pytest
```

前端未改可不跑前端；若改前端必须跑：

```bash
cd ibkr_show_frontend
vue-tsc -b
npm run build
npx vitest run
```

## 八、安全边界

不要做：

```text
不要调用真实 IBKR
不要调用真实 LLM
不要部署线上
不要合入 main
不要自动创建 enabled EvalCase
不要修改 .env / admin_auth.json / AGENTS.md / CLAUDE.md
```

## 九、提交

提交信息：

```text
feat(trade-decision): add risk gate and action constraints
```

推送分支：

```bash
git push origin feature/trade-decision-risk-gate-action-system
```

## 十、最终输出

请输出：

```text
# Stage 01 Risk Gate & Action System 总结

## 分支信息
- 当前分支：
- commit：
- 是否已推送：
- 是否合入 main：否

## 修复内容
- RiskGate：
- Action 体系：
- panic_blocked：
- execution_plan：
- correctness checks：

## 测试结果
- test_trade_decision_risk_gate：
- test_trade_decision_composer：
- test_trade_decision_langgraph：
- full pytest：
- 前端测试：

## 遗留问题
无则写“无”。
```
