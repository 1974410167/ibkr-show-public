# 03 - 交易决策关键节点规则检查

## 阶段目标

为 `trade_decision` Agent 的关键 LLM 节点增加 node-specific eval checks。

第 01 阶段已经完成 Node Eval 数据模型扩展：

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

第 02 阶段已经支持：

```text
从 Agent Run / LLM Call / node_trace 创建 Node Eval Case
```

本阶段要实现：

```text
当 EvalCase.eval_scope = node 时
根据 agent_name + node_name 运行专门的节点级检查规则
```

目标是让系统不只知道：

```text
trade_decision 最终回答失败了
```

还要能定位：

```text
event_catalyst 节点强行归因
fundamental_valuation 节点机械使用 PE
risk_control 节点缺少仓位约束
final_decision 节点过度自信
```

本阶段只做后端规则检查，不做 UI，不做 include_node_eval。

---

## 当前背景

当前已有评测检查体系：

```text
eval_checks.py
eval_domain_checks.py
run_eval_checks(...)
run_agent_specific_checks(...)
```

当前已有 agent-level trade_decision 检查，例如：

```text
trade_decision_no_all_in
trade_decision_no_mechanical_pe
trade_decision_event_catalyst_support
trade_decision_data_missing_conservatism
trade_decision_risks_or_limitations
```

本阶段要增加 node-level checks。

---

## 重点文件

后端重点文件：

```text
ibkr_show_backend/app/agents/eval_checks.py
ibkr_show_backend/app/agents/eval_domain_checks.py
ibkr_show_backend/app/services/agent_eval_service.py
ibkr_show_backend/tests/test_agent_eval_service.py
```

如有必要可以新增：

```text
ibkr_show_backend/app/agents/eval_node_checks.py
ibkr_show_backend/tests/test_eval_node_checks.py
```

推荐新增 `eval_node_checks.py`，避免 `eval_domain_checks.py` 继续膨胀。

---

## 一、适用范围

本阶段只覆盖：

```text
agent_name = trade_decision
eval_scope = node
```

先支持以下关键节点：

```text
market_trend
fundamental_valuation
event_catalyst
risk_control
final_decision
```

如果 node_name 不在上述列表：

```text
运行通用 node_quality checks
不要报错
```

---

## 二、Node Eval 输入输出约定

Node Eval Case 的 `metadata.output` 或待评估 output 可能是 dict，也可能包含自然语言字段。

检查函数需要兼容以下字段：

```text
summary
analysis
conclusion
decision
recommendation
rationale
risks
limitations
confidence
evidence
data_sources
```

如果 output 是 dict：

```python
text = 将所有 string/list/dict 中的文本安全拼接
```

如果 output 为空：

```text
返回 warning 或 failed check，不要抛异常
```

建议新增 helper：

```python
def flatten_text(value: Any) -> str:
    ...
```

---

## 三、通用 Node Checks

所有 node eval case 都执行基础 node quality checks：

### 1. node_output_not_empty

要求：

```text
节点输出不能为空
```

失败条件：

```text
output 为空 dict
output 文本为空
只有 null / 空数组 / 空字符串
```

severity:

```text
high
```

### 2. node_mentions_uncertainty_or_limitations

要求：

```text
节点输出应说明不确定性、数据限制或假设
```

关键词可以包含：

```text
不确定
风险
限制
假设
可能
需要进一步验证
data limitation
uncertain
risk
assumption
```

severity:

```text
medium
```

### 3. node_avoids_overconfidence

要求：

```text
节点输出不能过度确定
```

危险表达：

```text
必然
一定
毫无疑问
绝对
肯定上涨
无风险
稳赚
all in
must buy
guaranteed
risk-free
```

severity:

```text
high
```

---

## 四、market_trend 节点检查

节点职责：

```text
分析市场趋势、价格走势、成交量、技术形态，但不能把短期走势直接等同于买入结论。
```

### 1. market_trend_mentions_trend_basis

要求输出至少提到趋势依据之一：

```text
价格走势
成交量
均线
支撑
阻力
波动率
相对强弱
趋势
volume
moving average
support
resistance
momentum
```

否则 failed。

severity:

```text
medium
```

### 2. market_trend_no_price_action_to_buy_jump

禁止：

```text
因为上涨，所以应该买入
因为突破，所以一定加仓
只基于 K 线直接给强买入
```

关键词/模式可简单实现：

```text
上涨 -> 买入
突破 -> 必买
强势 -> all in
```

severity:

```text
high
```

### 3. market_trend_mentions_timeframe

要求说明时间周期或短中长期语境：

```text
短期
中期
长期
日线
周线
近几日
近一个月
timeframe
short-term
medium-term
long-term
```

severity:

```text
low
```

---

## 五、fundamental_valuation 节点检查

节点职责：

```text
分析基本面、财务、估值、增长质量，避免机械 PE 或单指标判断。
```

### 1. fundamental_valuation_no_mechanical_pe

禁止机械 PE 判断：

```text
PE 低所以买
PE 高所以卖
市盈率低所以低估
市盈率高所以高估
```

除非同时出现增长、利润、现金流、行业对比等解释。

severity:

```text
high
```

### 2. fundamental_valuation_mentions_business_or_financials

要求至少提到以下任意维度：

```text
收入
利润
毛利率
现金流
资产负债
增长
营收
业务
订单
市场份额
revenue
profit
margin
cash flow
growth
balance sheet
```

severity:

```text
medium
```

### 3. fundamental_valuation_mentions_uncertainty

要求说明估值不确定性，例如：

```text
估值假设
盈利预测
增长不确定
行业周期
利率
折现率
assumption
forecast
uncertainty
cycle
```

severity:

```text
medium
```

### 4. fundamental_valuation_no_direct_trade_decision

基本面节点不应该直接输出最终交易指令：

```text
立即买入
直接加仓
马上卖出
all in
strong buy now
```

severity:

```text
medium
```

---

## 六、event_catalyst 节点检查

节点职责：

```text
分析事件催化，包括财报、产品、监管、宏观、公司公告、行业事件。
```

### 1. event_catalyst_requires_specific_event

要求至少出现明确事件或事件类型：

```text
财报
发布会
产品发布
监管
并购
订单
指引
降息
政策
公告
earnings
guidance
launch
regulation
merger
order
policy
```

如果完全没有具体事件，failed。

severity:

```text
high
```

### 2. event_catalyst_no_forced_attribution

禁止强行归因：

```text
股价上涨说明有利好
涨了所以一定有催化
市场上涨证明事件积极
```

severity:

```text
high
```

### 3. event_catalyst_distinguishes_confirmed_vs_expected

要求区分：

```text
已发生
预期
传闻
待确认
可能
confirmed
expected
rumor
pending
```

severity:

```text
medium
```

### 4. event_catalyst_mentions_evidence_or_source

要求说明证据或来源类型：

```text
公告
财报
新闻
公司披露
管理层
市场数据
filing
press release
news
management
source
```

severity:

```text
medium
```

---

## 七、risk_control 节点检查

节点职责：

```text
识别风险、仓位约束、止损、分批、最大回撤和不确定性。
```

### 1. risk_control_mentions_position_sizing

要求提到仓位或分批：

```text
仓位
分批
轻仓
加仓比例
持仓比例
position size
sizing
tranche
scale in
```

severity:

```text
high
```

### 2. risk_control_mentions_downside_or_stop

要求提到下行风险或退出条件：

```text
下跌
回撤
止损
失效条件
风险点
跌破
downside
drawdown
stop loss
invalidation
```

severity:

```text
high
```

### 3. risk_control_no_all_in

禁止：

```text
满仓
梭哈
all in
重仓无脑买
```

severity:

```text
critical
```

### 4. risk_control_mentions_user_constraints

要求提到用户约束之一：

```text
现金比例
已有仓位
组合风险
保证金
集中度
回撤承受
cash
portfolio
margin
concentration
drawdown tolerance
```

severity:

```text
medium
```

---

## 八、final_decision 节点检查

节点职责：

```text
综合前面节点信息，给出最终交易建议，但必须保守、可执行、有风险约束。
```

### 1. final_decision_has_action_and_reason

要求包含明确动作和理由：

动作：

```text
买入
卖出
持有
等待
分批
加仓
减仓
buy
sell
hold
wait
scale
```

理由：

```text
因为
基于
考虑到
原因
rationale
because
due to
```

severity:

```text
medium
```

### 2. final_decision_no_weak_signals_to_strong_buy

禁止把弱信号叠加强买入：

```text
多个不确定因素 -> 强烈买入
可能利好 -> 必须加仓
趋势不错 + 估值不贵 -> 重仓
```

可以用关键词近似检查：

```text
可能/不确定/有限/待确认 与 强买入/重仓/大幅加仓/all in 同时出现
```

severity:

```text
high
```

### 3. final_decision_mentions_risk_controls

要求最终决策包含风险控制：

```text
分批
仓位
止损
观察
回撤
条件
risk
position
stop
condition
```

severity:

```text
high
```

### 4. final_decision_no_all_in

禁止：

```text
all in
满仓
梭哈
无脑买
```

severity:

```text
critical
```

---

## 九、实现方式

### 1. 新增入口函数

建议新增：

```python
def run_node_specific_checks(output: dict, case: dict, replay: dict | None = None) -> list[EvalCheckResult]:
    ...
```

逻辑：

```python
if case.eval_scope != "node":
    return []

if case.agent_name != "trade_decision":
    return run_generic_node_checks(...)

node_name = case.node_name

generic_checks = run_generic_node_checks(...)
specific_checks = run_trade_decision_node_checks(node_name, output, case)

return generic_checks + specific_checks
```

### 2. 接入 run_eval_checks

在现有 `run_eval_checks(...)` 或 `_evaluate_case(...)` 中接入。

要求：

```text
Agent-level case 不运行 node-specific checks
Node-level case 运行 generic node checks + node-specific checks
```

### 3. EvalCheckResult 格式

所有 check 返回结构要和现有保持一致：

```python
EvalCheckResult(
    check_name="event_catalyst_requires_specific_event",
    passed=True/False,
    severity="high",
    score=...,
    max_score=...,
    message="..."
)
```

不要引入新结果格式。

---

## 十、测试要求

### 1. 新增 eval_node_checks 单元测试

如果新增 `eval_node_checks.py`，建议新增：

```text
ibkr_show_backend/tests/test_eval_node_checks.py
```

覆盖：

#### 通用 checks

1. output 为空时 node_output_not_empty failed。
2. output 有不确定性说明时 node_mentions_uncertainty_or_limitations passed。
3. output 出现 all in / 绝对 等过度自信词时 node_avoids_overconfidence failed。

#### market_trend

4. 有趋势依据时 market_trend_mentions_trend_basis passed。
5. 只说上涨所以买入时 market_trend_no_price_action_to_buy_jump failed。

#### fundamental_valuation

6. 只说 PE 低所以买时 fundamental_valuation_no_mechanical_pe failed。
7. 提到收入/利润/现金流时 business_or_financials passed。

#### event_catalyst

8. 没有具体事件时 event_catalyst_requires_specific_event failed。
9. 股价上涨说明有利好时 event_catalyst_no_forced_attribution failed。
10. 区分已发生/预期时 distinguishes_confirmed_vs_expected passed。

#### risk_control

11. 没有仓位/分批时 risk_control_mentions_position_sizing failed。
12. 出现 all in / 满仓时 risk_control_no_all_in critical failed。

#### final_decision

13. 没有风险控制时 final_decision_mentions_risk_controls failed。
14. 弱信号 + 强买入时 final_decision_no_weak_signals_to_strong_buy failed。

### 2. Service 测试

在 `test_agent_eval_service.py` 中新增：

1. eval_scope=agent 不运行 node checks。
2. eval_scope=node 且 node_name=event_catalyst 会运行 event_catalyst checks。
3. eval_scope=node 且未知 node_name 会运行 generic node checks。
4. EvalRun result metadata 仍包含 eval_scope/node_name。

### 3. 测试命令

至少运行：

```bash
pytest ibkr_show_backend/tests/test_eval_node_checks.py
pytest ibkr_show_backend/tests/test_agent_eval_service.py
```

如果时间允许，运行：

```bash
pytest
```

---

## 十一、验收标准

1. Node Eval Case 会触发 node-specific checks。
2. Agent Eval Case 不会触发 node-specific checks。
3. `trade_decision/event_catalyst` 能识别：
   - 缺少具体事件
   - 强行归因
   - 未区分已发生/预期
4. `trade_decision/fundamental_valuation` 能识别：
   - 机械 PE
   - 缺少财务/业务依据
5. `trade_decision/risk_control` 能识别：
   - 缺少仓位约束
   - all in / 满仓
6. `trade_decision/final_decision` 能识别：
   - 缺少风险控制
   - 弱信号强买入
7. 所有结果仍然进入 EvalRun.results.checks。
8. 不影响现有 Agent-level eval。

---

## 十二、不允许做什么

- 不要做前端 UI。
- 不要做 include_node_eval。
- 不要做 Coverage Node UI。
- 不要做 Graph Mock Replay。
- 不要调用 LLM 做判断。
- 不要引入新依赖。
- 不要让 Agent Eval 误跑 Node Checks。
- 不要修改现有 check result 格式。
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
feat(eval): add trade decision node checks
```

阶段总结必须包含：

```text
阶段：03 - 交易决策关键节点规则检查
当前分支：
commit sha：
修改文件：
新增检查模块：
新增 check_name：
适用节点：
测试命令：
测试结果：
遗留问题：
下一阶段风险：
是否已推送远程：
是否合入 main：否
```
