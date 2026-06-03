# IBKR Show

IBKR 个人账户可视化与 AI 分析工具。把 IBKR Flex Query / 历史 CSV 中的账户、持仓、交易、现金流、股息解析到 Elasticsearch，通过 FastAPI 和 Vue 前端提供可视化查询、交易复盘和交易决策辅助。

- **IBKR 是个人账户数据唯一来源**（账户、持仓、交易、成本、盈亏、股息、出入金）
- **LongBridge 只用于公开市场数据**（行情、K 线、新闻、公告、财报、估值），不调用交易/账户/下单接口
- **LLM 是可选能力**，未配置时核心页面仍可运行
- **默认提供 Demo 模式**，没有 IBKR 账号也能体验完整功能

## 功能概览

- 账户总览 — 总权益、现金、市值、盈亏、TWR、权益曲线、盈亏日历
- 持仓分析 — 数量、均价、市价、市值、占比、日涨跌、集中度、资产分布
- 交易记录 — 按日期/代码/方向筛选、排序、分页、CSV 导出
- 出入金 / 股息 — 按币种汇总、预扣税、净到账
- 每日持仓复盘 — 自动生成 + SMTP 邮件推送
- 交易复盘 Agent — 标的级 / 单笔交易复盘，100 分制
- 交易决策 Agent — 加仓/持有/减仓/清仓建议 + 财报分析
- LLM Provider 后台配置 — 支持 OpenAI-compatible
- LongBridge OAuth 一键授权 — 自动注册 Client ID
- Email SMTP 配置
- 系统状态页 — `/admin/system` 聚合 10 个组件健康检查

| 账户曲线 | 盈亏日历 |
|----------|----------|
| <img src="docs/screenshots/readme/performance-curves.png" alt="账户权益、净收益、净成本和已实现盈亏曲线" width="100%"> | <img src="docs/screenshots/readme/performance-calendar.png" alt="按月查看每日盈亏表现" width="100%"> |
| 持仓全景 | 持仓分析 |
| <img src="docs/screenshots/readme/positions-treemap.png" alt="持仓全景图按仓位大小和行业着色展示当前组合" width="100%"> | <img src="docs/screenshots/readme/positions-allocation.png" alt="持仓集中度、资金类别和行业分布" width="100%"> |
| AI 决策 | AI 复盘 |
| <img src="docs/screenshots/readme/trade-decision-agent.png" alt="交易决策 Agent 输出持仓管理建议和评分维度" width="100%"> | <img src="docs/screenshots/readme/trade-review-agent.png" alt="交易复盘 Agent 展示最近复盘和标的级评分详情" width="100%"> |

## 快速开始

```bash
git clone <repo-url> ibkr_show
cd ibkr_show
cp .env.example .env
docker compose up -d
```

首次启动会构建镜像（约 3-5 分钟）。启动后访问 `http://localhost:8080`，首次进入会引导创建管理员账号。

默认 `DEMO_MODE=true`，worker-init 会自动导入脱敏样例数据（AAPL、MSFT 等），无需 IBKR 账号即可体验完整页面。

## 自动化验收

```bash
scripts/verify_docker.sh
```

自动验证：Docker Compose config / build / up、`/health`、Demo 数据导入、Bootstrap 初始化、登录态、`/api/admin/system/status`（10 个组件）、前端 HTML。失败时自动打印关键日志。

```bash
# 验收后自动清理容器和数据卷
CLEANUP=1 scripts/verify_docker.sh
```

## Demo 模式

- 默认 `DEMO_MODE=true`，样例数据是脱敏数据
- 不需要 IBKR / LLM / LongBridge 也能体验
- 接入真实 IBKR 前建议清理 volume：

```bash
docker compose down -v
# 修改 .env: DEMO_MODE=false
docker compose up -d
```

## 后台配置入口

业务配置全部在后台页面填写，**不需要在 .env 里填写**：

| 配置项 | 后台路径 |
|--------|----------|
| IBKR Flex Token / Query ID | `/admin/ibkr` |
| LLM Provider / API Key / Model | `/admin/llm` |
| LongBridge OAuth | `/admin/longbridge-mcp` |
| Email SMTP | `/admin/email` |
| 系统状态总览 | `/admin/system` |

普通用户不需要在 `.env` 里填写 IBKR Flex Token、LLM API Key、LongBridge Client ID、Email SMTP 密码等，全部通过后台页面配置。

## LongBridge 说明

- 普通用户只需进入 `/admin/longbridge-mcp`，点击"开始授权"
- 系统会自动注册 OAuth Client ID，跳转到 LongBridge 授权页
- 用户同意后，OpenAPI / SDK / MCP 复用同一套 OAuth token
- LongBridge **只用于公开市场数据**（行情、K 线、基准 ETF、资讯、公告、财报、估值）
- **不用于**账户、持仓、订单、成交、下单等私有数据

## 数据持久化

Docker Compose 使用三个 named volume：

| Volume | 内容 |
|--------|------|
| `es-data` | Elasticsearch 数据 |
| `redis-data` | Redis 缓存 |
| `backend-data` | 配置文件（`data/config/` 下的 JSON） |

`backend-data` 保存的配置文件：

- `admin_auth.json` — 管理员账号
- `ibkr_flex.json` — IBKR Flex 配置
- `llm_providers.json` — LLM Provider 列表
- `longbridge_openapi_oauth.json` — LongBridge OAuth
- `email.json` — Email SMTP 配置

> **注意**：这些文件可能包含 token 和 API Key，不要提交到 Git，备份时注意安全。

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

## 开发者模式

如果你需要本地开发而不是使用 Docker：

<details>
<summary>展开查看手动启动方式</summary>

### 环境要求

- Python 3.11+
- Node.js 18+
- Elasticsearch 8.x

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
# 后端
pytest ibkr_show_backend/tests

# Worker
pytest ibkr_show_worker/tests

# 前端
cd ibkr_show_frontend && npm run test && npm run build
```

### 导入历史 CSV

```bash
# 单文件
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

可以。LongBridge 和 LLM 是可选能力。未配置时，账户、持仓、交易、现金流、股息等 IBKR 本地数据页面仍可运行。

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
docker cp your-file.csv ibkr_show-backend-1:/app/ibkr_show_backend/data/
docker compose exec worker-scheduler python -m worker.main import-daily-file --file /app/ibkr_show_backend/data/your-file.csv
```

## 安全声明

- 本项目**不是投资建议**，LLM 输出仅供研究参考
- 使用者需自行承担投资风险
- **不要公开部署**带真实账户数据的实例，至少放在内网 / VPN / 反向代理认证后
- **不要提交** token、API Key、IBKR CSV、账户数据到 Git

## 发布前检查

```bash
scripts/check_release_safety.sh   # 扫描敏感信息泄露
scripts/verify_docker.sh          # Docker 全链路验收
```

## Roadmap

- 配置加密存储
- 更完善的多用户 / 权限模型
- 更丰富的 Demo 数据
- 更完整的 CI
- 更好的可观测性

## License

[MIT](LICENSE)

如果觉得对你有用，点个star吧
