# Eval P2: Regression Profile & Deployment Gate

## 概述

Eval P2 为 Agent Regression Eval 引入了以下能力：

1. **Regression Profile** — 每个 Agent 可保存默认回归策略
2. **Prompt 保存触发** — Prompt 保存后按 Profile 自动建议回归
3. **代码变更影响分析** — 根据 changed files 识别受影响 Agent
4. **部署前 Regression Gate** — 在部署前运行推荐回归，Gate 不通过则阻断
5. **Gate Report 沉淀** — Gate 运行报告持久化，支持历史查询

---

## Regression Profile

每个 Agent 可以保存一份默认回归配置，包含：

- `agent_name` — 唯一标识
- `enabled` — 是否启用
- `mode` — `static` 或 `live_mock`
- `case_tag` — 用例标签过滤
- `severity` / `category` — 用例过滤
- `include_disabled` / `include_judge` / `include_node_eval` — 选项
- `gate` — 门禁阈值（`fail_on_critical`, `fail_on_high`, `min_pass_rate`, `max_failed`）
- `trigger_policy` — 触发策略（`on_prompt_save`, `on_code_change`, `on_deploy`）

管理入口：Harness 控制台 → 回归配置 tab。

---

## 本地使用

### 1. 影响分析（dry-run）

分析哪些 Agent 受代码变更影响：

```bash
# 分析指定文件
python -m app.cli.eval_harness impact-analysis \
  --changed-file ibkr_show_backend/app/agents/trade_decision_graph/nodes.py \
  --output-file impact.json

# 分析 git diff
python -m app.cli.eval_harness impact-analysis \
  --base-ref origin/main \
  --head-ref HEAD
```

### 2. 部署前 Gate（dry-run）

预览哪些 Agent 会运行回归，不实际执行：

```bash
python -m app.cli.eval_harness regression-gate \
  --base-ref origin/main \
  --head-ref HEAD \
  --dry-run \
  --output json
```

### 3. 部署前 Gate（真实执行）

运行推荐的回归评测，Gate 不通过则返回非 0 退出码：

```bash
python -m app.cli.eval_harness regression-gate \
  --base-ref origin/main \
  --head-ref HEAD \
  --output json \
  --save-report
```

---

## CLI 参数说明

### regression-gate

| 参数 | 说明 |
|---|---|
| `--changed-file FILE` | 指定变更文件（可重复） |
| `--base-ref REF` | Git base ref |
| `--head-ref REF` | Git head ref |
| `--dry-run` | 只分析，不运行 eval |
| `--output text\|json` | 输出格式 |
| `--output-file PATH` | 输出到文件 |
| `--max-agents N` | 最多运行 N 个 Agent（默认 10） |
| `--save-report` | 保存 Gate Report 到 Elasticsearch |
| `--trigger LABEL` | 报告触发源标签（默认 `cli`） |
| `--created-by LABEL` | 报告创建者 |
| `--metadata-json JSON` | 附加元数据 |
| `--run-not-recommended` | 也运行非推荐 Agent |

### 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 通过，或无 recommended runs |
| 1 | Gate 失败，或内部错误 |
| 2 | 参数错误 |

---

## 接入 CI/CD

### 示例：GitHub Actions

```yaml
name: Deploy Gate

on:
  push:
    branches: [main]

jobs:
  regression-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          cd ibkr_show_backend
          pip install -r requirements.txt

      - name: Run Regression Gate
        env:
          ES_HOST: ${{ secrets.ES_HOST }}
          ES_USERNAME: ${{ secrets.ES_USERNAME }}
          ES_PASSWORD: ${{ secrets.ES_PASSWORD }}
        run: |
          cd ibkr_show_backend
          python -m app.cli.eval_harness regression-gate \
            --base-ref origin/main~1 \
            --head-ref HEAD \
            --output json \
            --save-report \
            --trigger ci_deploy \
            --created-by github_actions

      - name: Deploy
        if: success()
        run: echo "Gate passed, proceed with deployment"
```

### 示例：Shell 脚本

```bash
#!/bin/bash
set -e

echo "Running regression gate..."
cd ibkr_show_backend

python -m app.cli.eval_harness regression-gate \
  --base-ref origin/main \
  --head-ref HEAD \
  --output json \
  --save-report \
  --trigger deploy_script

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "Gate passed, proceeding with deployment"
  # 在此执行实际部署
elif [ $EXIT_CODE -eq 1 ]; then
  echo "Gate FAILED, deployment blocked"
  exit 1
else
  echo "Gate error (exit code $EXIT_CODE)"
  exit $EXIT_CODE
fi
```

---

## 风险说明

1. **Profile 配置依赖**：只有 `profile.enabled=true` 且 `trigger_policy.on_code_change=true` 的 Agent 才会被推荐运行
2. **无推荐时默认通过**：如果没有 Agent 被推荐运行，Gate 默认返回 exit code 0
3. **max_agents 保护**：默认最多运行 10 个 Agent，防止误配置导致大量回归
4. **LLM 成本**：如果 Profile 启用了 `include_judge`，会产生额外 LLM token 成本
5. **超时**：git diff 命令有 30 秒超时限制

---

## API 端点

### 影响分析

- `POST /api/admin/agent-eval/impact-analysis/changed-files` — 分析文件列表
- `POST /api/admin/agent-eval/impact-analysis/git-diff` — 分析 git diff

### Regression Gate

- `POST /api/admin/agent-eval/regression-gate/dry-run` — Dry-run（默认保存 report）
- `GET /api/admin/agent-eval/regression-gate/reports` — 列出 Gate 报告
- `GET /api/admin/agent-eval/regression-gate/reports/{report_id}` — 获取报告详情

### Regression Profile

- `GET /api/admin/agent-eval/regression-profiles` — 列出 Profiles
- `GET /api/admin/agent-eval/regression-profiles/{agent_name}` — 获取 Profile
- `PUT /api/admin/agent-eval/regression-profiles/{agent_name}` — 创建/更新 Profile
- `POST /api/admin/agent-eval/regression-profiles/{agent_name}/disable` — 禁用 Profile
- `POST /api/admin/agent-eval/regression-profiles/{agent_name}/build-payload` — 生成回归参数

---

## Harness 控制台

回归相关功能统一在「回归配置」tab 中：

1. **回归配置** — 管理每个 Agent 的 Regression Profile
2. **代码变更影响分析** — 输入 changed files 或 git diff，分析受影响 Agent
3. **部署 Gate 报告** — 查看历史 Gate 运行报告
