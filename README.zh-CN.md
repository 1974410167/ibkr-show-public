# IBKR Trade Agent

[English](README.md)

**面向真实 IBKR 账户的开源组合分析与 AI 研究工作台。**

大多数交易 Agent 只分析单只股票。**IBKR Trade Agent 从你的真实 IBKR 账户数据出发**，把账户历史、当前持仓、公开市场信息和 AI Agent 放进同一个复盘与研究流程。

IBKR Trade Agent 会把 IBKR Flex Query / 历史 CSV 中的账户、持仓、交易、现金流、股息等数据导入 Elasticsearch，通过 FastAPI 提供账户和 Agent API，并通过 Vue 前端提供组合看板、交易复盘、决策评估、市场事件跟踪和 AI 辅助研究。

**风险边界**：本项目**不是券商**，**不是自动交易机器人**，**不连接 IBKR 交易或下单接口**。它不会提交、修改、取消、路由或执行真实订单，只用于帮助用户基于账户数据和公开市场信息进行研究与复盘。

- **IBKR 是私有账户数据来源**：账户、持仓、交易、成本、盈亏、股息、入金和出金。
- **LongBridge 只用于公开市场数据**：行情、K 线、新闻、公告、财报、估值、基准和宏观信息。
- **LLM 是可选能力**：未配置 LLM 时，账户、持仓、交易、现金流、股息和基础市场事件页面仍可运行。
- **默认启用 Demo 模式**：没有 IBKR 账号也可以先体验产品。

## 功能概览

### 账户看板

- 账户总览：总权益、现金、市值、盈亏、时间加权收益率（TWR）、权益曲线和盈亏日历。
- 持仓分析：数量、均价、市价、市值、占比、日涨跌、集中度和资产分布。
- 交易记录：按日期、代码和方向筛选，支持排序、分页和 CSV 导出。
- 现金流与股息：入金、出金、预扣税、币种汇总和净到账。
- 市场事件：宏观事件、财报、公告、事件源配置、同步任务和事件影响上下文。

### AI Agent

- 每日持仓复盘：账户级每日复盘，可选 SMTP 邮件推送。
- 交易复盘 Agent：标的级和单笔交易复盘，包含评分和错误总结。
- 交易决策 Agent：加仓、持有、减仓、清仓或等待建议，包含风险门控、质量检查和结果回放。
- 风险评估 Agent：组合级风险评估，支持后台任务跟踪。
- Account Copilot：账户问答助手，支持工具调用、运行 trace、记忆、审批和监控。
- Agent 可观测与评测：任务图、运行 trace、回放快照、LLM/工具指标、结构化输出指标和回归评测工具。

### 市场数据集成

- LongBridge OAuth 一键授权，支持自动注册 Client ID。
- LongBridge OpenAPI / SDK / MCP 复用同一套 OAuth token。
- 只使用公开市场数据：行情、K 线、基准 ETF、新闻、公告、财报、估值和宏观信息。
- 不使用 LongBridge 账户、订单、成交、交易或下单接口。

### 后台与运维

- 后台页面覆盖 IBKR Flex、LLM Provider、LongBridge OAuth、Email SMTP、投资策略、Prompt 版本、市场事件、Agent 监控、评测 Harness 和系统状态。
- 系统状态页 `/admin/system` 聚合组件健康检查。
- Docker Compose 部署包含 Elasticsearch、Redis、backend、frontend 和 worker 服务。
- 提供发布安全扫描和 Docker 全链路验收脚本。

## 为什么选择 IBKR Trade Agent？

普通账户看板通常只展示持仓和收益；普通交易 Agent 往往只围绕单只股票做研究。IBKR Trade Agent 的出发点不同：从真实 IBKR 账户数据开始，把账户历史、当前持仓、真实交易、公开市场数据、财报新闻和 AI Agent 放进同一个研究流程。

它更适合长期投资者做账户级分析：仓位集中度、现金流、股息、已实现和未实现盈亏、复盘质量、决策纪律，以及决策后的效果评估。

## 架构

```text
IBKR Flex Query / CSV
        |
        v
Worker 导入与解析
        |
        v
Elasticsearch <---- FastAPI Backend ----> Redis 缓存 / 任务支持
        |                 |
        |                 v
        |          Agent 运行、trace、回放、评测
        |                 |
        v                 v
Vue 看板与后台控制台
```

后端保持 route 文件轻量，把业务逻辑放在 services 和 repositories 中。Worker 负责解析、转换、幂等写入 Elasticsearch 和每日调度导入。前端使用 Vue 3、Vite、TypeScript、PrimeVue 和 ECharts。

## 截图

| 账户曲线 | 盈亏日历 |
|----------|----------|
| <img src="docs/screenshots/readme/performance-curves.png" alt="账户权益、净收益、净成本和已实现盈亏曲线" width="100%"> | <img src="docs/screenshots/readme/performance-calendar.png" alt="按月查看每日盈亏表现" width="100%"> |
| 持仓全景 | 持仓分析 |
| <img src="docs/screenshots/readme/positions-treemap.png" alt="持仓全景图按仓位大小和行业着色展示当前组合" width="100%"> | <img src="docs/screenshots/readme/positions-allocation.png" alt="持仓集中度、资金类别和行业分布" width="100%"> |
| AI 决策 | AI 复盘 |
| <img src="docs/screenshots/readme/trade-decision-agent.png" alt="交易决策 Agent 输出持仓管理建议和评分维度" width="100%"> | <img src="docs/screenshots/readme/trade-review-agent.png" alt="交易复盘 Agent 展示最近复盘和标的级评分详情" width="100%"> |

## 快速开始

```bash
git clone https://github.com/1974410167/ibkr-trade-agent.git
cd ibkr-trade-agent
cp .env.example .env
docker compose up -d
```

首次启动会构建镜像，通常需要 3-5 分钟。启动后访问 `http://localhost:8080`，首次进入会引导创建管理员账号。

默认 `DEMO_MODE=true`，worker-init 会导入 AAPL、MSFT 等脱敏样例数据，无需 IBKR 账号即可体验页面。

## Demo 模式

- 默认 `DEMO_MODE=true`，样例数据是脱敏数据。
- 不需要 IBKR / LLM / LongBridge 凭据也能体验。
- 接入真实 IBKR 数据前建议清理 Docker volume：

```bash
docker compose down -v
# 修改 .env: DEMO_MODE=false
docker compose up -d
```

## 后台配置入口

业务配置全部在后台页面填写，正常使用时**不需要把这些密钥写入 `.env`**。

| 配置项 | 后台路径 |
|--------|----------|
| IBKR Flex Token / Query ID | `/admin/ibkr` |
| LLM Provider / API Key / 模型 | `/admin/llm` |
| LongBridge OAuth | `/admin/longbridge-mcp` |
| Email SMTP | `/admin/email` |
| 投资策略 | `/admin/investment-policy` |
| Prompt 版本 | `/admin/prompts` |
| 市场事件源 | `/admin/market-events` |
| Agent 监控 | `/admin/agent-monitoring` |
| Agent 评测 Harness | `/admin/harness` |
| 系统状态总览 | `/admin/system` |

普通用户不需要在 `.env` 里填写 IBKR Flex Token、LLM API Key、LongBridge Client ID、Email SMTP 密码等，全部通过后台页面配置。

## LongBridge 说明

- 进入 `/admin/longbridge-mcp`，点击授权按钮。
- 系统会自动注册 OAuth Client ID，并跳转到 LongBridge 授权页。
- 用户同意后，OpenAPI / SDK / MCP 复用同一套 OAuth token。
- LongBridge **只用于公开市场数据**：行情、K 线、基准 ETF、新闻、公告、财报、估值和宏观信息。
- LongBridge **不用于**账户、持仓、订单、成交、入金、出金或下单。

## 数据持久化

Docker Compose 使用三个 named volume：

| Volume | 内容 |
|--------|------|
| `es-data` | Elasticsearch 数据 |
| `redis-data` | Redis 缓存 |
| `backend-data` | `data/config/` 下的 JSON 配置文件 |

`backend-data` 中可能包含：

- `admin_auth.json`：管理员账号。
- `ibkr_flex.json`：IBKR Flex 配置。
- `llm_providers.json`：LLM Provider 列表。
- `longbridge_openapi_oauth.json`：LongBridge OAuth。
- `email.json`：Email SMTP 配置。
- `market_event_credentials.json`：市场事件源凭据。

> **注意**：这些文件可能包含 token 和 API Key，不要提交到 Git，备份时也要谨慎处理。

## 常用 Docker 命令

```bash
docker compose ps                        # 查看容器状态
docker compose logs -f backend           # 查看后端日志
docker compose logs -f worker-scheduler  # 查看 worker 日志
docker compose restart backend           # 重启某个服务
docker compose down                      # 停止所有服务
docker compose down -v                   # 停止并删除数据卷
docker compose build --no-cache && docker compose up -d  # 重新构建
```

## 自动化验收

```bash
scripts/verify_docker.sh
```

自动验证会检查 Docker Compose config / build / up、`/health`、Demo 数据导入、Bootstrap 初始化、登录态、`/api/admin/system/status` 和前端 HTML。脚本会临时写入验证用 `.env`，退出时恢复原 `.env`；失败时会打印关键日志。

```bash
# 验收后自动清理容器和数据卷
CLEANUP=1 scripts/verify_docker.sh
```

## 开发者模式

如果你需要本地开发而不是使用 Docker：

<details>
<summary>展开查看手动启动方式</summary>

### 环境要求

- Python 3.11+；推荐 Python 3.12，因为 CI 使用该版本。
- Node.js 18+；推荐 Node.js 20，因为 CI 使用该版本。
- Elasticsearch 8.x。
- Redis 推荐开启，用于缓存和任务相关流程。

### Backend

```bash
cd ibkr_show_backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Worker

```bash
cd ibkr_show_worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m worker.main init-es
python -m worker.main es-health
```

### Frontend

```bash
cd ibkr_show_frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

### 测试

```bash
# Backend
cd ibkr_show_backend && ./.venv/bin/python -m pytest

# Worker
cd ibkr_show_worker && ./.venv/bin/python -m pytest

# Frontend
cd ibkr_show_frontend && npm run test && npm run build
```

### 导入历史 CSV

```bash
# 单文件
cd ibkr_show_worker
python -m worker.main import-daily-file --file /path/to/file.csv

# 批量
find /path/to/folder -name '*.csv' -print0 | while IFS= read -r -d '' f; do
  python -m worker.main import-daily-file --file "$f"
done
```

</details>

## IBKR Flex Query 要求

建议在 Flex Query 中尽量勾选完整指标，至少覆盖：`ACCT`、`EQUT`、`POST`、`TRNT`、`CTRN`、`SECU`、`FIFO`、`MYTD`、`NETP`、`PPPO`、`CNAV`、`CRTT`、`UNBC`。缺失 section 会导致对应页面数据不完整。

## 常见问题

### 页面没有数据

先查看 `/admin/system` 系统状态页和 `docker compose logs worker-init --tail=100`，确认 ES 连接、Demo 数据导入是否正常。

### 登录账号是什么

首次启动通过页面创建管理员账号，不是 `.env` 中的默认密码。`.env` 中的 `AUTH_USERNAME` / `AUTH_PASSWORD` 仅作为应急 fallback。

### LongBridge 或 LLM 没配置能不能启动

可以。LongBridge 和 LLM 是可选能力。未配置时，账户、持仓、交易、现金流、股息和基础市场事件页面仍可运行。

### 如何重置管理员密码

删除 backend-data 中的 `data/config/admin_auth.json`，重启后重新初始化：

```bash
docker compose exec backend rm /app/ibkr_show_backend/data/config/admin_auth.json
docker compose restart backend
```

### 如何关闭 Demo 模式

```bash
# 修改 .env: DEMO_MODE=false
docker compose down -v
docker compose up -d
```

### 如何导入真实历史 CSV

通过后台 `/admin/ibkr` 页面上传，或：

```bash
docker compose cp your-file.csv backend:/app/ibkr_show_backend/data/your-file.csv
docker compose exec worker-scheduler python -m worker.main import-daily-file --file /app/ibkr_show_backend/data/your-file.csv
```

## 安全声明

- 本项目**不是投资建议**，LLM 输出仅供研究参考。
- 本项目**不是券商**，**不是自动交易机器人**。
- 本项目**不连接 IBKR 下单接口**，不会提交、修改、取消或路由订单。
- 本项目**不使用 LongBridge 账户、订单、成交或交易接口**。
- 使用者需自行承担投资风险。
- **不要公开部署**带真实账户数据的实例，除非放在内网、VPN 或反向代理认证之后。
- **不要提交** token、API Key、IBKR CSV、券商 statement、账户数据或生成的配置 JSON 到 Git。

## 公开仓库卫生

本仓库应保持适合公开分发。发布或同步公开副本前请运行：

```bash
scripts/check_release_safety.sh   # 扫描敏感信息泄露
scripts/verify_docker.sh          # Docker 全链路验收
```

公开仓库中不应包含私有部署细节、个人机器路径、服务器地址、凭据、下载的券商 statement、`.env` 文件或生成的 `data/config/*.json` 文件。

## Roadmap

- 更丰富的 Demo 组合数据和场景覆盖。
- 更完整的多用户和权限模型。
- 更完整的 Agent 正确性、回放和回归门禁评测覆盖。
- 更好的长任务和 Agent 运行运维看板。
- 更多市场事件数据源和事件影响分析。
- 更丰富的部署模板和发布流程加固。

## License

[MIT](LICENSE)
