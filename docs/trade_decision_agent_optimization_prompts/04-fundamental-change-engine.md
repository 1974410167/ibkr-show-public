# Stage 04 - FundamentalChangeEngine

请执行交易决策 Agent 优化 Stage 04：基本面变化检测器。

本地项目目录：

```text
<PROJECT_ROOT>
```

建议新建分支：

```text
feature/trade-decision-fundamental-change-engine
```

本阶段目标：

让基本面节点不只回答“当前基本面好不好”，而是能判断：

```text
基本面是否比上一次决策变坏？
核心投资假设是否被证伪？
增长、利润率、现金流、指引是否发生变化？
```

## 一、开始前必须读代码

至少阅读：

```text
ibkr_show_backend/app/services/trade_decision_sub_agents.py
ibkr_show_backend/app/agents/trade_decision_cards.py
ibkr_show_backend/app/services/investment_thesis.py
ibkr_show_backend/app/services/trade_decision_risk_gate.py
ibkr_show_backend/tests/test_trade_decision_v2_cards.py
```

重点看：

1. `FundamentalValuationSubAgent` 当前拉取哪些数据。
2. `FundamentalValuationCard` 当前字段。
3. MCP 工具中 financial_report / valuation / business_segments / rating / forecast_eps 的返回结构。
4. Investment Thesis 是否已在 Stage 03 接入。

## 二、新增 FundamentalChangeEngine

新增文件建议：

```text
ibkr_show_backend/app/services/fundamental_change_engine.py
```

输入：

```text
financial_reports: list[dict]
valuation: dict | None
business_segments: list[dict] | None
institution_rating: dict | None
forecast_eps: dict | None
investment_thesis: InvestmentThesis | None
```

输出：

```python
@dataclass
class FundamentalChangeResult:
    fundamental_status: str  # green/yellow/orange/red/unknown
    thesis_broken: bool
    change_signals: list[str]
    positive_signals: list[str]
    negative_signals: list[str]
    revenue_growth_trend: str | None
    margin_trend: str | None
    cash_flow_trend: str | None
    guidance_change: str | None
    segment_growth_notes: list[str]
    evidence: list[dict]
    data_limitations: list[str]
```

## 三、核心检测规则

至少实现：

### 1. 收入增长放缓

最近 4 个季度收入同比 / 环比明显下降：

```text
change_signals += ["revenue_growth_slowdown"]
```

### 2. 利润率恶化

毛利率 / 营业利润率连续下降：

```text
change_signals += ["margin_compression"]
```

### 3. 现金流恶化

经营现金流下降或自由现金流转负：

```text
change_signals += ["cash_flow_deterioration"]
```

### 4. 指引下调

如果工具数据有 guidance / forecast 下调：

```text
change_signals += ["guidance_cut"]
```

### 5. 分部增长失效

如果 business_segments 中核心分部增速放缓：

```text
change_signals += ["segment_growth_failure"]
```

### 6. 投资假设破坏

结合 InvestmentThesis.sell_triggers 判断：

```text
thesis_broken = True
fundamental_status = red
```

第一版可以用关键词 + 指标规则，不需要完美。

## 四、股票差异化

至少支持不同 symbol 的关注点：

```text
AMD：data center revenue / AI GPU / margin
MSTR：BTC trend / NAV premium / dilution / financing cost
ORCL：RPO / cloud revenue / CapEx / cash flow
MSFT/META：cloud/AI capex/margin
XIACY：EV growth / smartphone margin / gross margin
SMCI：margin / inventory / customer concentration
```

如果缺少具体字段，写入 data_limitations，不要编造。

## 五、接入 FundamentalValuationSubAgent

在 `FundamentalValuationSubAgent` 获取财报/估值数据后运行 `FundamentalChangeEngine`。

扩展 `FundamentalValuationCard` 字段：

```text
fundamental_status
thesis_broken
change_signals
positive_signals
negative_signals
guidance_change
margin_trend
cash_flow_trend
segment_growth_notes
```

LLM 只能解释这些结果，不允许覆盖 `thesis_broken`。

## 六、接入 Risk Gate

Risk Gate 必须使用 fundamental_status：

```text
fundamental_status=red 或 thesis_broken=True → sell_thesis_broken / reduce_now
fundamental_status=orange → hold_no_add / trim_on_rebound
fundamental_status=yellow → 禁止 add_batch
fundamental_status=green → 正常按其他 gate 判断
```

## 七、测试要求

新增：

```text
tests/test_fundamental_change_engine.py
```

覆盖：

1. revenue growth slowdown 识别。
2. margin compression 识别。
3. cash flow deterioration 识别。
4. guidance cut 识别。
5. thesis_broken 识别。
6. 数据不足时输出 unknown + data_limitations。
7. FundamentalValuationCard 包含新字段。
8. RiskGate 根据 red/orange/yellow 降级 action。
9. 不编造缺失字段。

运行：

```bash
cd ibkr_show_backend
pytest tests/test_fundamental_change_engine.py
pytest tests/test_investment_thesis.py
pytest tests/test_trade_decision_risk_gate.py
pytest tests/test_trade_decision_v2_cards.py
pytest tests/test_trade_decision_langgraph.py
pytest
```

## 八、安全边界

不要做：

```text
不要调用真实 IBKR
不要调用真实 LLM
不要部署线上
不要合入 main
不要改数据库
不要做 UI
```

## 九、提交

提交信息：

```text
feat(trade-decision): add fundamental change engine
```

推送：

```bash
git push origin feature/trade-decision-fundamental-change-engine
```

## 十、最终输出

```text
# Stage 04 FundamentalChangeEngine 总结

## 分支信息
- 当前分支：
- commit：
- 是否已推送：
- 是否合入 main：否

## 实现内容
- FundamentalChangeEngine：
- FundamentalValuationCard 扩展：
- thesis_broken：
- RiskGate 接入：

## 测试结果
- test_fundamental_change_engine：
- trade_decision 相关测试：
- full pytest：
- 前端测试：

## 遗留问题
无则写“无”。
```
