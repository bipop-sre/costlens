"""Storage-backed API routes for persistent data."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from costlens.storage import get_storage

router = APIRouter(prefix="/api/storage", tags=["storage"])


class BudgetCreate(BaseModel):
    name: str
    amount: float
    currency: str = "USD"
    period: str = "monthly"
    provider: Optional[str] = None
    service_name: Optional[str] = None


class NotificationConfig(BaseModel):
    dingtalk_webhook: Optional[str] = None
    dingtalk_secret: Optional[str] = None
    feishu_webhook: Optional[str] = None


@router.get("/costs")
async def query_costs(
    days: int = 30,
    provider: Optional[str] = None,
    service: Optional[str] = None,
):
    """Query persisted cost records."""
    storage = get_storage()
    end = date.today()
    start = end - timedelta(days=days)
    records = storage.get_cost_records(start, end, provider, service)
    return {
        "count": len(records),
        "records": [r.model_dump() for r in records],
    }


@router.get("/costs/daily")
async def daily_totals(days: int = 30, provider: Optional[str] = None):
    """Get daily cost totals from storage."""
    storage = get_storage()
    end = date.today()
    start = end - timedelta(days=days)
    totals = storage.get_daily_totals(start, end, provider)
    return {"daily_totals": totals}


@router.get("/costs/services")
async def service_totals(days: int = 30, provider: Optional[str] = None):
    """Get cost totals by service from storage."""
    storage = get_storage()
    end = date.today()
    start = end - timedelta(days=days)
    totals = storage.get_service_totals(start, end, provider)
    return {"service_totals": totals}


@router.get("/alerts")
async def query_alerts(
    days: int = 30,
    severity: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    limit: int = 100,
):
    """Query persisted alerts."""
    storage = get_storage()
    start = date.today() - timedelta(days=days) if days > 0 else None
    alerts = storage.get_alerts(start_date=start, severity=severity,
                                 acknowledged=acknowledged, limit=limit)
    return {"count": len(alerts), "alerts": alerts}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    """Acknowledge an alert."""
    storage = get_storage()
    if storage.acknowledge_alert(alert_id):
        return {"status": "acknowledged", "alert_id": alert_id}
    raise HTTPException(status_code=404, detail="Alert not found")


@router.get("/recommendations")
async def query_recommendations(
    priority: Optional[str] = None,
    limit: int = 50,
):
    """Query persisted recommendations."""
    storage = get_storage()
    recs = storage.get_recommendations(priority=priority, limit=limit)
    total_savings = storage.get_total_potential_savings()
    return {
        "count": len(recs),
        "recommendations": recs,
        "total_potential_savings": round(total_savings, 2),
    }


@router.post("/budgets")
async def create_budget(request: BudgetCreate):
    """Create or update a budget."""
    from costlens.models.budget import Budget, BudgetPeriod
    storage = get_storage()
    budget = Budget(
        name=request.name,
        amount=request.amount,
        currency=request.currency,
        period=BudgetPeriod(request.period),
        provider=request.provider,
        service_name=request.service_name,
    )
    budget_id = storage.save_budget(budget)
    return {"status": "saved", "id": budget_id, "budget": budget.model_dump()}


@router.get("/budgets")
async def list_budgets():
    """List all budgets."""
    storage = get_storage()
    budgets = storage.get_budgets()
    return {"count": len(budgets), "budgets": [b.model_dump() for b in budgets]}


@router.delete("/budgets/{name}")
async def delete_budget(name: str):
    """Delete a budget."""
    storage = get_storage()
    if storage.delete_budget(name):
        return {"status": "deleted", "name": name}
    raise HTTPException(status_code=404, detail="Budget not found")


@router.get("/analysis-runs")
async def list_analysis_runs(limit: int = 10):
    """List recent analysis runs."""
    storage = get_storage()
    runs = storage.get_analysis_runs(limit)
    return {"count": len(runs), "runs": runs}


@router.get("/stats")
async def storage_stats():
    """Get storage statistics."""
    storage = get_storage()
    stats = storage.get_stats()
    return stats


@router.post("/notifications/configure")
async def configure_notifications(config: NotificationConfig):
    """Configure notification providers."""
    from costlens.notifications import get_notification_manager

    manager = get_notification_manager()

    configured = []
    if config.dingtalk_webhook:
        manager.add_dingtalk(config.dingtalk_webhook, config.dingtalk_secret)
        configured.append("dingtalk")
    if config.feishu_webhook:
        manager.add_feishu(config.feishu_webhook)
        configured.append("feishu")
    return {"status": "configured", "providers": configured}


@router.post("/notifications/send-pending")
async def send_pending_notifications():
    """Send pending alert notifications."""
    from costlens.models.alert import Alert, AlertSeverity, AlertType
    from costlens.notifications import get_notification_manager

    storage = get_storage()
    manager = get_notification_manager()

    pending = storage.get_unnotified_alerts()
    if not pending:
        return {"status": "no_pending", "count": 0}

    alerts = []
    alert_ids = []
    for row in pending:
        alerts.append(Alert(
            alert_type=AlertType(row["alert_type"]),
            severity=AlertSeverity(row["severity"]),
            title=row["title"],
            message=row["message"],
            provider=row["provider"],
            current_value=row["current_value"],
            threshold_value=row["threshold_value"],
            currency=row["currency"],
            resource_id=row["resource_id"],
        ))
        alert_ids.append(row["id"])

    results = await manager.notify_batch(alerts)
    storage.mark_alerts_notified(alert_ids)

    return {
        "alerts_sent": len(alerts),
        "notification_results": results,
    }


@router.post("/demo/generate")
async def generate_demo_data():
    """Generate demo dataset for testing."""
    from costlens.mock_data import generate_demo_dataset

    result = generate_demo_dataset("costlens_demo.db")
    return result
