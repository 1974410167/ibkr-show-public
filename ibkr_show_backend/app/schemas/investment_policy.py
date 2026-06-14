from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


RiskProfile = Literal["conservative", "balanced", "aggressive_growth"]
AddStyle = Literal["left_side_add", "pullback_add", "right_side_confirm", "batch_add"]
AssetRole = Literal[
    "core_growth",
    "faith_holding",
    "satellite_growth",
    "speculative",
    "btc_proxy",
    "cash_like",
    "index_etf",
    "watchlist",
    "forbidden",
    "unknown",
]
Conviction = Literal["high", "medium", "low"]
AiReviewStatus = Literal["unknown", "reasonable", "questionable", "risky"]


def normalize_policy_symbol(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if "." in value:
        value = value.split(".", 1)[0]
    return value.strip()


class GlobalInvestmentPolicyBase(BaseModel):
    risk_profile: RiskProfile = "balanced"
    target_annual_return_pct: float | None = Field(default=None, ge=0, le=5)
    max_drawdown_tolerance_pct: float | None = Field(default=None, ge=0, le=1)
    allow_concentrated_position: bool = False
    allow_single_position_over_20_pct: bool = False
    allow_leverage: bool = False
    cash_reserve_pct: float | None = Field(default=None, ge=0, le=1)
    preferred_add_styles: list[AddStyle] = Field(default_factory=list)
    preferred_sell_style: str = ""
    holding_period: str = ""
    notes: str = ""
    enabled: bool = True


class GlobalInvestmentPolicyUpsert(GlobalInvestmentPolicyBase):
    pass


class GlobalInvestmentPolicy(GlobalInvestmentPolicyBase):
    id: str = "global"
    policy_type: Literal["global"] = "global"
    created_at: str
    updated_at: str


class SymbolInvestmentPolicyBase(BaseModel):
    model_config = ConfigDict(validate_by_name=True)

    symbol: str
    asset_role: AssetRole = "unknown"
    conviction: Conviction = "medium"
    user_preferred_target_position_pct: float | None = Field(
        default=None,
        ge=0,
        le=1,
        validation_alias=AliasChoices("user_preferred_target_position_pct", "target_position_pct"),
    )
    user_preferred_max_position_pct: float = Field(
        default=0.05,
        ge=0,
        le=1,
        validation_alias=AliasChoices("user_preferred_max_position_pct", "max_position_pct"),
    )
    user_preferred_min_position_pct: float = Field(
        default=0.0,
        ge=0,
        le=1,
        validation_alias=AliasChoices("user_preferred_min_position_pct", "min_position_pct"),
    )
    add_rules: list[str] = Field(default_factory=list)
    no_add_triggers: list[str] = Field(default_factory=list)
    sell_triggers: list[str] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    notes: str = ""
    enabled: bool = True
    ai_review_status: AiReviewStatus = "unknown"
    ai_review_summary: str | None = None
    ai_review_updated_at: str | None = None

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        normalized = normalize_policy_symbol(value)
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @field_validator(
        "add_rules",
        "no_add_triggers",
        "sell_triggers",
        "hard_constraints",
        "soft_preferences",
        mode="before",
    )
    @classmethod
    def _coerce_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise ValueError("must be a list of strings")

    @model_validator(mode="after")
    def _validate_position_order(self) -> "SymbolInvestmentPolicyBase":
        target = self.user_preferred_target_position_pct
        if target is None:
            target = self.user_preferred_min_position_pct
        if self.user_preferred_min_position_pct > target or target > self.user_preferred_max_position_pct:
            raise ValueError("user preferred position percentages must satisfy min <= target <= max")
        return self

    @property
    def target_position_pct(self) -> float | None:
        """Backward-compatible alias. This is a user preference, not an AI recommendation."""
        return self.user_preferred_target_position_pct

    @property
    def max_position_pct(self) -> float:
        """Backward-compatible alias. This is a user preference, not a Risk Gate hard cap."""
        return self.user_preferred_max_position_pct

    @property
    def min_position_pct(self) -> float:
        """Backward-compatible alias. This is a user preference, not a system minimum."""
        return self.user_preferred_min_position_pct


class SymbolInvestmentPolicyUpsert(SymbolInvestmentPolicyBase):
    pass


class SymbolInvestmentPolicy(SymbolInvestmentPolicyBase):
    id: str
    policy_type: Literal["symbol"] = "symbol"
    created_at: str
    updated_at: str


class SymbolInvestmentPolicyListResponse(BaseModel):
    items: list[SymbolInvestmentPolicy]


class InvestmentPolicySeedDefaultsResponse(BaseModel):
    created: list[SymbolInvestmentPolicy]
    skipped: list[SymbolInvestmentPolicy]
    message: str
