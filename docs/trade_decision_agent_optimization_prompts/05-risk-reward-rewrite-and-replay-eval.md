# Stage 05 - RiskReward Rewrite & Replay Eval

请执行交易决策 Agent 优化 Stage 05：风险收益重写与回放评估。

本地项目目录：

```text
<PROJECT_ROOT>
```

建议新建分支：

```text
feature/trade-decision-risk-reward-rewrite
```

本阶段目标：

重写 `RiskRewardSubAgent` 的规则层，不再使用“上涨 30% / 跌到成本 85%”这种简化逻辑。

同时补一层 replay eval，让后续可以用历史场景回放验证 Agent 决策质量。

## 一、开始前必须读代码

至少阅读：

```text
ibkr_show_backend/app/services/trade_decision_sub_agents.py
ibkr_show_backend/app/services/trade_decision_composer.py
ibkr_show_backend/app/services/technical_signal_engine.py
ibkr_show_backend/app/services/fundamental_change_engine.py
ibkr_show_backend/app/services/investment_thesis.py
ibkr_show_backend/app/agents/trade_decision_cards.py
ibkr_show_backend/app/services/eval_simulation_service.py
ibkr_show_backend/tests/test_trade_decision_v2_cards.py
```

重点看：

1. `RiskRewardSubAgent.generate()` 当前如何算 upside/downside。
2. `RiskRewardCard` 当前字段。
3. TechnicalSignalEngine 是否已输出 MA/ATR/support/resistance。
4. FundamentalChangeEngine 是否已输出 fundamental_status。
5. InvestmentThesis 是否提供 max_position_pct / risk_class。

## 二、新增 RiskRewardEngine

新增文件建议：

```text
ibkr_show_backend/app/services/risk_reward_engine.py
```

输入：

```text
AccountFactSnapshot
AccountFitCard
MarketTrendCard
FundamentalValuationCard
EventCatalystCard
InvestmentThesis
TechnicalSignals
```

输出：

```python
@dataclass
class RiskRewardEstimate:
    upside_potential_pct: float | None
    downside_risk_pct: float | None
    reward_risk_ratio: float | None
    downside_scenarios: list[dict]
    upside_scenarios: list[dict]
    stop_add_level: float | None
    invalidation_level: float | None
    trim_level: float | None
    wait_for_pullback: bool
    position_size_label: str
    max_position_pct: float
    confidence: str
    data_limitations: list[str]
```

## 三、下行风险算法

不要再用成本价作为主要下行。

下行风险应来自：

```text
MA200 距离
最近支撑位距离
2.5 * ATR 波动空间
基本面 orange/red 情景估值压缩
高波动标的风险惩罚
```

简化规则：

```text
downside_candidates = [
  price_to_ma200_pct,
  price_to_support_pct,
  2.5 * atr14_pct,
  fundamental_drawdown_pct
]
downside_risk_pct = max(abs(candidate))
```

注意：如果用户成本很低，也不能低估当前回撤风险。

## 四、上行空间算法

上行来自：

```text
分析师目标价
历史估值分位
阻力位
基本面 green/yellow 情景
事件催化
```

简化规则：

```text
upside_candidates = [
  price_to_target_price_pct,
  price_to_resistance_pct,
  scenario_growth_upside_pct
]
upside_potential_pct = conservative median / min positive candidate
```

如果数据不足，明确写入 data_limitations。

## 五、风险收益比

```text
reward_risk_ratio = upside_potential_pct / downside_risk_pct
```

保守规则：

```text
ratio < 1.0 → 不允许加仓
ratio 1.0 ~ 1.5 → hold_no_add / wait
ratio 1.5 ~ 2.0 → add_on_pullback
ratio > 2.0 → 可考虑 add_right_side，但仍受 RiskGate 限制
```

## 六、仓位建议

仓位建议必须结合：

```text
InvestmentThesis.max_position_pct
risk_class
current_position_pct
trend_break_level
fundamental_status
reward_risk_ratio
```

示例：

```text
risk_class=extreme → max_position_pct capped at 10%
trend_break_level=broken → no add
fundamental_status=orange → max target reduced 50%
reward_risk_ratio<1.5 → hold_no_add
```

## 七、接入 RiskRewardSubAgent

`RiskRewardSubAgent.generate()` 应优先使用 `RiskRewardEngine` 的确定性结果。

LLM 可以解释，但不能覆盖关键字段：

```text
upside_potential_pct
downside_risk_pct
reward_risk_ratio
max_position_pct
wait_for_pullback
```

扩展 `RiskRewardCard`：

```text
downside_scenarios
upside_scenarios
stop_add_level
invalidation_level
trim_level
risk_reward_confidence
```

## 八、接入 Composer / RiskGate

Composer 的 `_compute_score_detail` 风险收益评分要基于 `reward_risk_ratio`，而不是只看 rr.score。

RiskGate 使用：

```text
reward_risk_ratio < 1.0 → avoid / reduce_now
reward_risk_ratio < 1.5 → hold_no_add / wait
downside_risk_pct 过高 → 禁止 add_batch
```

## 九、Replay Eval

新增最小回放评估，不做复杂回测。

建议新增：

```text
ibkr_show_backend/app/services/trade_decision_replay_eval.py
```

功能：

```text
输入 historical scenario / saved simulation result / replay_snapshot
重新运行 composer/risk gate
输出当时建议是否符合当前规则
```

第一版只做离线 deterministic replay，不调用 LLM/IBKR。

输出：

```python
ReplayEvalResult:
    replay_id
    original_action
    replay_action
    action_changed
    rule_violations
    risk_gate_reasons
```

用于未来评估“历史某天 Agent 是否应该拦截交易”。

## 十、测试要求

新增：

```text
tests/test_risk_reward_engine.py
tests/test_trade_decision_replay_eval.py
```

覆盖：

1. 下行风险不用成本价低估。
2. MA200 / support / ATR 能生成 downside scenarios。
3. target_price / resistance 能生成 upside scenarios。
4. reward_risk_ratio < 1.0 禁止加仓。
5. MSTR risk_class=extreme 限制 max_position_pct。
6. trend broken 时 wait_for_pullback / hold_no_add。
7. fundamental red 时 risk_reward 降级。
8. RiskRewardCard 包含新字段。
9. Composer 使用 reward_risk_ratio 调整评分。
10. ReplayEval 不调用 LLM/IBKR。
11. ReplayEval 能发现原 action 违反当前 RiskGate。

运行：

```bash
cd ibkr_show_backend
pytest tests/test_risk_reward_engine.py
pytest tests/test_trade_decision_replay_eval.py
pytest tests/test_trade_decision_risk_gate.py
pytest tests/test_trade_decision_v2_cards.py
pytest tests/test_trade_decision_langgraph.py
pytest
```

## 十一、安全边界

不要做：

```text
不要调用真实 IBKR
不要调用真实 LLM
不要部署线上
不要合入 main
不要做真实交易
不要做自动回测收益承诺
```

## 十二、提交

提交信息：

```text
feat(trade-decision): rewrite risk reward engine
```

推送：

```bash
git push origin feature/trade-decision-risk-reward-rewrite
```

## 十三、最终输出

```text
# Stage 05 RiskReward Rewrite & Replay Eval 总结

## 分支信息
- 当前分支：
- commit：
- 是否已推送：
- 是否合入 main：否

## 实现内容
- RiskRewardEngine：
- downside scenarios：
- upside scenarios：
- RiskRewardCard 扩展：
- Composer/RiskGate 接入：
- ReplayEval：

## 测试结果
- test_risk_reward_engine：
- test_trade_decision_replay_eval：
- trade_decision 相关测试：
- full pytest：
- 前端测试：

## 遗留问题
无则写“无”。
```
