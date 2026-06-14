# IBKR Trade Agent

**Open-source portfolio analytics and AI research workspace for real IBKR portfolios.**

Most trading agents analyze stocks in isolation. **IBKR Trade Agent starts from your actual IBKR account data**, then combines portfolio history, current holdings, public market context, and AI agents into one review workflow.

[中文文档](README.zh-CN.md)

![License](https://img.shields.io/badge/license-MIT-green.svg)
![GitHub stars](https://img.shields.io/github/stars/1974410167/ibkr-trade-agent?style=social)
![Docker Compose](https://img.shields.io/badge/Docker%20Compose-ready-2496ED?logo=docker&logoColor=white)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Vue 3](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)

IBKR Trade Agent imports IBKR Flex Query data or historical CSV files into Elasticsearch, serves account and agent APIs through FastAPI, and provides a Vue dashboard for portfolio monitoring, trade replay, decision review, market-event tracking, and AI-assisted research.

**Risk boundary**: this project is **not a broker**, **not an auto-trading bot**, and **does not connect to IBKR trading APIs or order placement APIs**. It does not submit, modify, cancel, route, or execute live orders. It only analyzes account data and public market context to support human research and review.

- **IBKR is the source of truth for private account data**: balances, positions, trades, cost basis, PnL, dividends, deposits, and withdrawals.
- **LongBridge is used only for public market data**: quotes, candles, news, announcements, earnings, valuation, benchmarks, and macro context.
- **LLM features are optional**: core account, position, trade, cash-flow, dividend, and market-event pages can run without an LLM provider.
- **Demo mode is enabled by default**: you can explore the product without an IBKR account.

## Features

### Portfolio Dashboard

- Account overview: total equity, cash, market value, PnL, Time-Weighted Return (TWR), equity curves, and PnL calendar.
- Position analytics: quantity, average cost, market price, market value, allocation, daily move, concentration, and asset distribution.
- Trade records: filter by date, symbol, and side; sort, paginate, and export CSV.
- Cash flows and dividends: deposits, withdrawals, withholding tax, currency summaries, and net cash received.
- Market events: macro events, earnings, announcements, source configuration, sync runs, and event impact context.

### AI Agents

- Daily position review: account-level daily review with optional SMTP delivery.
- Trade review agent: symbol-level and single-trade review with scoring and mistake summaries.
- Trade decision agent: add, hold, reduce, exit, or wait suggestions with risk gates, quality checks, and outcome replay.
- Risk assessment agent: portfolio-level risk assessment with background task tracking.
- Account Copilot: conversational account assistant with tool calls, run traces, memory, approvals, and monitoring.
- Agent observability: task graph, run trace, replay snapshots, LLM/tool metrics, structured-output metrics, and regression/evaluation harnesses.

### Market Data Integration

- LongBridge OAuth one-click authorization with automatic Client ID registration.
- LongBridge OpenAPI / SDK / MCP reuse the same OAuth token.
- Public market data only: quotes, candles, benchmark ETFs, news, announcements, earnings, valuation, and macro context.
- No LongBridge account, order, execution, or trading API usage.

### Admin & Operations

- Admin pages for IBKR Flex, LLM providers, LongBridge OAuth, Email SMTP, investment policy, prompt versions, market events, agent monitoring, evaluation harnesses, and system status.
- System status page at `/admin/system` with component health checks.
- Docker Compose deployment with Elasticsearch, Redis, backend, frontend, and worker services.
- Release safety and Docker verification scripts for public distribution checks.

## Why IBKR Trade Agent?

Most portfolio dashboards stop at positions and returns. Most trading agents focus on single-stock research. IBKR Trade Agent is built around a different idea: start from the investor's real IBKR account, then combine account history, holdings, realized trades, public market data, earnings/news context, and AI agents into one research workflow.

It is designed for long-term investors who care about account-level analysis: portfolio concentration, cash movement, dividends, realized and unrealized performance, review quality, decision discipline, and post-decision evaluation.

## Architecture

```text
IBKR Flex Query / CSV
        |
        v
Worker ingestion and parsers
        |
        v
Elasticsearch <---- FastAPI backend ----> Redis cache / task support
        |                 |
        |                 v
        |          Agent runtime, traces, replay, eval
        |                 |
        v                 v
Vue dashboard and admin console
```

The backend keeps route files thin and puts business logic in services and repositories. The worker owns parsing, transformation, idempotent Elasticsearch upserts, and scheduled daily imports. The frontend uses Vue 3, Vite, TypeScript, PrimeVue, and ECharts.

## Screenshots

| Account Curves | PnL Calendar |
|----------|----------|
| <img src="docs/screenshots/readme/performance-curves.png" alt="Account equity, net earnings, net cost, and realized PnL curves" width="100%"> | <img src="docs/screenshots/readme/performance-calendar.png" alt="Monthly calendar view of daily PnL performance" width="100%"> |
| Position Overview | Position Analytics |
| <img src="docs/screenshots/readme/positions-treemap.png" alt="Position treemap colored by allocation and sector" width="100%"> | <img src="docs/screenshots/readme/positions-allocation.png" alt="Position concentration, asset category, and sector distribution" width="100%"> |
| AI Decision Agent | AI Trade Review |
| <img src="docs/screenshots/readme/trade-decision-agent.png" alt="Trade decision agent with position management suggestions and scoring dimensions" width="100%"> | <img src="docs/screenshots/readme/trade-review-agent.png" alt="Trade review agent with recent reviews and symbol-level scoring details" width="100%"> |

## Quick Start

```bash
git clone https://github.com/1974410167/ibkr-trade-agent.git
cd ibkr-trade-agent
cp .env.example .env
docker compose up -d
```

The first startup builds Docker images and usually takes about 3-5 minutes. After startup, open `http://localhost:8080`. The first visit will guide you through administrator account creation.

`DEMO_MODE=true` is enabled by default. The worker init service imports sanitized sample data such as AAPL and MSFT, so you can explore the UI without an IBKR account.

## Demo Mode

- `DEMO_MODE=true` is enabled by default, and sample data is sanitized.
- IBKR, LLM, and LongBridge credentials are not required for demo usage.
- Before connecting real IBKR data, clear Docker volumes:

```bash
docker compose down -v
# Edit .env: DEMO_MODE=false
docker compose up -d
```

## Admin Configuration

Business configuration is entered in the admin UI. You do **not** need to put these secrets in `.env` for normal use.

| Setting | Admin path |
|--------|----------|
| IBKR Flex Token / Query ID | `/admin/ibkr` |
| LLM Provider / API Key / Model | `/admin/llm` |
| LongBridge OAuth | `/admin/longbridge-mcp` |
| Email SMTP | `/admin/email` |
| Investment policy | `/admin/investment-policy` |
| Prompt versions | `/admin/prompts` |
| Market event sources | `/admin/market-events` |
| Agent monitoring | `/admin/agent-monitoring` |
| Agent evaluation harness | `/admin/harness` |
| System status overview | `/admin/system` |

Normal users do not need to put IBKR Flex Token, LLM API Key, LongBridge Client ID, or Email SMTP passwords in `.env`. Configure them through the admin pages instead.

## LongBridge Notes

- Go to `/admin/longbridge-mcp` and click the authorization button.
- The system automatically registers an OAuth Client ID and redirects to LongBridge authorization.
- After consent, OpenAPI / SDK / MCP reuse the same OAuth token.
- LongBridge is used **only for public market data**: quotes, candles, benchmark ETFs, news, announcements, earnings, valuation, and macro context.
- LongBridge is **not used for** account data, positions, orders, executions, deposits, withdrawals, or order placement.

## Data Persistence

Docker Compose uses three named volumes:

| Volume | Contents |
|--------|------|
| `es-data` | Elasticsearch data |
| `redis-data` | Redis cache |
| `backend-data` | JSON config files under `data/config/` |

Files stored in `backend-data` may include:

- `admin_auth.json`: administrator account.
- `ibkr_flex.json`: IBKR Flex configuration.
- `llm_providers.json`: LLM provider list.
- `longbridge_openapi_oauth.json`: LongBridge OAuth.
- `email.json`: Email SMTP configuration.
- `market_event_credentials.json`: market-event provider credentials.

> **Note**: these files may contain tokens and API keys. Do not commit them to Git, and handle backups carefully.

## Common Docker Commands

```bash
docker compose ps                        # Check container status
docker compose logs -f backend           # Backend logs
docker compose logs -f worker-scheduler  # Worker logs
docker compose restart backend           # Restart one service
docker compose down                      # Stop all services
docker compose down -v                   # Stop and delete volumes
docker compose build --no-cache && docker compose up -d  # Rebuild
```

## Automated Verification

```bash
scripts/verify_docker.sh
```

The verification script checks Docker Compose config / build / up, `/health`, demo data import, bootstrap initialization, authenticated session behavior, `/api/admin/system/status`, and frontend HTML. It temporarily writes a verification `.env`, restores the original `.env` on exit, and prints relevant logs when a check fails.

```bash
# Clean containers and volumes after verification
CLEANUP=1 scripts/verify_docker.sh
```

## Developer Mode

If you want local development instead of Docker:

<details>
<summary>Show manual startup instructions</summary>

### Requirements

- Python 3.11+; Python 3.12 is recommended because CI uses it.
- Node.js 18+; Node.js 20 is recommended because CI uses it.
- Elasticsearch 8.x.
- Redis is recommended for cache and task-related flows.

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

### Tests

```bash
# Backend
cd ibkr_show_backend && ./.venv/bin/python -m pytest

# Worker
cd ibkr_show_worker && ./.venv/bin/python -m pytest

# Frontend
cd ibkr_show_frontend && npm run test && npm run build
```

### Import Historical CSV

```bash
# Single file
cd ibkr_show_worker
python -m worker.main import-daily-file --file /path/to/file.csv

# Batch
find /path/to/folder -name '*.csv' -print0 | while IFS= read -r -d '' f; do
  python -m worker.main import-daily-file --file "$f"
done
```

</details>

## IBKR Flex Query Requirements

When creating an IBKR Flex Query, include as many metrics as possible. At minimum, cover: `ACCT`, `EQUT`, `POST`, `TRNT`, `CTRN`, `SECU`, `FIFO`, `MYTD`, `NETP`, `PPPO`, `CNAV`, `CRTT`, and `UNBC`. Missing sections may make some pages incomplete.

## FAQ

### The pages show no data

Check the `/admin/system` status page and `docker compose logs worker-init --tail=100` first. Confirm that Elasticsearch is connected and demo data import completed.

### What is the login account?

On first startup, create the administrator account through the page. It is not the default password in `.env`. `AUTH_USERNAME` / `AUTH_PASSWORD` in `.env` are only emergency fallbacks.

### Can the app start without LongBridge or LLM configuration?

Yes. LongBridge and LLM are optional. Without them, local IBKR account, position, trade, cash-flow, dividend, and basic market-event pages can still run.

### How do I reset the administrator password?

Delete `data/config/admin_auth.json` from `backend-data`, then restart the backend:

```bash
docker compose exec backend rm /app/ibkr_show_backend/data/config/admin_auth.json
docker compose restart backend
```

### How do I disable demo mode?

```bash
# Edit .env: DEMO_MODE=false
docker compose down -v
docker compose up -d
```

### How do I import real historical CSV files?

Upload files through the `/admin/ibkr` page, or run:

```bash
docker compose cp your-file.csv backend:/app/ibkr_show_backend/data/your-file.csv
docker compose exec worker-scheduler python -m worker.main import-daily-file --file /app/ibkr_show_backend/data/your-file.csv
```

## Safety Statement

- This project is **not investment advice**. LLM output is for research reference only.
- This project is **not a broker** and **not an automated trading bot**.
- This project **does not connect to IBKR order placement APIs** and does not place trades.
- This project **does not use LongBridge account, order, execution, or trading APIs**.
- Users are responsible for their own investment decisions and risk.
- Do **not publicly deploy** an instance that contains real account data unless it is protected by an internal network, VPN, or reverse-proxy authentication.
- Do **not commit** tokens, API keys, IBKR CSV files, broker statements, account data, or generated config JSON files to Git.

## Public Repository Hygiene

This repository is intended to be safe for public distribution. Before publishing a release or synchronizing a public copy, run:

```bash
scripts/check_release_safety.sh   # Scan for sensitive information leaks
scripts/verify_docker.sh          # End-to-end Docker verification
```

The public repository should never contain private deployment details, personal machine paths, server addresses, credentials, downloaded broker statements, `.env` files, or generated `data/config/*.json` files.

## Roadmap

- Richer demo portfolio data and scenario coverage.
- More complete multi-user and permission model.
- More evaluation coverage for agent correctness, replay, and regression gates.
- Better operational dashboards for long-running agent tasks.
- More market-event providers and event impact analytics.
- Broader deployment templates and release workflow hardening.

## License

[MIT](LICENSE)
