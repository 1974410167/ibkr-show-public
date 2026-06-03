from __future__ import annotations

from app.agents.eval_harness import EvalCase
from app.agents.eval_cases.account_copilot_cases import CASES as ACCOUNT_COPILOT_CASES
from app.agents.eval_cases.daily_position_review_cases import CASES as DAILY_POSITION_REVIEW_CASES
from app.agents.eval_cases.judge_calibration_cases import CASES as JUDGE_CALIBRATION_CASES
from app.agents.eval_cases.trade_decision_cases import CASES as TRADE_DECISION_CASES
from app.agents.eval_cases.trade_review_cases import CASES as TRADE_REVIEW_CASES


def list_builtin_eval_cases() -> list[EvalCase]:
    return [
        *ACCOUNT_COPILOT_CASES,
        *TRADE_REVIEW_CASES,
        *DAILY_POSITION_REVIEW_CASES,
        *TRADE_DECISION_CASES,
        *JUDGE_CALIBRATION_CASES,
    ]
