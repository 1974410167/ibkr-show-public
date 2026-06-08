# 重点事件 / 市场事件中台

## 功能概览

市场事件中台用于提前跟踪宏观事件、美联储事件、公司事件、市场休市日和持仓相关新闻，帮助投资者在关键事件前后做好风险管理。

## 数据源

| 数据源 | 内容 | 需要 API Key |
|---|---|---|
| BLS | CPI、PPI、非农就业、失业率、JOLTS | 是 |
| BEA | GDP、PCE、个人收入支出 | 是 |
| FRED | 宏观时间序列备用/校验 | 是 |
| Fed | FOMC、SEP、会议纪要 | 否 |
| ISM | PMI | 否 |
| Longbridge | 财报、分红、拆股、IPO、休市、市场状态、交易时段、新闻 | 否（复用已有 Longbridge OpenAPI OAuth） |
| Manual | 后台手动维护的事件 | 否 |

## API Key 申请

### BLS
- 申请链接：https://data.bls.gov/registrationEngine/
- 说明：填写邮箱、组织名、验证码，获取免费 API Key。

### BEA
- 申请链接：https://apps.bea.gov/API/signup/
- 说明：填写邮箱和名称，获取 BEA UserID。

### FRED
- 申请链接：https://fred.stlouisfed.org/docs/api/api_key.html
- 说明：登录 FRED 账户后申请 API Key。

## 后台配置

进入：后台管理 > 宏观数据源

填写：
- BLS_API_KEY
- BEA_API_KEY
- FRED_API_KEY

说明：
- Key 加密保存在后端配置存储中
- 前端不会回显明文，只显示脱敏值（`****last4`）
- 不要把 key 写入代码或提交到 git
- Longbridge Provider uses Longbridge OpenAPI / SDK.
- MCP is not used by backend market event synchronization.
- Longbridge credentials are reused from existing Longbridge configuration and are not duplicated into market event credentials.
- Longbridge news only supports `news(symbol)` in market event sync; topic or keyword news should be implemented by a GenericNewsProvider or another dedicated news source.

## 同步方式

1. **手动同步**：在后台数据源配置页面点击"测试连接"
2. **dry_run**：预览模式，不写入数据库
3. **sync_run 日志**：每次同步都会记录到 `market_event_sync_runs` 索引

## 前台使用

- **重点事件页面**（`/market-events`）：风险总览卡片、事件列表、日历视图、事件详情
- **总览页**：未来 7 天重点事件卡片
- **持仓详情页**：影响该标的的未来事件（预留）

## 常见问题

### 为什么 CPI/FOMC 没显示？
- 检查 BLS/Fed 数据源是否启用
- 检查 BLS API Key 是否已配置
- 查看 sync_run 日志确认同步是否成功

### 为什么实际值为空？
- 实际值需要在事件发布后通过 BLS/BEA API 拉取
- 确认 API Key 已配置且有效
- 手动触发 VALUE 类型同步

### 如何检查数据源是否启用？
- 进入后台管理 > 宏观数据源
- 查看各数据源的启用状态

### 如何查看同步失败原因？
- 查看 sync_run 日志中的 error_message
- 检查后端日志

## 安全说明

- 不要提交 API Key 到 git
- 不要公开后台管理入口
- API 不会返回 raw_payload 给普通用户
- Key 加密保存在后端配置存储中，前端只展示脱敏值
- 后端配置文件权限为 0o600
