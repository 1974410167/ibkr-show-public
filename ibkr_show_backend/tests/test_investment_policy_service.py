from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.clients.es_client import ESIndexNotFoundError
from app.schemas.investment_policy import GlobalInvestmentPolicyUpsert, SymbolInvestmentPolicyUpsert
from app.services.investment_policy_repository import InvestmentPolicyRepository
from app.services.investment_policy_service import InvestmentPolicyService


@dataclass
class DummySettings:
    es_investment_policy_index: str = "ibkr_investment_policy_test"


class StubESClient:
    def __init__(self) -> None:
        self.index_bodies: dict[str, dict] = {}
        self.documents: dict[str, dict[str, dict]] = {}
        self.missing_get_indexes: set[str] = set()
        self.missing_search_indexes: set[str] = set()

    def create_index_if_missing(self, index: str, body: dict) -> None:
        self.index_bodies[index] = body
        self.documents.setdefault(index, {})

    def index_document(self, index: str, id: str, document: dict) -> dict:
        self.documents.setdefault(index, {})[id] = document
        return {"result": "created"}

    def get(self, index: str, id: str) -> dict | None:
        if index in self.missing_get_indexes:
            raise ESIndexNotFoundError(index)
        document = self.documents.get(index, {}).get(id)
        return {"_source": document} if document else None

    def search(self, index: str, body: dict) -> dict:
        if index in self.missing_search_indexes:
            raise ESIndexNotFoundError(index)
        documents = list(self.documents.get(index, {}).values())
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        for item in filters:
            term = item.get("term")
            if not term:
                continue
            field, expected = next(iter(term.items()))
            documents = [doc for doc in documents if doc.get(field) == expected]
        documents.sort(key=lambda doc: doc.get("symbol") or "")
        return {"hits": {"hits": [{"_id": doc.get("id"), "_source": doc} for doc in documents]}}


def make_service() -> tuple[InvestmentPolicyService, StubESClient]:
    es = StubESClient()
    repository = InvestmentPolicyRepository(es, DummySettings())
    return InvestmentPolicyService(repository), es


def test_global_policy_save_and_read() -> None:
    service, _es = make_service()

    saved = service.upsert_global_policy(
        GlobalInvestmentPolicyUpsert(
            risk_profile="aggressive_growth",
            target_annual_return_pct=0.35,
            max_drawdown_tolerance_pct=0.30,
            allow_concentrated_position=True,
            allow_single_position_over_20_pct=True,
            allow_leverage=False,
            cash_reserve_pct=0.08,
            preferred_add_styles=["pullback_add", "batch_add"],
            preferred_sell_style="sell_when_thesis_breaks",
            holding_period="long",
            notes="test",
            enabled=True,
        )
    )

    loaded = service.get_global_policy()

    assert saved.id == "global"
    assert loaded.risk_profile == "aggressive_growth"
    assert loaded.cash_reserve_pct == 0.08


def test_symbol_policy_save_read_and_symbol_normalization() -> None:
    service, _es = make_service()

    saved = service.upsert_symbol_policy(
        "amd.us",
        SymbolInvestmentPolicyUpsert(
            symbol="ignored.us",
            asset_role="core_growth",
            conviction="high",
            user_preferred_min_position_pct=0.05,
            user_preferred_target_position_pct=0.20,
            user_preferred_max_position_pct=0.28,
            add_rules=["pullback"],
            no_add_triggers=["broken trend"],
            sell_triggers=["thesis broken"],
            hard_constraints=["do not exceed max"],
            soft_preferences=["hold while thesis intact"],
            notes="AI GPU",
        ),
    )

    loaded = service.get_symbol_policy("AMD.US")

    assert saved.symbol == "AMD"
    assert loaded is not None
    assert loaded.symbol == "AMD"
    assert loaded.user_preferred_target_position_pct == 0.20
    assert loaded.user_preferred_max_position_pct == 0.28
    assert loaded.target_position_pct == 0.20
    assert loaded.max_position_pct == 0.28


def test_symbol_policy_reads_legacy_position_fields_as_user_preferences() -> None:
    service, es = make_service()
    es.documents.setdefault("ibkr_investment_policy_test", {})["symbol:AMD"] = {
        "id": "symbol:AMD",
        "policy_type": "symbol",
        "symbol": "AMD",
        "asset_role": "core_growth",
        "conviction": "high",
        "min_position_pct": 0.04,
        "target_position_pct": 0.18,
        "max_position_pct": 0.25,
        "add_rules": [],
        "no_add_triggers": [],
        "sell_triggers": [],
        "hard_constraints": [],
        "soft_preferences": [],
        "notes": "",
        "enabled": True,
        "ai_review_status": "unknown",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }

    loaded = service.get_symbol_policy("AMD.US")

    assert loaded is not None
    assert loaded.user_preferred_min_position_pct == 0.04
    assert loaded.user_preferred_target_position_pct == 0.18
    assert loaded.user_preferred_max_position_pct == 0.25


def test_position_pct_boundary_validation() -> None:
    with pytest.raises(ValidationError):
        SymbolInvestmentPolicyUpsert(
            symbol="AMD",
            user_preferred_min_position_pct=0.30,
            user_preferred_target_position_pct=0.20,
            user_preferred_max_position_pct=0.28,
        )

    with pytest.raises(ValidationError):
        SymbolInvestmentPolicyUpsert(
            symbol="AMD",
            user_preferred_min_position_pct=0.0,
            user_preferred_target_position_pct=0.20,
            user_preferred_max_position_pct=1.2,
        )


def test_get_policy_for_symbol_falls_back_to_investment_thesis_template() -> None:
    service, _es = make_service()

    policy = service.get_policy_for_symbol("MSTR.US")

    assert policy["source"] == "default_template"
    assert policy["symbol"] == "MSTR"
    assert policy["asset_role"] == "btc_proxy"
    assert policy["max_position_pct"] == 0.10
    assert policy["user_investment_preference"]["user_preferred_max_position_pct"] == 0.10
    assert policy["user_investment_preference"]["disclaimer"] == "这是用户主观偏好，不是 AI 最终仓位建议"
    assert policy["sell_triggers"]


def test_seed_defaults_does_not_overwrite_existing_policy() -> None:
    service, _es = make_service()
    service.upsert_symbol_policy(
        "AMD",
        SymbolInvestmentPolicyUpsert(
            symbol="AMD",
            asset_role="watchlist",
            conviction="low",
            user_preferred_min_position_pct=0.0,
            user_preferred_target_position_pct=0.01,
            user_preferred_max_position_pct=0.02,
            notes="user override",
        ),
    )

    created, skipped = service.seed_defaults(force=False)
    loaded = service.get_symbol_policy("AMD")

    assert created
    assert any(item.symbol == "AMD" for item in skipped)
    assert loaded is not None
    assert loaded.asset_role == "watchlist"
    assert loaded.user_preferred_max_position_pct == 0.02


def test_seed_defaults_initializes_user_preferred_fields() -> None:
    service, _es = make_service()

    created, _skipped = service.seed_defaults(force=False)
    amd = next(item for item in created if item.symbol == "AMD")

    assert amd.user_preferred_target_position_pct == 0.20
    assert amd.user_preferred_max_position_pct == 0.28
