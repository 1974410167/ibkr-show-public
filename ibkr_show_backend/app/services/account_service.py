from app.clients.cache_client import RedisCacheClient
from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.account import AccountDeltaMetric, AccountOverviewResponse, LatestReportDateResponse


class AccountService:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        cache_client: RedisCacheClient | None = None,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.cache_client = cache_client

    def get_latest_report_date(self) -> LatestReportDateResponse | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "size": 1,
                "sort": [{"report_date": {"order": "desc"}}],
                "_source": ["report_date"],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        source = hits[0]["_source"]
        return LatestReportDateResponse(report_date=source["report_date"])

    def get_overview(self) -> AccountOverviewResponse | None:
        cache_key = self.cache_client.build_key("account-overview") if self.cache_client else None
        if cache_key and self.cache_client:
            cached = self.cache_client.get_json(cache_key)
            if cached is not None:
                return AccountOverviewResponse(**cached)

        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "size": 2,
                "sort": [{"report_date": {"order": "desc"}}],
                "_source": [
                    "account_id",
                    "report_date",
                    "currency",
                    "total_equity",
                    "cash",
                    "stock_value",
                    "options_value",
                    "funds_value",
                    "crypto_value",
                    "interest_accruals",
                    "dividend_accruals",
                    "margin_financing_charge_accruals",
                    "fifo_total_realized_pnl",
                    "fifo_total_unrealized_pnl",
                    "fifo_total_pnl",
                    "cnav_twr",
                    "crtt_dividends_ytd",
                    "crtt_broker_interest_ytd",
                    "crtt_commissions_ytd",
                ],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        overview_source = dict(hits[0]["_source"])
        account_id = overview_source["account_id"]
        report_date = overview_source["report_date"]

        previous_source = dict(hits[1]["_source"]) if len(hits) > 1 else None
        overview_metrics = self._get_overview_metrics(
            account_id=account_id,
            report_date=report_date,
            previous_report_date=previous_source["report_date"] if previous_source is not None else None,
        )

        total_realized_pnl = overview_metrics["current_realized_pnl"]
        total_unrealized_pnl = overview_metrics["current_unrealized_pnl"]
        overview_source["fifo_total_realized_pnl"] = total_realized_pnl
        overview_source["fifo_total_unrealized_pnl"] = total_unrealized_pnl
        overview_source["fifo_total_pnl"] = total_realized_pnl + total_unrealized_pnl
        overview_source["ytd_twr"] = overview_metrics["ytd_twr"]

        if previous_source is not None:
            previous_total_realized_pnl = overview_metrics["previous_realized_pnl"]
            previous_total_unrealized_pnl = overview_metrics["previous_unrealized_pnl"]
            previous_total_pnl = previous_total_realized_pnl + previous_total_unrealized_pnl

            overview_source["total_equity_delta"] = self._build_delta_metric(
                overview_source.get("total_equity"),
                previous_source.get("total_equity"),
            )
            overview_source["fifo_total_realized_pnl_delta"] = self._build_delta_metric(
                total_realized_pnl,
                previous_total_realized_pnl,
            )
            overview_source["fifo_total_unrealized_pnl_delta"] = self._build_delta_metric(
                total_unrealized_pnl,
                previous_total_unrealized_pnl,
            )
            overview_source["fifo_total_pnl_delta"] = self._build_delta_metric(
                overview_source["fifo_total_pnl"],
                previous_total_pnl,
            )

        overview = AccountOverviewResponse(**overview_source)
        if cache_key and self.cache_client:
            self.cache_client.set_json(cache_key, overview.model_dump())
        return overview

    def _get_overview_metrics(
        self,
        *,
        account_id: str,
        report_date: str,
        previous_report_date: str | None,
    ) -> dict[str, float | None]:
        report_year = report_date[:4]
        searches: list[tuple[str, dict]] = [
            (
                self.settings.es_trade_index,
                {
                    "size": 0,
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"account_id": account_id}},
                                {"range": {"trade_date": {"lte": report_date}}},
                            ]
                        }
                    },
                    "aggs": {"total_realized_pnl": {"sum": {"field": "fifo_pnl_realized"}}},
                },
            ),
            (
                self.settings.es_position_index,
                {
                    "size": 0,
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"account_id": account_id}},
                                {"term": {"report_date": report_date}},
                            ]
                        }
                    },
                    "aggs": {"total_unrealized_pnl": {"sum": {"field": "total_unrealized_pnl"}}},
                },
            ),
            (
                self.settings.es_account_index,
                {
                    "size": 2000,
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"account_id": account_id}},
                                {"range": {"report_date": {"gte": f"{report_year}-01-01", "lte": report_date}}},
                            ]
                        }
                    },
                    "sort": [{"report_date": {"order": "asc"}}],
                    "_source": ["report_date", "cnav_twr"],
                },
            ),
        ]

        if previous_report_date is not None:
            searches.extend(
                [
                    (
                        self.settings.es_trade_index,
                        {
                            "size": 0,
                            "query": {
                                "bool": {
                                    "filter": [
                                        {"term": {"account_id": account_id}},
                                        {"range": {"trade_date": {"lte": previous_report_date}}},
                                    ]
                                }
                            },
                            "aggs": {"total_realized_pnl": {"sum": {"field": "fifo_pnl_realized"}}},
                        },
                    ),
                    (
                        self.settings.es_position_index,
                        {
                            "size": 0,
                            "query": {
                                "bool": {
                                    "filter": [
                                        {"term": {"account_id": account_id}},
                                        {"term": {"report_date": previous_report_date}},
                                    ]
                                }
                            },
                            "aggs": {"total_unrealized_pnl": {"sum": {"field": "total_unrealized_pnl"}}},
                        },
                    ),
                ]
            )

        responses = self.es_client.multi_search(searches)
        current_realized_response = responses[0]
        current_unrealized_response = responses[1]
        ytd_twr_response = responses[2]
        previous_realized_response = responses[3] if previous_report_date is not None else None
        previous_unrealized_response = responses[4] if previous_report_date is not None else None

        return {
            "current_realized_pnl": self._extract_sum_aggregation(current_realized_response, "total_realized_pnl"),
            "current_unrealized_pnl": self._extract_sum_aggregation(current_unrealized_response, "total_unrealized_pnl"),
            "ytd_twr": self._extract_ytd_twr(ytd_twr_response),
            "previous_realized_pnl": self._extract_sum_aggregation(previous_realized_response, "total_realized_pnl"),
            "previous_unrealized_pnl": self._extract_sum_aggregation(
                previous_unrealized_response,
                "total_unrealized_pnl",
            ),
        }

    @staticmethod
    def _extract_sum_aggregation(response: dict | None, aggregation_name: str) -> float:
        if response is None:
            return 0.0
        return float(response.get("aggregations", {}).get(aggregation_name, {}).get("value") or 0.0)

    @staticmethod
    def _extract_ytd_twr(response: dict) -> float | None:
        twr_values = [
            float(hit["_source"]["cnav_twr"])
            for hit in response.get("hits", {}).get("hits", [])
            if hit.get("_source", {}).get("cnav_twr") is not None
        ]
        if not twr_values:
            return None

        cumulative_return = 1.0
        for daily_twr in twr_values:
            cumulative_return *= 1.0 + daily_twr / 100.0

        return (cumulative_return - 1.0) * 100.0

    def _build_delta_metric(
        self,
        current_value: float | None,
        previous_value: float | None,
    ) -> AccountDeltaMetric | None:
        if current_value is None or previous_value is None:
            return None

        amount_change = float(current_value) - float(previous_value)
        percent_change = None
        if float(previous_value) != 0.0:
            percent_change = amount_change / abs(float(previous_value)) * 100.0

        return AccountDeltaMetric(
            amount_change=amount_change,
            percent_change=percent_change,
        )
