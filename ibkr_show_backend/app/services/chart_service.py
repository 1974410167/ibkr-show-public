from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from app.clients.cache_client import RedisCacheClient
from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.schemas.charts import (
    EquityCurvePoint,
    EquityCurveResponse,
    PerformanceCalendarItem,
    PerformanceCalendarResponse,
    PerformanceCalendarSummary,
)
from app.utils.dates import parse_date
from app.utils.es_query_builder import build_date_range_filter

INFERRED_DAILY_PNL_EPSILON = 0.01
DEPOSIT_WITHDRAWAL_FLOW_TYPE = "Deposits/Withdrawals"
CURVE_AMOUNT_PRECISION = 2
CURVE_PERCENT_PRECISION = 2
PERFORMANCE_CALENDAR_VIEWS = {"month", "year", "all-years"}


@dataclass
class DailyPerformanceEntry:
    report_date: date
    daily_mtm: float | None
    daily_twr: float | None


class ChartService:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        cache_client: RedisCacheClient | None = None,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.cache_client = cache_client

    def get_equity_curve(self, start_date: str | None, end_date: str | None) -> EquityCurveResponse:
        cache_key = None
        if self.cache_client:
            cache_key = self.cache_client.build_key(
                "equity-curve",
                f"start={start_date or ''}",
                f"end={end_date or ''}",
            )
            cached = self.cache_client.get_json(cache_key)
            if cached is not None:
                return EquityCurveResponse(**cached)

        latest_report_date = self._get_latest_report_date()
        if latest_report_date is None:
            return EquityCurveResponse(items=[])

        effective_end = parse_date(end_date) or latest_report_date
        effective_start = parse_date(start_date)

        filters = [
            build_date_range_filter(
                "report_date",
                effective_start.isoformat() if effective_start else None,
                effective_end.isoformat(),
            )
        ]
        snapshots_response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "query": {"bool": {"filter": [item for item in filters if item]}},
                "sort": [{"report_date": {"order": "asc"}}],
                "size": 2000,
                "_source": ["account_id", "report_date", "total_equity", "cnav_mtm", "cnav_twr"],
            },
        )
        snapshot_sources = [hit["_source"] for hit in snapshots_response.get("hits", {}).get("hits", [])]
        if not snapshot_sources:
            return EquityCurveResponse(items=[])

        account_id = snapshot_sources[-1].get("account_id")
        cash_flow_response = self._get_cash_flow_response(account_id, effective_end) if account_id else None
        cash_flow_curve = self._build_net_cost_curve(cash_flow_response)
        daily_net_flows = self._build_daily_net_flows(cash_flow_response)
        realized_pnl_curve = self._build_realized_pnl_curve(account_id, effective_end)
        latest_calendar_month = effective_end.strftime("%Y-%m")

        items = []
        current_net_cost = 0.0
        current_realized_pnl = 0.0
        cash_flow_index = 0
        realized_pnl_index = 0
        previous_total_equity: float | None = None
        for source in snapshot_sources:
            report_date = source["report_date"]
            total_equity = source.get("total_equity")

            while cash_flow_index < len(cash_flow_curve) and cash_flow_curve[cash_flow_index][0] <= report_date:
                current_net_cost = cash_flow_curve[cash_flow_index][1]
                cash_flow_index += 1
            while realized_pnl_index < len(realized_pnl_curve) and realized_pnl_curve[realized_pnl_index][0] <= report_date:
                current_realized_pnl = realized_pnl_curve[realized_pnl_index][1]
                realized_pnl_index += 1

            net_cost = current_net_cost
            total_pnl = None
            if total_equity is not None and net_cost is not None:
                total_pnl = float(total_equity) - float(net_cost)

            daily_mtm = source.get("cnav_mtm")
            daily_mtm_inferred = False
            if daily_mtm is None and total_equity is not None and previous_total_equity is not None:
                daily_mtm = float(total_equity) - float(previous_total_equity) - daily_net_flows.get(report_date, 0.0)
                daily_mtm_inferred = True
                if abs(float(daily_mtm)) < INFERRED_DAILY_PNL_EPSILON:
                    daily_mtm = 0.0

            daily_twr = source.get("cnav_twr")
            if daily_twr is None and daily_mtm is not None and previous_total_equity not in (None, 0, 0.0):
                daily_twr = float(daily_mtm) / abs(float(previous_total_equity)) * 100.0
            if daily_mtm_inferred and daily_mtm == 0.0:
                daily_twr = 0.0
            if not report_date.startswith(latest_calendar_month):
                daily_mtm = None
                daily_twr = None

            items.append(
                EquityCurvePoint(
                    report_date=report_date,
                    total_equity=self._round_amount(total_equity),
                    total_pnl=self._round_amount(total_pnl),
                    net_cost=self._round_amount(net_cost),
                    realized_pnl=self._round_amount(current_realized_pnl),
                    daily_mtm=self._round_amount(daily_mtm),
                    daily_twr=self._round_percent(daily_twr),
                )
            )
            previous_total_equity = float(total_equity) if total_equity is not None else previous_total_equity
        response = EquityCurveResponse(items=items)
        if cache_key and self.cache_client:
            self.cache_client.set_json(cache_key, response.model_dump(exclude_none=True))
        return response

    def get_performance_calendar(self, view: str, anchor: str | None) -> PerformanceCalendarResponse:
        if view not in PERFORMANCE_CALENDAR_VIEWS:
            raise ValueError("view must be one of: month, year, all-years")

        latest_report_date = self._get_latest_report_date()
        if latest_report_date is None:
            return PerformanceCalendarResponse(
                view=view,
                anchor=anchor or "",
                latest_anchor="",
                earliest_anchor=None,
                items=[],
                summary=PerformanceCalendarSummary(),
            )

        latest_month_anchor = latest_report_date.strftime("%Y-%m")
        latest_year_anchor = latest_report_date.strftime("%Y")

        cache_key = None
        effective_anchor = anchor or (latest_month_anchor if view == "month" else latest_year_anchor if view == "year" else "all")
        if self.cache_client:
            cache_key = self.cache_client.build_key(
                "performance-calendar",
                f"view={view}",
                f"anchor={effective_anchor}",
            )
            cached = self.cache_client.get_json(cache_key)
            if cached is not None and self._is_compatible_performance_calendar_cache(cached, view):
                return PerformanceCalendarResponse(**cached)

        earliest_report_date = self._get_earliest_report_date() or latest_report_date
        if view == "month":
            response = self._build_month_calendar_response(
                latest_report_date=latest_report_date,
                latest_anchor=latest_month_anchor,
                earliest_report_date=earliest_report_date,
                anchor=effective_anchor,
            )
        elif view == "year":
            response = self._build_year_calendar_response(
                latest_report_date=latest_report_date,
                latest_anchor=latest_year_anchor,
                earliest_report_date=earliest_report_date,
                anchor=effective_anchor,
            )
        else:
            response = self._build_all_years_calendar_response(
                latest_report_date=latest_report_date,
                earliest_report_date=earliest_report_date,
            )

        if cache_key and self.cache_client:
            self.cache_client.set_json(cache_key, response.model_dump(exclude_none=True))
        return response

    def _is_compatible_performance_calendar_cache(self, cached: dict, view: str) -> bool:
        if view == "all-years":
            return True
        earliest_anchor = cached.get("earliest_anchor")
        return isinstance(earliest_anchor, str) and bool(earliest_anchor.strip())

    def _round_amount(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), CURVE_AMOUNT_PRECISION)

    def _round_percent(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), CURVE_PERCENT_PRECISION)

    def _get_latest_report_date(self) -> date | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={"size": 1, "sort": [{"report_date": {"order": "desc"}}], "_source": ["report_date"]},
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return parse_date(hits[0]["_source"]["report_date"])

    def _get_earliest_report_date(self) -> date | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={"size": 1, "sort": [{"report_date": {"order": "asc"}}], "_source": ["report_date"]},
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return parse_date(hits[0]["_source"]["report_date"])

    def _get_previous_snapshot_before(self, report_date: date) -> dict | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "size": 1,
                "query": {"bool": {"filter": [{"range": {"report_date": {"lt": report_date.isoformat()}}}]}},
                "sort": [{"report_date": {"order": "desc"}}],
                "_source": ["account_id", "report_date", "total_equity"],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return hits[0]["_source"]

    def _fetch_snapshot_sources(self, start: date | None, end: date) -> list[dict]:
        filters = [build_date_range_filter("report_date", start.isoformat() if start else None, end.isoformat())]
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "query": {"bool": {"filter": [item for item in filters if item]}},
                "sort": [{"report_date": {"order": "asc"}}],
                "size": 4000,
                "_source": ["account_id", "report_date", "total_equity", "cnav_mtm", "cnav_twr"],
            },
        )
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    def _build_daily_performance_entries(self, start: date | None, end: date) -> list[DailyPerformanceEntry]:
        snapshot_sources = self._fetch_snapshot_sources(start, end)
        if not snapshot_sources:
            return []

        first_source = snapshot_sources[0]
        account_id = first_source.get("account_id") or snapshot_sources[-1].get("account_id")
        previous_snapshot = self._get_previous_snapshot_before(start) if start is not None else None
        previous_total_equity = (
            float(previous_snapshot.get("total_equity"))
            if previous_snapshot and previous_snapshot.get("total_equity") is not None
            else None
        )
        cash_flow_response = self._get_cash_flow_response(account_id, end, start) if account_id else None
        daily_net_flows = self._build_daily_net_flows(cash_flow_response)

        entries: list[DailyPerformanceEntry] = []
        for source in snapshot_sources:
            report_date = parse_date(source["report_date"])
            total_equity = source.get("total_equity")

            daily_mtm = source.get("cnav_mtm")
            daily_mtm_inferred = False
            if daily_mtm is None and total_equity is not None and previous_total_equity is not None:
                daily_mtm = float(total_equity) - float(previous_total_equity) - daily_net_flows.get(
                    report_date.isoformat(),
                    0.0,
                )
                daily_mtm_inferred = True
                if abs(float(daily_mtm)) < INFERRED_DAILY_PNL_EPSILON:
                    daily_mtm = 0.0

            daily_twr = source.get("cnav_twr")
            if daily_twr is None and daily_mtm is not None and previous_total_equity not in (None, 0, 0.0):
                daily_twr = float(daily_mtm) / abs(float(previous_total_equity)) * 100.0
            if daily_mtm_inferred and daily_mtm == 0.0:
                daily_twr = 0.0

            entries.append(
                DailyPerformanceEntry(
                    report_date=report_date,
                    daily_mtm=self._round_amount(daily_mtm),
                    daily_twr=self._round_percent(daily_twr),
                )
            )
            if total_equity is not None:
                previous_total_equity = float(total_equity)

        return entries

    def _build_month_calendar_response(
        self,
        *,
        latest_report_date: date,
        latest_anchor: str,
        earliest_report_date: date,
        anchor: str,
    ) -> PerformanceCalendarResponse:
        effective_month = self._parse_month_anchor(anchor)
        latest_month = date(latest_report_date.year, latest_report_date.month, 1)
        earliest_month = date(earliest_report_date.year, earliest_report_date.month, 1)
        if effective_month > latest_month:
            effective_month = latest_month
        if effective_month < earliest_month:
            effective_month = earliest_month

        start = effective_month
        end = min(self._month_end(effective_month), latest_report_date)
        entries = self._build_daily_performance_entries(start, end)
        entries_by_date = {entry.report_date.isoformat(): entry for entry in entries}
        days_in_month = monthrange(effective_month.year, effective_month.month)[1]
        items: list[PerformanceCalendarItem] = []
        for day in range(1, days_in_month + 1):
            period_date = date(effective_month.year, effective_month.month, day)
            entry = entries_by_date.get(period_date.isoformat())
            items.append(
                PerformanceCalendarItem(
                    period_key=period_date.isoformat(),
                    label=str(day),
                    period_start=period_date.isoformat(),
                    pnl=entry.daily_mtm if entry else None,
                    twr=entry.daily_twr if entry else None,
                    has_data=entry is not None,
                )
            )

        return PerformanceCalendarResponse(
            view="month",
            anchor=effective_month.strftime("%Y-%m"),
            latest_anchor=latest_anchor,
            earliest_anchor=earliest_month.strftime("%Y-%m"),
            previous_anchor=(effective_month - timedelta(days=1)).strftime("%Y-%m")
            if effective_month > earliest_month
            else None,
            next_anchor=(self._month_end(effective_month) + timedelta(days=1)).strftime("%Y-%m")
            if effective_month < latest_month
            else None,
            items=items,
            summary=self._build_calendar_summary(items),
        )

    def _build_year_calendar_response(
        self,
        *,
        latest_report_date: date,
        latest_anchor: str,
        earliest_report_date: date,
        anchor: str,
    ) -> PerformanceCalendarResponse:
        effective_year = self._parse_year_anchor(anchor)
        latest_year = latest_report_date.year
        earliest_year = earliest_report_date.year
        effective_year = min(max(effective_year, earliest_year), latest_year)

        start = date(effective_year, 1, 1)
        end = min(date(effective_year, 12, 31), latest_report_date)
        entries = self._build_daily_performance_entries(start, end)
        items: list[PerformanceCalendarItem] = []
        for month in range(1, 13):
            month_start = date(effective_year, month, 1)
            month_end = self._month_end(month_start)
            month_entries = [entry for entry in entries if month_start <= entry.report_date <= month_end]
            items.append(
                self._build_grouped_calendar_item(
                    period_key=f"{effective_year}-{month:02d}",
                    label=f"{month}月",
                    period_start=month_start.isoformat(),
                    period_end=month_end.isoformat(),
                    entries=month_entries,
                )
            )

        return PerformanceCalendarResponse(
            view="year",
            anchor=str(effective_year),
            latest_anchor=latest_anchor,
            earliest_anchor=str(earliest_year),
            previous_anchor=str(effective_year - 1) if effective_year > earliest_year else None,
            next_anchor=str(effective_year + 1) if effective_year < latest_year else None,
            items=items,
            summary=self._build_calendar_summary(items),
        )

    def _build_all_years_calendar_response(
        self,
        *,
        latest_report_date: date,
        earliest_report_date: date,
    ) -> PerformanceCalendarResponse:
        entries = self._build_daily_performance_entries(None, latest_report_date)
        items: list[PerformanceCalendarItem] = []
        for year in range(earliest_report_date.year, latest_report_date.year + 1):
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            year_entries = [entry for entry in entries if year_start <= entry.report_date <= year_end]
            items.append(
                self._build_grouped_calendar_item(
                    period_key=str(year),
                    label=f"{year}年",
                    period_start=year_start.isoformat(),
                    period_end=year_end.isoformat(),
                    entries=year_entries,
                )
            )

        return PerformanceCalendarResponse(
            view="all-years",
            anchor="all",
            latest_anchor=str(latest_report_date.year),
            earliest_anchor=str(earliest_report_date.year),
            items=items,
            summary=self._build_calendar_summary(items),
        )

    def _build_grouped_calendar_item(
        self,
        *,
        period_key: str,
        label: str,
        period_start: str,
        period_end: str,
        entries: list[DailyPerformanceEntry],
    ) -> PerformanceCalendarItem:
        if not entries:
            return PerformanceCalendarItem(
                period_key=period_key,
                label=label,
                period_start=period_start,
                period_end=period_end,
                has_data=False,
            )

        total_pnl = sum(entry.daily_mtm or 0.0 for entry in entries if entry.daily_mtm is not None)
        twr = self._compound_twr([entry.daily_twr for entry in entries if entry.daily_twr is not None])
        return PerformanceCalendarItem(
            period_key=period_key,
            label=label,
            period_start=period_start,
            period_end=period_end,
            pnl=self._round_amount(total_pnl),
            twr=self._round_percent(twr),
            has_data=True,
        )

    def _build_calendar_summary(self, items: list[PerformanceCalendarItem]) -> PerformanceCalendarSummary:
        positive_periods = 0
        negative_periods = 0
        total_pnl = 0.0
        periods_with_data = 0

        for item in items:
            if item.pnl is None:
                continue
            periods_with_data += 1
            total_pnl += item.pnl
            if item.pnl > 0:
                positive_periods += 1
            elif item.pnl < 0:
                negative_periods += 1

        return PerformanceCalendarSummary(
            positive_periods=positive_periods,
            negative_periods=negative_periods,
            total_pnl=self._round_amount(total_pnl) if periods_with_data else None,
            periods_with_data=periods_with_data,
        )

    def _compound_twr(self, values: list[float]) -> float | None:
        if not values:
            return None

        cumulative_return = 1.0
        for value in values:
            cumulative_return *= 1.0 + float(value) / 100.0
        return (cumulative_return - 1.0) * 100.0

    def _month_end(self, value: date) -> date:
        return date(value.year, value.month, monthrange(value.year, value.month)[1])

    def _parse_month_anchor(self, value: str) -> date:
        try:
            year_text, month_text = value.split("-")
            return date(int(year_text), int(month_text), 1)
        except ValueError as exc:
            raise ValueError("month anchor must use YYYY-MM format") from exc

    def _parse_year_anchor(self, value: str) -> int:
        if len(value) != 4 or not value.isdigit():
            raise ValueError("year anchor must use YYYY format")
        return int(value)

    def _build_net_cost_curve(self, cash_flow_response: dict | None) -> list[tuple[str, float]]:
        if not cash_flow_response:
            return []

        cumulative = 0.0
        net_cost_points: list[tuple[str, float]] = []
        for hit in cash_flow_response.get("hits", {}).get("hits", []):
            source = hit["_source"]
            effective_date = source.get("settle_date") or source.get("report_date")
            if not effective_date:
                date_time = source.get("date_time")
                if date_time:
                    effective_date = str(date_time).split("T", 1)[0]
            if not effective_date:
                continue
            cumulative += float(source.get("amount_in_base") or 0.0)
            if net_cost_points and net_cost_points[-1][0] == effective_date:
                net_cost_points[-1] = (effective_date, cumulative)
            else:
                net_cost_points.append((effective_date, cumulative))

        return net_cost_points

    def _build_daily_net_flows(self, cash_flow_response: dict | None) -> dict[str, float]:
        if not cash_flow_response:
            return {}
        net_flows_by_date: dict[str, float] = {}
        for hit in cash_flow_response.get("hits", {}).get("hits", []):
            source = hit["_source"]
            effective_date = source.get("settle_date") or source.get("report_date")
            if not effective_date:
                date_time = source.get("date_time")
                if date_time:
                    effective_date = str(date_time).split("T", 1)[0]
            if not effective_date:
                continue
            net_flows_by_date[effective_date] = net_flows_by_date.get(effective_date, 0.0) + float(
                source.get("amount_in_base") or 0.0
            )

        return net_flows_by_date

    def _get_cash_flow_response(self, account_id: str, effective_end: date, effective_start: date | None = None) -> dict:
        date_range: dict[str, str] = {"lte": effective_end.isoformat()}
        if effective_start is not None:
            date_range["gte"] = effective_start.isoformat()
        return self.es_client.search(
            index=self.settings.es_cash_flow_index,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"account_id": account_id}},
                            {"term": {"flow_type": DEPOSIT_WITHDRAWAL_FLOW_TYPE}},
                            {"range": {"date_time": date_range}},
                        ]
                    }
                },
                "sort": [{"date_time": {"order": "asc"}}],
                "size": 10000,
                "_source": ["date_time", "settle_date", "report_date", "amount_in_base"],
            },
        )

    def _build_realized_pnl_curve(self, account_id: str | None, effective_end: date) -> list[tuple[str, float]]:
        if not account_id:
            return []

        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"account_id": account_id}},
                            {"range": {"trade_date": {"lte": effective_end.isoformat()}}},
                        ]
                    }
                },
                "sort": [
                    {"trade_date": {"order": "asc"}},
                    {"date_time": {"order": "asc", "missing": "_last"}},
                ],
                "size": 10000,
                "_source": ["trade_date", "fifo_pnl_realized"],
            },
        )

        cumulative = 0.0
        realized_points: list[tuple[str, float]] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit["_source"]
            trade_date = source.get("trade_date")
            if not trade_date:
                continue
            cumulative += float(source.get("fifo_pnl_realized") or 0.0)
            if realized_points and realized_points[-1][0] == trade_date:
                realized_points[-1] = (trade_date, cumulative)
            else:
                realized_points.append((trade_date, cumulative))

        return realized_points
