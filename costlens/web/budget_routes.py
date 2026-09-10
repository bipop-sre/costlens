"""Budget management API routes."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from costlens.web.auth import verify_token
from costlens.storage import get_storage
from costlens.models.budget import Budget, BudgetPeriod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/budgets", dependencies=[Depends(verify_token)])


class BudgetCreateRequest(BaseModel):
    name: str
    amount: float
    currency: str = "CNY"
    period: str = "monthly"
    provider: Optional[str] = None
    service_name: Optional[str] = None
    alert_thresholds: list[float] = [50.0, 80.0, 100.0]


@router.get("")
async def get_budgets():
    """Get all budgets with current spend status."""
    from costlens.analysis.monthly_comparison import _query_month_data

    storage = get_storage()
    budgets = storage.get_budgets()

    today = date.today()
    month_data = _query_month_data(today.year, today.month)

    result = []
    for budget in budgets:
        current_spend = 0
        if budget.provider and budget.service_name:
            for svc in month_data["services"]:
                if svc["provider"] == budget.provider and svc["service"] == budget.service_name:
                    current_spend = svc["cost"]
                    break
        elif budget.provider:
            current_spend = month_data["providers"].get(budget.provider, {}).get("cost", 0)
        else:
            current_spend = month_data["total_cost"]

        utilization = (current_spend / budget.amount * 100) if budget.amount > 0 else 0
        status = "on_track"
        if utilization >= 100:
            status = "exceeded"
        elif utilization >= 80:
            status = "warning"
        elif utilization >= 50:
            status = "caution"

        result.append({
            "name": budget.name,
            "amount": budget.amount,
            "currency": budget.currency,
            "period": budget.period.value if hasattr(budget.period, 'value') else budget.period,
            "provider": budget.provider,
            "service_name": budget.service_name,
            "alert_thresholds": budget.alert_thresholds,
            "current_spend": current_spend,
            "utilization": round(utilization, 1),
            "status": status,
            "remaining": max(0, budget.amount - current_spend),
        })

    return {"budgets": result}


@router.post("")
async def create_budget(request: BudgetCreateRequest):
    """Create a new budget."""
    storage = get_storage()

    existing = storage.get_budgets()
    for b in existing:
        if b.name == request.name:
            raise HTTPException(status_code=400, detail=f"Budget '{request.name}' already exists")

    budget = Budget(
        name=request.name,
        amount=request.amount,
        currency=request.currency,
        period=BudgetPeriod(request.period),
        provider=request.provider,
        service_name=request.service_name,
        alert_thresholds=request.alert_thresholds,
    )

    storage.save_budget(budget)
    logger.info("Created budget: %s", request.name)
    return {"status": "created", "name": request.name}


@router.put("/{name}")
async def update_budget(name: str, request: BudgetCreateRequest):
    """Update an existing budget."""
    storage = get_storage()

    budget = Budget(
        name=name,
        amount=request.amount,
        currency=request.currency,
        period=BudgetPeriod(request.period),
        provider=request.provider,
        service_name=request.service_name,
        alert_thresholds=request.alert_thresholds,
    )

    storage.save_budget(budget)
    logger.info("Updated budget: %s", name)
    return {"status": "updated", "name": name}


@router.delete("/{name}")
async def delete_budget(name: str):
    """Delete a budget."""
    storage = get_storage()

    if storage.delete_budget(name):
        logger.info("Deleted budget: %s", name)
        return {"status": "deleted", "name": name}
    else:
        raise HTTPException(status_code=404, detail=f"Budget '{name}' not found")


@router.post("/check")
async def check_budgets():
    """Check all budgets and create alerts if needed."""
    from costlens.analysis.monthly_comparison import _query_month_data

    storage = get_storage()
    budgets = storage.get_budgets()

    if not budgets:
        return {"status": "no_budgets", "alerts_created": 0}

    today = date.today()
    month_data = _query_month_data(today.year, today.month)

    alerts_created = 0

    for budget in budgets:
        current_spend = 0
        if budget.provider and budget.service_name:
            for svc in month_data["services"]:
                if svc["provider"] == budget.provider and svc["service"] == budget.service_name:
                    current_spend = svc["cost"]
                    break
        elif budget.provider:
            current_spend = month_data["providers"].get(budget.provider, {}).get("cost", 0)
        else:
            current_spend = month_data["total_cost"]

        utilization = (current_spend / budget.amount * 100) if budget.amount > 0 else 0

        for threshold in budget.alert_thresholds:
            if utilization >= threshold:
                existing_alerts = storage.get_alerts(limit=100)
                already_alerted = any(
                    a.get("alert_type") == "budget_threshold" and
                    budget.name in a.get("title", "") and
                    f"{threshold:.0f}%" in a.get("title", "") and
                    a.get("timestamp", "").startswith(f"{today.year}-{today.month:02d}")
                    for a in existing_alerts
                )

                if not already_alerted:
                    from costlens.models.alert import Alert, AlertSeverity, AlertType
                    severity = AlertSeverity.CRITICAL if threshold >= 100 else AlertSeverity.WARNING

                    from costlens.web.app import PROVIDER_NAMES
                    scope = ""
                    if budget.provider:
                        scope = f" - {PROVIDER_NAMES.get(budget.provider, budget.provider)}"
                    if budget.service_name:
                        scope += f" - {budget.service_name}"

                    alert = Alert(
                        alert_type=AlertType.BUDGET_THRESHOLD,
                        severity=severity,
                        title=f"预算 {budget.name}{scope} 已达 {threshold:.0f}%",
                        message=(
                            f"预算 '{budget.name}' 当前花费 ¥{current_spend:,.2f}，"
                            f"已达预算 ¥{budget.amount:,.2f} 的 {utilization:.1f}%，"
                            f"剩余 ¥{max(0, budget.amount - current_spend):,.2f}"
                        ),
                        provider=budget.provider or "multi-cloud",
                        current_value=current_spend,
                        threshold_value=budget.amount * threshold / 100,
                    )

                    storage.save_alert(alert)
                    alerts_created += 1
                    break

    logger.info("Budget check completed, created %d alerts", alerts_created)
    return {"status": "checked", "alerts_created": alerts_created}
