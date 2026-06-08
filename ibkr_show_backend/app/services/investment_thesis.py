"""Investment Thesis - per-symbol play-book used by the risk gate and composer.

A thesis captures:
- role (core_growth / btc_proxy / etc.) and risk_class
- max position size budget
- core reasons to hold
- explicit add / hold / sell / no-add rules
- review cadence

This is intentionally a code-only config (no DB / no UI) in the first version.
When a symbol is not configured we return a conservative `unknown` thesis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Role and risk_class enums are plain strings to keep things simple and
# forward-compatible. We still expose constants so callers and tests can
# reference the canonical values.
ROLE_CORE_GROWTH = "core_growth"
ROLE_BTC_PROXY = "btc_proxy"
ROLE_CLOUD_INFRA_GROWTH = "cloud_infra_growth"
ROLE_SOFTWARE_PLATFORM = "software_platform"
SOCIAL_PLATFORM = "social_platform"
CORE_BALANCE = "core_balance"
OPPORTUNISTIC = "opportunistic"
ROLE_TRADE = "trade"
ROLE_UNKNOWN = "unknown"

RISK_CLASS_LOW = "low"
RISK_CLASS_MEDIUM = "medium"
RISK_CLASS_MEDIUM_HIGH = "medium_high"
RISK_CLASS_HIGH_GROWTH = "high_growth"
RISK_CLASS_EXTREME = "extreme"
RISK_CLASS_UNKNOWN = "unknown"

REVIEW_DAILY = "daily"
REVIEW_WEEKLY = "weekly"
REVIEW_QUARTERLY = "quarterly"
REVIEW_UNKNOWN = "unknown"


@dataclass
class InvestmentThesis:
    symbol: str
    role: str = ROLE_UNKNOWN
    risk_class: str = RISK_CLASS_UNKNOWN
    max_position_pct: float = 0.05
    target_position_pct: float | None = None
    core_thesis: list[str] = field(default_factory=list)
    add_rules: list[str] = field(default_factory=list)
    hold_rules: list[str] = field(default_factory=list)
    sell_triggers: list[str] = field(default_factory=list)
    no_add_triggers: list[str] = field(default_factory=list)
    review_frequency: str = REVIEW_UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "role": self.role,
            "risk_class": self.risk_class,
            "max_position_pct": self.max_position_pct,
            "target_position_pct": self.target_position_pct,
            "core_thesis": list(self.core_thesis),
            "add_rules": list(self.add_rules),
            "hold_rules": list(self.hold_rules),
            "sell_triggers": list(self.sell_triggers),
            "no_add_triggers": list(self.no_add_triggers),
            "review_frequency": self.review_frequency,
            "metadata": dict(self.metadata),
        }


# --- Default (unknown symbol) thesis ----------------------------------------

DEFAULT_THESIS = InvestmentThesis(
    symbol="*",
    role=ROLE_UNKNOWN,
    risk_class=RISK_CLASS_UNKNOWN,
    max_position_pct=0.05,
    target_position_pct=0.03,
    core_thesis=[],
    add_rules=[],
    hold_rules=[],
    sell_triggers=[],
    no_add_triggers=[],
    review_frequency=REVIEW_WEEKLY,
    metadata={"default": True},
)


# --- Per-symbol thesis registry ---------------------------------------------

# Each entry holds the symbol-specific thesis. When a symbol is missing we
# fall back to DEFAULT_THESIS.

_THESIS_REGISTRY: dict[str, InvestmentThesis] = {
    "AMD": InvestmentThesis(
        symbol="AMD",
        role=ROLE_CORE_GROWTH,
        risk_class=RISK_CLASS_HIGH_GROWTH,
        max_position_pct=0.28,
        target_position_pct=0.20,
        core_thesis=[
            "AI GPU 收入持续增长",
            "数据中心业务增速高于整体",
            "毛利率不恶化",
        ],
        add_rules=[
            "回调至 MA50/MA200 附近且趋势未 broken",
            "AI 业务指引兑现或上修",
        ],
        hold_rules=[
            "趋势处于 none / warning，未触发 sell_triggers",
            "公司基本面前瞻维持良好",
        ],
        sell_triggers=[
            "AI GPU 指引连续两个季度不及预期",
            "数据中心收入同比转负",
            "股价跌破 MA200 且基本面 red",
        ],
        no_add_triggers=[
            "trend_break_level=broken / severe",
            "PE 显著高于历史区间且无催化",
        ],
        review_frequency=REVIEW_WEEKLY,
        metadata={"sector": "semiconductors"},
    ),
    "MSTR": InvestmentThesis(
        symbol="MSTR",
        role=ROLE_BTC_PROXY,
        risk_class=RISK_CLASS_EXTREME,
        max_position_pct=0.10,
        target_position_pct=0.05,
        core_thesis=[
            "BTC 长期上涨",
            "MSTR 溢价可维持",
        ],
        add_rules=[
            "BTC 趋势 none / warning",
            "MSTR 相对 NAV 折价而非溢价",
        ],
        hold_rules=[
            "BTC 趋势 none / warning",
            "融资/稀释风险未显著上升",
        ],
        sell_triggers=[
            "BTC 趋势 severe broken",
            "NAV 溢价大幅压缩",
            "融资 / 稀释风险显著上升",
        ],
        no_add_triggers=[
            "BTC trend_break_level=broken / severe",
            "MSTR 溢价显著高于历史",
        ],
        review_frequency=REVIEW_DAILY,
        metadata={"sector": "btc_proxy", "high_vol": True},
    ),
    "ORCL": InvestmentThesis(
        symbol="ORCL",
        role=ROLE_CLOUD_INFRA_GROWTH,
        risk_class=RISK_CLASS_MEDIUM_HIGH,
        max_position_pct=0.12,
        target_position_pct=0.08,
        core_thesis=[
            "RPO 增长",
            "云收入增长",
            "AI 基建需求兑现",
        ],
        add_rules=[
            "云收入增速维持或加速",
            "CapEx 压力未显著影响现金流",
        ],
        hold_rules=[
            "云收入增速稳定",
            "毛利率无明显恶化",
        ],
        sell_triggers=[
            "云收入增速明显放缓",
            "CapEx 压力导致现金流恶化",
        ],
        no_add_triggers=[
            "云收入增速连续两季放缓",
            "自由流转负且无短期修复",
        ],
        review_frequency=REVIEW_QUARTERLY,
        metadata={"sector": "cloud_infra"},
    ),
    "MSFT": InvestmentThesis(
        symbol="MSFT",
        role=ROLE_SOFTWARE_PLATFORM,
        risk_class=RISK_CLASS_MEDIUM,
        max_position_pct=0.20,
        target_position_pct=0.15,
        core_thesis=[
            "Azure 收入持续增长",
            "AI 商业化路径明确",
            "现金流稳定",
        ],
        add_rules=[
            "Azure 增速维持双位数",
            "AI 业务收入贡献可见",
        ],
        hold_rules=[
            "Azure 增速未明显放缓",
            "经营利润率维持稳定",
        ],
        sell_triggers=[
            "Azure 收入连续两季同比转负",
            "云市场份额持续丢失",
        ],
        no_add_triggers=[
            "PE 显著高于历史区间",
            "增长指引连续下调",
        ],
        review_frequency=REVIEW_QUARTERLY,
        metadata={"sector": "software_platform"},
    ),
    "META": InvestmentThesis(
        symbol="META",
        role=SOCIAL_PLATFORM,
        risk_class=RISK_CLASS_MEDIUM_HIGH,
        max_position_pct=0.15,
        target_position_pct=0.10,
        core_thesis=[
            "广告业务复苏",
            "AI 提升推荐效率",
            "Reality Labs 亏损可控",
        ],
        add_rules=[
            "广告业务增速维持或加速",
            "经营杠杆释放",
        ],
        hold_rules=[
            "广告收入增长稳定",
            "AI 投入产生可量化回报",
        ],
        sell_triggers=[
            "广告收入持续放缓",
            "Reality Labs 亏损显著扩大",
            "AI 资本支出无法支撑",
        ],
        no_add_triggers=[
            "PE 显著高于历史区间",
            "广告业务景气度向下",
        ],
        review_frequency=REVIEW_QUARTERLY,
        metadata={"sector": "social_platform"},
    ),
    "XIACY": InvestmentThesis(
        symbol="XIACY",
        role=CORE_BALANCE,
        risk_class=RISK_CLASS_LOW,
        max_position_pct=0.05,
        target_position_pct=0.03,
        core_thesis=[
            "保守型资产",
            "波动性低",
        ],
        add_rules=[
            "组合整体风险敞口偏低时少量配置",
        ],
        hold_rules=[
            "保持稳定仓位",
        ],
        sell_triggers=[
            "组合整体风险敞口偏高需再平衡",
        ],
        no_add_triggers=[
            "组合中已超配保守资产",
        ],
        review_frequency=REVIEW_QUARTERLY,
        metadata={"sector": "balance"},
    ),
    "SMCI": InvestmentThesis(
        symbol="SMCI",
        role=OPPORTUNISTIC,
        risk_class=RISK_CLASS_HIGH_GROWTH,
        max_position_pct=0.08,
        target_position_pct=0.05,
        core_thesis=[
            "AI 服务器需求",
            "毛利率稳定",
            "交付能力改善",
        ],
        add_rules=[
            "毛利率稳定或改善",
            "审计/合规问题已解决",
        ],
        hold_rules=[
            "毛利率无明显恶化",
            "现金流维持正向",
        ],
        sell_triggers=[
            "审计/合规问题再次出现",
            "毛利率连续下台阶",
            "AI 服务器订单大幅低于预期",
        ],
        no_add_triggers=[
            "趋势 broken / severe",
            "审计/合规问题未解决",
        ],
        review_frequency=REVIEW_WEEKLY,
        metadata={"sector": "ai_servers"},
    ),
}


# --- Helpers ---------------------------------------------------------------

def _normalize_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    return str(symbol).upper().split(".", 1)[0].strip()


def get_thesis(symbol: str) -> InvestmentThesis:
    """Return the per-symbol thesis or a default thesis if not configured.

    A copy is returned (not the registry entry) so callers cannot mutate
    shared state by accident.
    """
    key = _normalize_symbol(symbol)
    template = _THESIS_REGISTRY.get(key) or DEFAULT_THESIS
    # Make a fresh copy so callers can mutate freely
    return InvestmentThesis(
        symbol=key or template.symbol,
        role=template.role,
        risk_class=template.risk_class,
        max_position_pct=template.max_position_pct,
        target_position_pct=template.target_position_pct,
        core_thesis=list(template.core_thesis),
        add_rules=list(template.add_rules),
        hold_rules=list(template.hold_rules),
        sell_triggers=list(template.sell_triggers),
        no_add_triggers=list(template.no_add_triggers),
        review_frequency=template.review_frequency,
        metadata=dict(template.metadata),
    )


def all_configured_symbols() -> list[str]:
    return sorted(_THESIS_REGISTRY.keys())


def is_thesis_known(thesis: InvestmentThesis) -> bool:
    return thesis.role != ROLE_UNKNOWN and thesis.risk_class != RISK_CLASS_UNKNOWN


# --- Trigger evaluation -----------------------------------------------------

def evaluate_no_add_triggers(
    thesis: InvestmentThesis,
    *,
    position_pct: float | None = None,
    trend_break_level: str | None = None,
    catalyst_strength: str | None = None,
) -> list[str]:
    """Return a list of triggered no_add rule names (heuristic).

    Currently this matches simple textual patterns in the configured rules.
    The Risk Gate also keeps its own structural checks; this is meant to
    surface the configured rule names for explainability.
    """
    triggered: list[str] = []
    if trend_break_level in {"broken", "severe"}:
        for rule in thesis.no_add_triggers:
            if "trend_break" in rule or "broken" in rule or "severe" in rule:
                triggered.append(rule)
    if position_pct is not None and thesis.max_position_pct and position_pct >= thesis.max_position_pct:
        for rule in thesis.no_add_triggers:
            if "上限" in rule or "超配" in rule:
                triggered.append(rule)
    if catalyst_strength in {"weak", "no_catalyst"}:
        for rule in thesis.no_add_triggers:
            if "催化" in rule or "指引" in rule or "增长" in rule:
                triggered.append(rule)
    # De-dup
    return list(dict.fromkeys(triggered))


def evaluate_sell_triggers(
    thesis: InvestmentThesis,
    *,
    trend_break_level: str | None = None,
    fundamental_red: bool = False,
) -> list[str]:
    """Return a list of triggered sell_triggers.

    Used by the Risk Gate to escalate to reduce_now / sell_thesis_broken.
    """
    triggered: list[str] = []
    if trend_break_level == "severe":
        for rule in thesis.sell_triggers:
            if "severe" in rule or "MA200" in rule or "趋势" in rule:
                triggered.append(rule)
    if fundamental_red:
        for rule in thesis.sell_triggers:
            if "red" in rule or "不及预期" in rule or "放缓" in rule or "恶化" in rule:
                triggered.append(rule)
    return list(dict.fromkeys(triggered))


__all__ = [
    "InvestmentThesis",
    "DEFAULT_THESIS",
    "ROLE_CORE_GROWTH",
    "ROLE_BTC_PROXY",
    "ROLE_CLOUD_INFRA_GROWTH",
    "ROLE_SOFTWARE_PLATFORM",
    "SOCIAL_PLATFORM",
    "CORE_BALANCE",
    "OPPORTUNISTIC",
    "ROLE_TRADE",
    "ROLE_UNKNOWN",
    "RISK_CLASS_LOW",
    "RISK_CLASS_MEDIUM",
    "RISK_CLASS_MEDIUM_HIGH",
    "RISK_CLASS_HIGH_GROWTH",
    "RISK_CLASS_EXTREME",
    "RISK_CLASS_UNKNOWN",
    "REVIEW_DAILY",
    "REVIEW_WEEKLY",
    "REVIEW_QUARTERLY",
    "REVIEW_UNKNOWN",
    "get_thesis",
    "all_configured_symbols",
    "is_thesis_known",
    "evaluate_no_add_triggers",
    "evaluate_sell_triggers",
]
