from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_investment_policy_service, require_admin_session
from app.core.auth import AuthSession
from app.schemas.investment_policy import (
    GlobalInvestmentPolicy,
    GlobalInvestmentPolicyUpsert,
    InvestmentPolicySeedDefaultsResponse,
    SymbolInvestmentPolicy,
    SymbolInvestmentPolicyListResponse,
    SymbolInvestmentPolicyUpsert,
)
from app.services.investment_policy_service import InvestmentPolicyError, InvestmentPolicyService

router = APIRouter(prefix="/investment-policy", tags=["investment-policy"])


@router.get("/global", response_model=GlobalInvestmentPolicy)
def get_global_policy(
    _auth: AuthSession = Depends(require_admin_session),
    svc: InvestmentPolicyService = Depends(get_investment_policy_service),
):
    return svc.get_global_policy()


@router.put("/global", response_model=GlobalInvestmentPolicy)
def upsert_global_policy(
    body: GlobalInvestmentPolicyUpsert,
    _auth: AuthSession = Depends(require_admin_session),
    svc: InvestmentPolicyService = Depends(get_investment_policy_service),
):
    return svc.upsert_global_policy(body)


@router.get("/symbols", response_model=SymbolInvestmentPolicyListResponse)
def list_symbol_policies(
    include_disabled: bool = Query(default=True),
    _auth: AuthSession = Depends(require_admin_session),
    svc: InvestmentPolicyService = Depends(get_investment_policy_service),
):
    return {"items": svc.list_symbol_policies(include_disabled=include_disabled)}


@router.get("/symbols/{symbol}", response_model=SymbolInvestmentPolicy)
def get_symbol_policy(
    symbol: str,
    _auth: AuthSession = Depends(require_admin_session),
    svc: InvestmentPolicyService = Depends(get_investment_policy_service),
):
    try:
        policy = svc.get_symbol_policy(symbol)
    except InvestmentPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if policy is None:
        raise HTTPException(status_code=404, detail="Symbol policy not found")
    return policy


@router.put("/symbols/{symbol}", response_model=SymbolInvestmentPolicy)
def upsert_symbol_policy(
    symbol: str,
    body: SymbolInvestmentPolicyUpsert,
    _auth: AuthSession = Depends(require_admin_session),
    svc: InvestmentPolicyService = Depends(get_investment_policy_service),
):
    try:
        return svc.upsert_symbol_policy(symbol, body)
    except InvestmentPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/symbols/{symbol}/disable", response_model=SymbolInvestmentPolicy)
def disable_symbol_policy(
    symbol: str,
    _auth: AuthSession = Depends(require_admin_session),
    svc: InvestmentPolicyService = Depends(get_investment_policy_service),
):
    try:
        return svc.disable_symbol_policy(symbol)
    except InvestmentPolicyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/seed-defaults", response_model=InvestmentPolicySeedDefaultsResponse)
def seed_default_policies(
    force: bool = Query(default=False),
    _auth: AuthSession = Depends(require_admin_session),
    svc: InvestmentPolicyService = Depends(get_investment_policy_service),
):
    created, skipped = svc.seed_defaults(force=force)
    return {
        "created": created,
        "skipped": skipped,
        "message": f"created {len(created)} default symbol policies; skipped {len(skipped)} existing policies",
    }
