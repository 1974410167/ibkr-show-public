# 市场事件中台 - 开发者文档

## 数据模型关系

```
market_event_sources (数据源配置)
    ├── market_event_definitions (事件定义/模板)
    ├── market_event_occurrences (事件实例)
    │       ├── market_event_values (数值: 前值/预期/实际)
    │       ├── market_event_impacts (影响映射)
    │       ├── market_event_news_links (关联新闻)
    │       └── market_event_analysis (LLM 分析, 预留)
    └── market_event_sync_runs (同步日志)
```

Key 加密保存在后端配置存储中（不在 ES 中），前端只展示脱敏值。

## ES 索引命名

所有索引使用 `_v1` 后缀，通过 Settings 配置：

| 索引 | 默认名 |
|---|---|
| sources | `market_event_sources_v1` |
| definitions | `market_event_definitions_v1` |
| occurrences | `market_event_occurrences_v1` |
| values | `market_event_values_v1` |
| impacts | `market_event_impacts_v1` |
| news_links | `market_event_news_links_v1` |
| analysis | `market_event_analysis_v1` |
| sync_runs | `market_event_sync_runs_v1` |

## Provider 架构

```
MarketEventProvider (ABC)
├── BlsProvider      -- CALENDAR_EVENTS, EVENT_VALUES, HEALTH_CHECK
├── BeaProvider      -- CALENDAR_EVENTS, EVENT_VALUES, HEALTH_CHECK
├── FredProvider     -- EVENT_VALUES, HEALTH_CHECK
├── FedProvider      -- CALENDAR_EVENTS, HEALTH_CHECK
├── IsmProvider      -- CALENDAR_EVENTS, EVENT_VALUES, HEALTH_CHECK
├── LongbridgeProvider -- CALENDAR_EVENTS, NEWS_EVENTS, CORPORATE_EVENTS, MARKET_HOLIDAYS, ...
└── ManualProvider   -- CALENDAR_EVENTS
```

每个 Provider 声明 `capabilities`，Registry 按 capability 分发。

Longbridge Provider uses Longbridge OpenAPI / SDK only. MCP is not used by backend market event synchronization. Longbridge credentials are reused from the existing Longbridge OpenAPI OAuth configuration and are not duplicated into market event credentials. Longbridge news is limited to `news(symbol)`; topic or keyword news should be implemented by a GenericNewsProvider or another dedicated news source.

## Sync Service 流程

```
sync_all(request)
  └── for each provider:
        └── sync_provider(source_code, request)
              ├── sync_calendar_events(provider, request)
              ├── sync_event_values(provider, request)
              ├── sync_corporate_events(provider, request)
              └── sync_market_holidays(provider, request)
```

每次 sync 都会：
1. 创建 `market_event_sync_runs` 文档（status=RUNNING）
2. 调用 Provider 获取数据
3. 幂等 upsert 到 occurrences/values/impacts
4. 更新 sync_run 状态

## Upsert 幂等规则

- **occurrence**: 以 `dedupe_key` 为 ES 文档 ID
- **dedupe_key**: `sha256(source_code | event_type | scheduled_at | title | market | period | symbols)`
- **values**: 以 `occurrence_id_value_type_label` 为 ID
- **impacts**: 以 `occurrence_id_symbol_asset_class_market` 为 ID
- **news_links**: 以 `occurrence_id_source_code_news_id_or_url` 为 ID

## 风险等级规则

```
CRITICAL: 至少一个 CRITICAL 事件
HIGH: 至少两个 HIGH，或一个 HIGH + 三个 MEDIUM
MEDIUM: 至少三个 MEDIUM，或一个 HIGH
LOW: 其他
```

## 新增数据源 Provider 步骤

1. 在 `app/schemas/market_event.py` 中添加 `MarketEventSourceCode` literal
2. 在 `app/services/market_event_providers.py` 中创建 Provider 子类
3. 在 `MarketEventProviderRegistry.__init__` 中注册
4. 在 `app/services/market_event_seed.py` 中添加默认 seed
5. 在 Settings 中添加 ES 索引配置
6. 编写测试

## 新增事件类型步骤

1. 在 `MarketEventType` literal 中添加新类型
2. 在 Provider 中添加解析逻辑
3. 更新 `BLS_ICS_TITLE_MAP` 或对应映射

## API 列表

### 公开 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/market-events` | 事件列表（分页、筛选） |
| GET | `/api/market-events/today` | 今日事件 |
| GET | `/api/market-events/upcoming` | 未来事件 |
| GET | `/api/market-events/risk-summary` | 风险概览 |
| GET | `/api/market-events/calendar` | 日历视图 |
| GET | `/api/market-events/{id}` | 事件详情 |
| GET | `/api/market-events/symbol/{symbol}` | 标的相关事件 |
| GET | `/api/market-events/sources` | 数据源状态 |

### Admin API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/market-events/sources` | 数据源配置列表 |
| GET | `/api/admin/market-events/sources/{code}` | 单个数据源配置 |
| PUT | `/api/admin/market-events/sources/{code}` | 更新数据源配置 |
| PUT | `/api/admin/market-events/sources/{code}/credential` | 保存凭证 |
| DELETE | `/api/admin/market-events/sources/{code}/credential` | 删除凭证 |
| POST | `/api/admin/market-events/sources/{code}/test` | 测试连接 |
| POST | `/api/admin/market-events/sync` | 触发同步 |

## 前端页面结构

- `src/views/MarketEventsView.vue` -- 重点事件首页（风险总览 + 列表 + 详情抽屉）
- `src/views/AdminMarketEventsView.vue` -- 后台宏观数据源配置
- `src/api/marketEvents.ts` -- API client
- `src/types/marketEvent.ts` -- TypeScript 类型

## Agent 联动预留点

本次未实现 Agent 联动。未来可扩展：

```
交易决策 Agent 可调用:
  GET /api/market-events/upcoming?days=7&importance=HIGH,CRITICAL
  GET /api/market-events/symbol/{symbol}

每日复盘 Agent 可调用:
  GET /api/market-events?start_at=...&end_at=...
```
