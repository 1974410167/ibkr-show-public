# Stage 03 - Investment Thesis Card

请执行交易决策 Agent 优化 Stage 03：投资假设卡。

本地项目目录：

```text
<PROJECT_ROOT>
```

建议新建分支：

```text
feature/trade-decision-investment-thesis-card
```

本阶段目标：

让交易决策 Agent 不再泛泛地判断“股票好不好”，而是能判断：

```text
我为什么持有这只股票？
这个持有理由是否仍成立？
最大仓位是多少？
它是核心仓、机会仓，还是交易仓？
什么情况下停止加仓、减仓、清仓？
```

## 一、开始前必须读代码

至少阅读：

```text
ibkr_show_backend/app/agents/trade_decision_cards.py
ibkr_show_backend/app/services/trade_decision_composer.py
ibkr_show_backend/app/services/trade_decision_sub_agents.py
ibkr_show_backend/app/services/trade_decision_account_facts.py
ibkr_show_backend/app/services/trade_decision_risk_gate.py
ibkr_show_backend/tests/test_trade_decision_v2_cards.py
ibkr_show_backend/tests/test_trade_decision_langgraph.py
```

## 二、新增 InvestmentThesis 配置

新增文件建议：

```text
ibkr_show_backend/app/services/investment_thesis.py
```

定义：

```python
@dataclass
class InvestmentThesis:
    symbol: str
    role: str
    risk_class: str
    max_position_pct: float
    target_position_pct: float | None
    core_thesis: list[str]
    add_rules: list[str]
    hold_rules: list[str]
    sell_triggers: list[str]
    no_add_triggers: list[str]
    review_frequency: str
    metadata: dict
```

第一版用代码配置，不做 UI，不做数据库。

默认配置至少包含：

```text
AMD.US
MSTR.US
ORCL.US
MSFT.US
META.US
XIACY.US
SMCI.US
```

如果 symbol 未配置，使用 default thesis：

```text
role=unknown
risk_class=unknown
max_position_pct=0.05
```

## 三、建议默认配置

示例，不要求完全一致，但要体现差异化风险预算：

### AMD.US

```text
role=core_growth
risk_class=high_growth
max_position_pct=0.28
core_thesis:
- AI GPU 收入持续增长
- 数据中心业务增速高于整体
- 毛利率不恶化
sell_triggers:
- AI GPU 指引连续两个季度不及预期
- 数据中心收入同比转负
- 股价跌破 MA200 且基本面 orange/red
```

### MSTR.US

```text
role=btc_proxy
risk_class=extreme
max_position_pct=0.10
core_thesis:
- BTC 长期上涨
- MSTR 溢价可维持
sell_triggers:
- BTC 趋势 severe broken
- NAV 溢价大幅压缩
- 融资/稀释风险显著上升
```

### ORCL.US

```text
role=cloud_infra_growth
risk_class=medium_high_growth
max_position_pct=0.12
core_thesis:
- RPO 增长
- 云收入增长
- AI 基建需求兑现
sell_triggers:
- 云收入增速明显放缓
- CapEx 压力导致现金流恶化
```

## 四、接入 Account Facts / Card Pack

把 thesis 加进账户事实或 card_pack：

```text
AccountFactSnapshot.investment_thesis
或 TradeDecisionCardPack.investment_thesis
```

不要破坏已有序列化。

最终 decision_output 中增加：

```text
investment_thesis
thesis_status
thesis_risks
thesis_constraints
```

## 五、接入 Risk Gate

Risk Gate 必须使用 thesis：

```text
当前 position_pct >= thesis.max_position_pct → hold_no_add
risk_class=extreme → 禁止 add_batch，最多 add_on_pullback
sell_triggers 命中 → reduce_now / sell_thesis_broken
no_add_triggers 命中 → hold_no_add
```

如果没有 thesis，不要强行加仓：

```text
unknown thesis + 高风险标的 → wait / hold_no_add
```

## 六、接入 Composer

`position_advice.max_position_pct` 优先使用 thesis.max_position_pct，而不是所有股票都用一套通用 10%。

最终输出要能解释：

```text
该标的是 core_growth，最大仓位 28%
当前仓位 X%
距离最大仓位还有 Y%
```

## 七、测试要求

新增：

```text
tests/test_investment_thesis.py
```

覆盖：

1. AMD / MSTR / ORCL / MSFT / META / XIACY / SMCI 均有配置。
2. unknown symbol 返回 default thesis。
3. MSTR max_position_pct < AMD。
4. thesis max_position_pct 进入 position_advice。
5. 当前仓位超过 max_position_pct 时，RiskGate 输出 hold_no_add。
6. extreme risk_class 禁止 add_batch。
7. sell_trigger 命中时输出 sell_thesis_broken 或 reduce_now。
8. final decision 包含 investment_thesis 信息。

运行：

```bash
cd ibkr_show_backend
pytest tests/test_investment_thesis.py
pytest tests/test_trade_decision_risk_gate.py
pytest tests/test_trade_decision_composer.py
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
不要做 UI
不要写数据库迁移
```

## 九、提交

提交信息：

```text
feat(trade-decision): add investment thesis cards
```

推送：

```bash
git push origin feature/trade-decision-investment-thesis-card
```

## 十、最终输出

```text
# Stage 03 Investment Thesis Card 总结

## 分支信息
- 当前分支：
- commit：
- 是否已推送：
- 是否合入 main：否

## 实现内容
- InvestmentThesis：
- 默认配置：
- Account/Pack 接入：
- RiskGate 接入：
- Composer 输出：

## 测试结果
- test_investment_thesis：
- trade_decision 相关测试：
- full pytest：
- 前端测试：

## 遗留问题
无则写“无”。
```
