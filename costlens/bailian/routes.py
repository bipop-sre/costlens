"""Web API routes for Bailian token usage monitoring."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from costlens.bailian.tracker import get_bailian_tracker
from costlens.web.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bailian", tags=["bailian"])


# ── Request/Response Models ──


class ApiKeyCreate(BaseModel):
    key_alias: str
    key_prefix: str = ""
    description: str = ""


class UsageRecordRequest(BaseModel):
    key_alias: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 1
    usage_date: Optional[str] = None
    request_id: str = ""


class UsageFromResponseRequest(BaseModel):
    key_alias: str
    model_name: str
    usage: dict = Field(default_factory=dict)
    request_id: str = ""


# ── API Key Management ──


@router.get("/keys", dependencies=[Depends(verify_token)])
async def list_keys(active_only: bool = True):
    """List registered Bailian API keys."""
    tracker = get_bailian_tracker()
    keys = tracker.list_api_keys(active_only=active_only)
    return {
        "keys": [
            {
                "key_alias": k.key_alias,
                "key_prefix": k.key_prefix,
                "description": k.description,
                "is_active": k.is_active,
                "created_at": str(k.created_at),
            }
            for k in keys
        ]
    }


@router.post("/keys", dependencies=[Depends(verify_token)])
async def add_key(req: ApiKeyCreate):
    """Register a new Bailian API key for tracking."""
    tracker = get_bailian_tracker()
    tracker.add_api_key(req.key_alias, req.key_prefix, req.description)
    return {"status": "ok", "key_alias": req.key_alias}


@router.delete("/keys/{key_alias}", dependencies=[Depends(verify_token)])
async def remove_key(key_alias: str):
    """Deactivate an API key."""
    tracker = get_bailian_tracker()
    tracker.remove_api_key(key_alias)
    return {"status": "ok"}


# ── Usage Recording ──


@router.post("/usage", dependencies=[Depends(verify_token)])
async def record_usage(req: UsageRecordRequest):
    """Record token usage from an API call."""
    tracker = get_bailian_tracker()
    usage_date = None
    if req.usage_date:
        try:
            usage_date = date.fromisoformat(req.usage_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")

    record = tracker.record_usage(
        key_alias=req.key_alias,
        model_name=req.model_name,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        call_count=req.call_count,
        usage_date=usage_date,
        request_id=req.request_id,
    )
    return {
        "status": "ok",
        "total_tokens": record.total_tokens,
        "estimated_cost": record.estimated_cost,
    }


@router.post("/usage/from-response", dependencies=[Depends(verify_token)])
async def record_usage_from_response(req: UsageFromResponseRequest):
    """Record usage from an OpenAI-compatible API response."""
    tracker = get_bailian_tracker()
    record = tracker.record_from_response(
        key_alias=req.key_alias,
        model_name=req.model_name,
        response_usage=req.usage,
        request_id=req.request_id,
    )
    if record is None:
        return {"status": "skipped", "reason": "no usage data"}
    return {
        "status": "ok",
        "total_tokens": record.total_tokens,
        "estimated_cost": record.estimated_cost,
    }


# ── Usage Querying ──


@router.get("/usage/summary", dependencies=[Depends(verify_token)])
async def get_summary(
    days: int = Query(30, ge=1, le=365),
    key_alias: Optional[str] = None,
):
    """Get aggregated usage summary per API key."""
    tracker = get_bailian_tracker()
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    summaries = tracker.get_usage_summary(start_date, end_date, key_alias)
    model_breakdown = tracker.get_model_breakdown(start_date, end_date, key_alias)

    # Aggregate model breakdown by model across all keys
    model_totals: dict[str, dict] = {}
    for item in model_breakdown:
        model = item.model_name
        if model not in model_totals:
            model_totals[model] = {"input": 0, "output": 0, "total": 0, "calls": 0, "cost": 0.0}
        model_totals[model]["input"] += item.total_input_tokens
        model_totals[model]["output"] += item.total_output_tokens
        model_totals[model]["total"] += item.total_tokens
        model_totals[model]["calls"] += item.total_calls
        model_totals[model]["cost"] += item.total_cost

    top_models = sorted(model_totals.items(), key=lambda x: -x[1]["total"])[:10]

    # Grand totals
    grand_input = sum(s.total_input_tokens for s in summaries)
    grand_output = sum(s.total_output_tokens for s in summaries)
    grand_total = sum(s.total_tokens for s in summaries)
    grand_calls = sum(s.total_calls for s in summaries)
    grand_cost = sum(s.total_cost for s in summaries)

    return {
        "period": {"start": str(start_date), "end": str(end_date), "days": days},
        "totals": {
            "input_tokens": grand_input,
            "output_tokens": grand_output,
            "total_tokens": grand_total,
            "calls": grand_calls,
            "estimated_cost": round(grand_cost, 4),
        },
        "by_key": [
            {
                "key_alias": s.key_alias,
                "input_tokens": s.total_input_tokens,
                "output_tokens": s.total_output_tokens,
                "total_tokens": s.total_tokens,
                "calls": s.total_calls,
                "estimated_cost": s.total_cost,
                "output_ratio": round(s.output_ratio, 1),
                "daily_avg_tokens": s.daily_avg_tokens,
                "daily_avg_cost": s.daily_avg_cost,
            }
            for s in summaries
        ],
        "top_models": [
            {
                "model": model,
                "input_tokens": data["input"],
                "output_tokens": data["output"],
                "total_tokens": data["total"],
                "calls": data["calls"],
                "cost": round(data["cost"], 4),
            }
            for model, data in top_models
        ],
    }


@router.get("/usage/daily", dependencies=[Depends(verify_token)])
async def get_daily_usage(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    key_alias: Optional[str] = None,
):
    """Get daily usage data for a specific month."""
    tracker = get_bailian_tracker()

    daily_by_key = tracker.get_daily_usage(year, month, key_alias)
    daily_totals = tracker.get_daily_totals(year, month)

    return {
        "year": year,
        "month": month,
        "daily": daily_by_key,
        "totals": daily_totals,
    }


@router.get("/usage/models", dependencies=[Depends(verify_token)])
async def get_model_usage(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=50),
):
    """Get top models by token consumption."""
    tracker = get_bailian_tracker()
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    models = tracker.get_top_models(start_date, end_date, limit)
    return {"models": models, "period": {"start": str(start_date), "end": str(end_date)}}


@router.get("/usage/trend", dependencies=[Depends(verify_token)])
async def get_usage_trend(months: int = Query(6, ge=1, le=12)):
    """Get monthly usage trend over the last N months."""
    tracker = get_bailian_tracker()
    today = date.today()
    trend = []

    for i in range(months - 1, -1, -1):
        d = date(today.year, today.month, 1) - timedelta(days=i * 30)
        y, m = d.year, d.month
        start = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(y, m + 1, 1) - timedelta(days=1)

        summaries = tracker.get_usage_summary(start, end)
        total_tokens = sum(s.total_tokens for s in summaries)
        total_input = sum(s.total_input_tokens for s in summaries)
        total_output = sum(s.total_output_tokens for s in summaries)
        total_calls = sum(s.total_calls for s in summaries)
        total_cost = sum(s.total_cost for s in summaries)

        trend.append({
            "year": y,
            "month": m,
            "label": f"{y}-{m:02d}",
            "total_tokens": total_tokens,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "calls": total_calls,
            "cost": round(total_cost, 4),
        })

    return {"trend": trend}


# ── Diagnostic ──


@router.get("/diagnose", dependencies=[Depends(verify_token)])
async def diagnose():
    """Diagnostic endpoint to verify the entire Bailian tracking pipeline."""
    import traceback
    results = {"steps": []}

    # Step 1: Check tracker initialization
    try:
        tracker = get_bailian_tracker()
        results["steps"].append({"step": "tracker_init", "status": "ok"})
    except Exception as exc:
        results["steps"].append({"step": "tracker_init", "status": "error", "error": str(exc), "traceback": traceback.format_exc()})
        results["overall"] = "failed"
        return results

    # Step 2: Check API keys
    try:
        keys = tracker.list_api_keys(active_only=False)
        results["steps"].append({"step": "list_keys", "status": "ok", "count": len(keys), "keys": [k.key_alias for k in keys]})
    except Exception as exc:
        results["steps"].append({"step": "list_keys", "status": "error", "error": str(exc)})

    # Step 3: Write test record
    try:
        from datetime import date as dt_date
        test_date = dt_date(2020, 1, 1)
        record = tracker.record_usage(
            key_alias="__diag__",
            model_name="test-model",
            input_tokens=100,
            output_tokens=50,
            usage_date=test_date,
            request_id="diag-test-001",
        )
        results["steps"].append({
            "step": "write_test",
            "status": "ok",
            "total_tokens": record.total_tokens,
            "estimated_cost": record.estimated_cost,
        })
    except Exception as exc:
        results["steps"].append({"step": "write_test", "status": "error", "error": str(exc), "traceback": traceback.format_exc()})
        results["overall"] = "failed"
        return results

    # Step 4: Read back test record
    try:
        from costlens.db import get_backend
        backend = get_backend()
        sql = backend.adapt_sql(
            "SELECT COUNT(*) as cnt FROM bailian_usage_records WHERE key_alias = ?"
        )
        with backend.connect() as conn:
            row = conn.execute(sql, ("__diag__",)).fetchone()
            count = row["cnt"] if row else 0
        results["steps"].append({"step": "read_test", "status": "ok", "diag_records": count})
    except Exception as exc:
        results["steps"].append({"step": "read_test", "status": "error", "error": str(exc), "traceback": traceback.format_exc()})

    # Step 5: Clean up test record
    try:
        from costlens.db import get_backend
        backend = get_backend()
        sql = backend.adapt_sql("DELETE FROM bailian_usage_records WHERE key_alias = ?")
        with backend.connect() as conn:
            conn.execute(sql, ("__diag__",))
            conn.commit()
        results["steps"].append({"step": "cleanup", "status": "ok"})
    except Exception as exc:
        results["steps"].append({"step": "cleanup", "status": "error", "error": str(exc)})

    # Step 6: Check total usage records
    try:
        from costlens.db import get_backend
        backend = get_backend()
        sql = "SELECT COUNT(*) as cnt FROM bailian_usage_records"
        with backend.connect() as conn:
            row = conn.execute(sql).fetchone()
            total = row["cnt"] if row else 0
        results["steps"].append({"step": "total_records", "status": "ok", "count": total})
    except Exception as exc:
        results["steps"].append({"step": "total_records", "status": "error", "error": str(exc)})

    results["overall"] = "ok"
    return results
