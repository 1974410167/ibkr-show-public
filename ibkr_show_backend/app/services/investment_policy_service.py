from __future__ import annotations

from app.schemas.investment_policy import (
    GlobalInvestmentPolicy,
    GlobalInvestmentPolicyUpsert,
    SymbolInvestmentPolicy,
    SymbolInvestmentPolicyUpsert,
    normalize_policy_symbol,
)
from app.services import investment_thesis
from app.services.investment_policy_repository import InvestmentPolicyRepository, utc_now_iso


class InvestmentPolicyError(ValueError):
    """Raised when an investment policy request cannot be fulfilled."""


class InvestmentPolicyService:
    def __init__(self, repository: InvestmentPolicyRepository) -> None:
        self.repository = repository

    def get_global_policy(self) -> GlobalInvestmentPolicy:
        stored = self.repository.get_global_policy()
        if stored is not None:
            return GlobalInvestmentPolicy.model_validate(stored)
        now = utc_now_iso()
        return GlobalInvestmentPolicy(
            created_at=now,
            updated_at=now,
            risk_profile="balanced",
            target_annual_return_pct=0.20,
            max_drawdown_tolerance_pct=0.25,
            allow_concentrated_position=True,
            allow_single_position_over_20_pct=True,
            allow_leverage=False,
            cash_reserve_pct=0.05,
            preferred_add_styles=["pullback_add", "batch_add"],
            preferred_sell_style="thesis_or_risk_trigger",
            holding_period="medium_to_long",
            notes="Default template. Save to create your own investment policy.",
            enabled=True,
        )

    def upsert_global_policy(self, payload: GlobalInvestmentPolicyUpsert) -> GlobalInvestmentPolicy:
        stored = self.repository.upsert_global_policy(payload.model_dump())
        return GlobalInvestmentPolicy.model_validate(stored)

    def list_symbol_policies(self, include_disabled: bool = True) -> list[SymbolInvestmentPolicy]:
        return [
            SymbolInvestmentPolicy.model_validate(item)
            for item in self.repository.list_symbol_policies(include_disabled=include_disabled)
        ]

    def get_symbol_policy(self, symbol: str) -> SymbolInvestmentPolicy | None:
        normalized = normalize_policy_symbol(symbol)
        if not normalized:
            raise InvestmentPolicyError("symbol is required")
        stored = self.repository.get_symbol_policy(normalized)
        if stored is not None:
            return SymbolInvestmentPolicy.model_validate(stored)
        fallback = self._fallback_policy_from_thesis(normalized)
        return fallback if fallback.symbol == normalized else None

    def get_policy_for_symbol(self, symbol: str) -> dict:
        normalized = normalize_policy_symbol(symbol)
        if not normalized:
            raise InvestmentPolicyError("symbol is required")
        stored = self.repository.get_symbol_policy(normalized)
        if stored is not None and stored.get("enabled", True):
            policy = SymbolInvestmentPolicy.model_validate(stored)
            return self._compatible_policy_dict(policy, source="user_config")
        fallback = self._fallback_policy_from_thesis(normalized)
        return self._compatible_policy_dict(fallback, source="default_template")

    def upsert_symbol_policy(self, symbol: str, payload: SymbolInvestmentPolicyUpsert) -> SymbolInvestmentPolicy:
        normalized = normalize_policy_symbol(symbol)
        if not normalized:
            raise InvestmentPolicyError("symbol is required")
        data = payload.model_dump()
        data["symbol"] = normalized
        policy = SymbolInvestmentPolicyUpsert.model_validate(data)
        stored = self.repository.upsert_symbol_policy(policy.model_dump())
        return SymbolInvestmentPolicy.model_validate(stored)

    def disable_symbol_policy(self, symbol: str) -> SymbolInvestmentPolicy:
        normalized = normalize_policy_symbol(symbol)
        if not normalized:
            raise InvestmentPolicyError("symbol is required")
        stored = self.repository.disable_symbol_policy(normalized)
        if stored is None:
            raise InvestmentPolicyError(f"Symbol policy not found: {normalized}")
        return SymbolInvestmentPolicy.model_validate(stored)

    def seed_defaults(self, force: bool = False) -> tuple[list[SymbolInvestmentPolicy], list[SymbolInvestmentPolicy]]:
        created: list[SymbolInvestmentPolicy] = []
        skipped: list[SymbolInvestmentPolicy] = []
        for symbol in investment_thesis.all_configured_symbols():
            existing = self.repository.get_symbol_policy(symbol)
            template = self._fallback_policy_from_thesis(symbol)
            if existing is not None and not force:
                skipped.append(SymbolInvestmentPolicy.model_validate(existing))
                continue
            stored = self.repository.upsert_symbol_policy(template.model_dump())
            created.append(SymbolInvestmentPolicy.model_validate(stored))
        return created, skipped

    def _fallback_policy_from_thesis(self, symbol: str) -> SymbolInvestmentPolicy:
        thesis = investment_thesis.get_thesis(symbol)
        now = utc_now_iso()
        asset_role = _asset_role_from_thesis(thesis.role)
        conviction = _conviction_from_risk_class(thesis.risk_class)
        user_preferred_target = thesis.target_position_pct
        user_preferred_max = thesis.max_position_pct
        if user_preferred_target is not None and user_preferred_target > user_preferred_max:
            user_preferred_target = user_preferred_max
        return SymbolInvestmentPolicy(
            id=InvestmentPolicyRepository.symbol_document_id(thesis.symbol),
            symbol=thesis.symbol,
            asset_role=asset_role,
            conviction=conviction,
            user_preferred_min_position_pct=0.0,
            user_preferred_target_position_pct=user_preferred_target,
            user_preferred_max_position_pct=user_preferred_max,
            add_rules=list(thesis.add_rules),
            no_add_triggers=list(thesis.no_add_triggers),
            sell_triggers=list(thesis.sell_triggers),
            hard_constraints=[],
            soft_preferences=list(thesis.hold_rules),
            notes="\n".join(thesis.core_thesis),
            enabled=True,
            created_at=now,
            updated_at=now,
            ai_review_status="unknown",
            ai_review_summary=None,
            ai_review_updated_at=None,
        )

    @staticmethod
    def _compatible_policy_dict(policy: SymbolInvestmentPolicy, source: str) -> dict:
        data = policy.model_dump()
        user_preference = {
            "asset_role": policy.asset_role,
            "conviction": policy.conviction,
            "user_preferred_target_position_pct": policy.user_preferred_target_position_pct,
            "user_preferred_max_position_pct": policy.user_preferred_max_position_pct,
            "user_preferred_min_position_pct": policy.user_preferred_min_position_pct,
            "add_rules": list(policy.add_rules),
            "no_add_triggers": list(policy.no_add_triggers),
            "sell_triggers": list(policy.sell_triggers),
            "hard_constraints": list(policy.hard_constraints),
            "soft_preferences": list(policy.soft_preferences),
            "notes": policy.notes,
            "enabled": policy.enabled,
            "ai_review_status": policy.ai_review_status,
            "ai_review_summary": policy.ai_review_summary,
            "ai_review_updated_at": policy.ai_review_updated_at,
            "disclaimer": "这是用户主观偏好，不是 AI 最终仓位建议",
        }
        data.update(
            {
                "source": source,
                "user_investment_preference": user_preference,
                # Backward-compatible fallback fields for older thesis/risk code.
                # They represent user/default preference context only and must
                # not be treated as AI final advice or a Risk Gate hard cap.
                "role": policy.asset_role,
                "risk_class": policy.conviction,
                "target_position_pct": policy.user_preferred_target_position_pct,
                "max_position_pct": policy.user_preferred_max_position_pct,
                "min_position_pct": policy.user_preferred_min_position_pct,
                "core_thesis": [line for line in policy.notes.splitlines() if line.strip()],
                "hold_rules": list(policy.soft_preferences),
                "review_frequency": "weekly",
                "metadata": {
                    "policy_type": "investment_policy",
                    "ai_review_status": policy.ai_review_status,
                },
            }
        )
        return data


def _asset_role_from_thesis(role: str) -> str:
    mapping = {
        investment_thesis.ROLE_CORE_GROWTH: "core_growth",
        investment_thesis.ROLE_BTC_PROXY: "btc_proxy",
        investment_thesis.ROLE_CLOUD_INFRA_GROWTH: "satellite_growth",
        investment_thesis.ROLE_SOFTWARE_PLATFORM: "core_growth",
        investment_thesis.SOCIAL_PLATFORM: "satellite_growth",
        investment_thesis.CORE_BALANCE: "cash_like",
        investment_thesis.OPPORTUNISTIC: "speculative",
        investment_thesis.ROLE_TRADE: "speculative",
        investment_thesis.ROLE_UNKNOWN: "unknown",
    }
    return mapping.get(role, "unknown")


def _conviction_from_risk_class(risk_class: str) -> str:
    if risk_class in {investment_thesis.RISK_CLASS_LOW, investment_thesis.RISK_CLASS_MEDIUM}:
        return "medium"
    if risk_class in {investment_thesis.RISK_CLASS_MEDIUM_HIGH, investment_thesis.RISK_CLASS_HIGH_GROWTH}:
        return "high"
    if risk_class == investment_thesis.RISK_CLASS_EXTREME:
        return "low"
    return "low"
