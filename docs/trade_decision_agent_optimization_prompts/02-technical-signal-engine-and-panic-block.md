# Stage 02 - TechnicalSignalEngine & Panic Block

请执行交易决策 Agent 优化 Stage 02：TechnicalSignalEngine 与趋势破坏硬规则。

本地项目目录：

```text
<PROJECT_ROOT>
```

建议新建分支：

```text
feature/trade-decision-technical-signal-engine
```

本阶段目标：

把“趋势是否破坏”从 LLM 主观判断中抽离出来，先由确定性指标计算，再让 LLM 解释。

本阶段重点服务两个问题：

```text
1. 今天这种大跌，是正常波动还是趋势破坏？
2. 用户想情绪化卖出时，系统能不能用硬规则拦住？
```

## 一、开始前必须读代码

至少阅读：

```text
ibkr_show_backend/app/services/trade_decision_sub_agents.py
ibkr_show_backend/app/agents/trade_decision_cards.py
ibkr_show_backend/app/services/trade_decision_composer.py
ibkr_show_backend/app/services/trade_decision_risk_gate.py  # 如果 Stage 01 已存在
ibkr_show_backend/tests/test_trade_decision_v2_cards.py
ibkr_show_backend/tests/test_trade_decision_langgraph.py
```

重点看：

1. `MarketTrendSubAgent` 当前如何调用 quote / candlesticks。
2. `MarketTrendCard` 当前字段。
3. node trace 中 `structured_output` 如何保存。
4. `panic_blocked` 如果 Stage 01 已做，如何接入技术信号。

## 二、新增 TechnicalSignalEngine

新增文件建议：

```text
ibkr_show_backend/app/services/technical_signal_engine.py
```

输入：

```python
symbol_candlesticks: list[dict]
benchmark_candlesticks: dict[str, list[dict]]  # QQQ / SPY / SMH
quote: dict | None
```

输出结构建议：

```python
@dataclass
class TechnicalSignals:
    ma20: float | None
    ma50: float | None
    ma200: float | None
    ma20_slope: float | None
    ma50_slope: float | None
    ma200_slope: float | None
    atr14: float | None
    atr14_pct: float | None
    volume_ratio: float | None
    relative_strength_20d: dict[str, float]
    relative_strength_60d: dict[str, float]
    support_levels: list[float]
    resistance_levels: list[float]
    trend_break_level: str  # none / warning / broken / severe
    trend_break_reasons: list[str]
    data_limitations: list[str]
```

## 三、指标计算要求

至少实现：

```text
MA20 / MA50 / MA200
MA slope
ATR14
volume_ratio = latest_volume / avg_volume_20d
20d return
60d return
relative_strength_20d vs QQQ/SPY/SMH
relative_strength_60d vs QQQ/SPY/SMH
support/resistance 简化版
trend_break_level
```

支持字段兼容：

```text
close / c
high / h
low / l
volume / v
timestamp / date
```

如果数据不足，不报错，写入 `data_limitations`。

## 四、趋势破坏规则

第一版规则：

### warning

```text
收盘价 < MA20
或 单日跌幅较大且 volume_ratio > 1.3
```

### broken

```text
连续 3 日收盘价 < MA50
且 MA50 slope <= 0
```

### severe

```text
收盘价 < MA200
或 20d / 60d 相对 QQQ 和 SMH 都明显跑输
```

规则要保守，不要频繁 severe。

## 五、接入 MarketTrendSubAgent

`MarketTrendSubAgent` 调用 candlesticks 后，应先运行 `TechnicalSignalEngine`。

然后把 technical signals 放进：

```text
MarketTrendCard.technical_signals
MarketTrendCard.trend_break_level
MarketTrendCard.support_levels
MarketTrendCard.resistance_levels
MarketTrendCard.relative_strength_score
```

如果 dataclass 里没有字段，需要扩展 `MarketTrendCard`。

LLM prompt 中要增加约束：

```text
你必须基于 technical_signals 解释趋势；
不能覆盖 trend_break_level；
如果 LLM 结论和 technical_signals 冲突，最终以 technical_signals 为准。
```

## 六、接入 Risk Gate / panic_blocked

如果 Stage 01 已有 RiskGate：

```text
trend_break_level=severe → 不允许 add / add_batch
trend_break_level=broken → 只能 hold_no_add / wait / trim_on_rebound
trend_break_level=warning → 允许 hold，但禁止追涨加仓
```

panic_blocked 规则增强：

```text
用户想清仓
但 trend_break_level 只是 none/warning
且 fundamental 不是 red
且仓位不高
=> panic_blocked
```

如果 Stage 01 还没做，至少把 technical signals 输出到 final decision，供后续阶段使用。

## 七、测试要求

新增：

```text
tests/test_technical_signal_engine.py
```

覆盖：

1. MA20 / MA50 / MA200 计算正确。
2. ATR14 计算正确。
3. volume_ratio 计算正确。
4. relative strength 计算正确。
5. warning / broken / severe 规则命中。
6. 数据不足时不抛异常。
7. MarketTrendSubAgent 输出 technical_signals。
8. RiskGate 使用 trend_break_level 降级 action。
9. panic_blocked 能使用 trend_break_level。

运行：

```bash
cd ibkr_show_backend
pytest tests/test_technical_signal_engine.py
pytest tests/test_trade_decision_v2_cards.py
pytest tests/test_trade_decision_langgraph.py
pytest tests/test_trade_decision_risk_gate.py
pytest
```

## 八、安全边界

不要做：

```text
不要调用真实 IBKR
不要调用真实 LLM
不要部署线上
不要合入 main
不要改真实交易逻辑
不要自动创建 EvalCase
```

## 九、提交

提交信息：

```text
feat(trade-decision): add technical signal engine
```

推送：

```bash
git push origin feature/trade-decision-technical-signal-engine
```

## 十、最终输出

```text
# Stage 02 TechnicalSignalEngine 总结

## 分支信息
- 当前分支：
- commit：
- 是否已推送：
- 是否合入 main：否

## 实现内容
- TechnicalSignalEngine：
- MarketTrendCard 扩展：
- trend_break_level：
- panic_blocked 接入：

## 测试结果
- test_technical_signal_engine：
- trade_decision 相关测试：
- full pytest：
- 前端测试：

## 遗留问题
无则写“无”。
```
