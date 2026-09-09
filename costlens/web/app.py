"""FastAPI Web Dashboard for CostLens with Token Authentication."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from costlens.web.auth import verify_token
from costlens.web.budget_routes import router as budget_router

logger = logging.getLogger(__name__)

app = FastAPI(title="CostLens Dashboard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "costlens.db"

PROVIDER_NAMES = {
    "alibaba": "阿里云",
    "tencent": "腾讯云",
}

ENABLED_PROVIDERS = ["alibaba", "tencent"]

# Include budget routes
app.include_router(budget_router)


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _query_month_data(year: int, month: int) -> dict:
    """Smart dedup query for monthly cost data."""
    db = _get_db()
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{month + 1:02d}-01"
    base_where = "WHERE record_date >= ? AND record_date < ?"
    base_params = [start, end]

    check_q = f"SELECT provider, granularity, COUNT(*) FROM cost_records {base_where} GROUP BY provider, granularity"
    cur = db.execute(check_q, base_params)
    provider_grans = {}
    for row in cur.fetchall():
        provider_grans.setdefault(row[0], []).append(row[1])

    providers = {}
    total_cost = 0.0
    all_services = []

    for p, grans in provider_grans.items():
        has_daily = "daily" in grans
        has_monthly = "monthly" in grans

        if has_daily and has_monthly:
            d_row = db.execute(
                f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records {base_where} AND provider=? AND granularity='daily'",
                base_params + [p],
            ).fetchone()
            mo_row = db.execute(
                f"""SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records
                    {base_where} AND provider=? AND granularity='monthly'
                    AND service_name NOT IN (
                        SELECT DISTINCT service_name FROM cost_records {base_where} AND provider=? AND granularity='daily'
                    )""",
                base_params + [p] + base_params + [p],
            ).fetchone()
            cnt = (d_row[0] or 0) + (mo_row[0] or 0)
            cost = round((d_row[1] or 0) + (mo_row[1] or 0), 2)
        elif has_daily:
            row = db.execute(
                f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records {base_where} AND provider=? AND granularity='daily'",
                base_params + [p],
            ).fetchone()
            cnt = row[0] or 0
            cost = row[1] or 0
        else:
            row = db.execute(
                f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records {base_where} AND provider=? AND granularity='monthly'",
                base_params + [p],
            ).fetchone()
            cnt = row[0] or 0
            cost = row[1] or 0

        providers[p] = {"cost": cost, "record_count": cnt}
        total_cost += cost

        # Collect all services for this provider
        if has_daily:
            cur2 = db.execute(
                f"SELECT service_name, ROUND(SUM(cost),2) as cost FROM cost_records {base_where} AND provider=? AND granularity='daily' GROUP BY service_name ORDER BY SUM(cost) DESC",
                base_params + [p],
            )
            for r in cur2.fetchall():
                all_services.append({"service": r[0], "cost": r[1], "provider": p})

        if has_monthly:
            cur3 = db.execute(
                f"""SELECT service_name, ROUND(SUM(cost),2) as cost FROM cost_records
                    {base_where} AND provider=? AND granularity='monthly'
                    AND service_name NOT IN (
                        SELECT DISTINCT service_name FROM cost_records {base_where} AND provider=? AND granularity='daily'
                    )
                    GROUP BY service_name ORDER BY SUM(cost) DESC""",
                base_params + [p] + base_params + [p],
            )
            for r in cur3.fetchall():
                all_services.append({"service": r[0], "cost": r[1], "provider": p})

    all_services.sort(key=lambda x: -x["cost"])
    db.close()

    return {
        "providers": providers,
        "total_cost": round(total_cost, 2),
        "services": all_services,
    }


# ── Auth endpoint ──


@app.get("/api/auth/check")
async def check_auth(authorization: str = Header(None)):
    """Check if token is valid."""
    from costlens.config import get_settings
    settings = get_settings()
    
    if not settings.web_auth_token:
        return {"valid": True, "auth_required": False}
    
    if not authorization:
        return {"valid": False, "auth_required": True}
    
    token = authorization.replace("Bearer ", "")
    if token != settings.web_auth_token:
        return {"valid": False, "auth_required": True}
    
    return {"valid": True, "auth_required": True}


# ── API Endpoints (all protected) ──


@app.get("/api/overview", dependencies=[Depends(verify_token)])
async def get_overview():
    """Dashboard overview: current month summary + last 6 months trend."""
    today = date.today()
    current = _query_month_data(today.year, today.month)

    # Last month for MoM
    if today.month == 1:
        prev_y, prev_m = today.year - 1, 12
    else:
        prev_y, prev_m = today.year, today.month - 1
    prev = _query_month_data(prev_y, prev_m)

    mom_change = None
    if prev["total_cost"] > 0:
        mom_change = round((current["total_cost"] - prev["total_cost"]) / prev["total_cost"] * 100, 1)

    # Last 6 months trend
    trend = []
    for i in range(5, -1, -1):
        d = date(today.year, today.month, 1) - timedelta(days=i * 30)
        y, m = d.year, d.month
        data = _query_month_data(y, m)
        trend.append({
            "year": y,
            "month": m,
            "total_cost": data["total_cost"],
            "providers": {p: v["cost"] for p, v in data["providers"].items()},
        })

    # Top 10 services
    top_services = current["services"][:10]

    return {
        "current_month": {
            "year": today.year,
            "month": today.month,
            "total_cost": current["total_cost"],
            "providers": {
                p: {
                    "name": PROVIDER_NAMES.get(p, p),
                    "cost": v["cost"],
                    "pct": round(v["cost"] / current["total_cost"] * 100, 1) if current["total_cost"] > 0 else 0,
                }
                for p, v in current["providers"].items()
            },
            "service_count": len(current["services"]),
        },
        "mom_change": mom_change,
        "prev_month_cost": prev["total_cost"],
        "trend": trend,
        "top_services": top_services,
    }


@app.get("/api/cost/monthly", dependencies=[Depends(verify_token)])
async def get_monthly_cost(year: int = Query(None), month: int = Query(None)):
    """Get monthly cost data with smart dedup."""
    if year is None or month is None:
        today = date.today()
        year = year or today.year
        month = month or today.month

    data = _query_month_data(year, month)

    # Add MoM comparison
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1
    prev = _query_month_data(prev_y, prev_m)

    # Add YoY comparison
    yoy = _query_month_data(year - 1, month)

    return {
        "year": year,
        "month": month,
        "total_cost": data["total_cost"],
        "providers": {
            p: {
                "name": PROVIDER_NAMES.get(p, p),
                "cost": v["cost"],
                "record_count": v["record_count"],
            }
            for p, v in data["providers"].items()
        },
        "services": data["services"],
        "mom": {
            "year": prev_y,
            "month": prev_m,
            "total_cost": prev["total_cost"],
            "change": round(data["total_cost"] - prev["total_cost"], 2) if prev["total_cost"] > 0 else None,
            "change_pct": round((data["total_cost"] - prev["total_cost"]) / prev["total_cost"] * 100, 1) if prev["total_cost"] > 0 else None,
        },
        "yoy": {
            "year": year - 1,
            "month": month,
            "total_cost": yoy["total_cost"],
            "change": round(data["total_cost"] - yoy["total_cost"], 2) if yoy["total_cost"] > 0 else None,
            "change_pct": round((data["total_cost"] - yoy["total_cost"]) / yoy["total_cost"] * 100, 1) if yoy["total_cost"] > 0 else None,
        },
    }


@app.get("/api/cost/daily", dependencies=[Depends(verify_token)])
async def get_daily_cost(
    year: int = Query(None),
    month: int = Query(None),
    provider: str = Query(None),
):
    """Get daily cost breakdown."""
    if year is None or month is None:
        today = date.today()
        year = year or today.year
        month = month or today.month

    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{month + 1:02d}-01"

    db = _get_db()
    where = "WHERE record_date >= ? AND record_date < ? AND granularity='daily'"
    params = [start, end]
    if provider:
        where += " AND provider=?"
        params.append(provider)

    rows = db.execute(
        f"SELECT record_date, provider, SUM(cost) as daily_cost FROM cost_records {where} GROUP BY record_date, provider ORDER BY record_date, provider",
        params,
    ).fetchall()

    # Group by date
    daily = defaultdict(lambda: {"total": 0, "providers": {}})
    for row in rows:
        d = row[0]
        p = row[1]
        cost = round(row[2], 2)
        daily[d]["total"] = round(daily[d]["total"] + cost, 2)
        daily[d]["providers"][p] = cost

    # Convert to list
    result = []
    for d in sorted(daily.keys()):
        result.append({
            "date": d,
            "total": daily[d]["total"],
            "providers": daily[d]["providers"],
        })

    db.close()
    return {"year": year, "month": month, "daily": result}


@app.get("/api/cost/services", dependencies=[Depends(verify_token)])
async def get_service_costs(
    year: int = Query(None),
    month: int = Query(None),
    provider: str = Query(None),
):
    """Get service-level cost breakdown with MoM comparison."""
    if year is None or month is None:
        today = date.today()
        year = year or today.year
        month = month or today.month

    data = _query_month_data(year, month)

    # Get previous month data for MoM
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1
    prev_data = _query_month_data(prev_y, prev_m)

    # Build lookup dict for previous month services
    prev_services = {}
    for s in prev_data["services"]:
        key = (s["provider"], s["service"])
        prev_services[key] = s["cost"]

    # Add MoM to current services
    for s in data["services"]:
        key = (s["provider"], s["service"])
        prev_cost = prev_services.get(key, 0)
        if prev_cost > 0:
            s["mom_cost"] = prev_cost
            s["mom_change"] = round(s["cost"] - prev_cost, 2)
            s["mom_change_pct"] = round((s["cost"] - prev_cost) / prev_cost * 100, 1)
        else:
            s["mom_cost"] = None
            s["mom_change"] = None
            s["mom_change_pct"] = None

    if provider:
        data["services"] = [s for s in data["services"] if s["provider"] == provider]

    # Group by provider
    by_provider = defaultdict(list)
    for s in data["services"]:
        by_provider[s["provider"]].append(s)

    return {
        "year": year,
        "month": month,
        "prev_month": {"year": prev_y, "month": prev_m},
        "by_provider": {
            p: {
                "name": PROVIDER_NAMES.get(p, p),
                "services": services,
                "total": round(sum(s["cost"] for s in services), 2),
            }
            for p, services in by_provider.items()
        },
    }


@app.get("/api/balance", dependencies=[Depends(verify_token)])
async def get_balance():
    """Get latest balance for each provider."""
    db = _get_db()
    rows = db.execute(
        """SELECT provider, available_amount, credit_amount, credit_balance,
                  owe_amount, currency, snapshot_at
           FROM balance_snapshots
           WHERE snapshot_at IN (
               SELECT MAX(snapshot_at) FROM balance_snapshots GROUP BY provider
           )
           ORDER BY provider"""
    ).fetchall()
    db.close()

    result = []
    for row in rows:
        result.append({
            "provider": row[0],
            "name": PROVIDER_NAMES.get(row[0], row[0]),
            "available_amount": round(row[1] or 0, 2),
            "credit_amount": round(row[2] or 0, 2),
            "credit_balance": round(row[3] or 0, 2),
            "owe_amount": round(row[4] or 0, 2),
            "currency": row[5] or "CNY",
            "updated_at": row[6],
        })
    return {"balance": result}


@app.post("/api/sync", dependencies=[Depends(verify_token)])
async def trigger_sync():
    """Trigger manual billing data sync."""
    try:
        from costlens.scheduler import BillingScheduler
        scheduler = BillingScheduler()
        result = await scheduler.sync_billing_data()
        return {"status": "success", "result": result}
    except Exception as exc:
        logger.error("Manual sync failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/alerts", dependencies=[Depends(verify_token)])
async def get_alerts(limit: int = Query(50), acknowledged: bool = Query(None)):
    """Get recent alerts (only for enabled providers)."""
    db = _get_db()

    # Filter by enabled providers
    provider_filter = "WHERE provider IN ({})".format(",".join("?" * len(ENABLED_PROVIDERS)))
    params = list(ENABLED_PROVIDERS)

    if acknowledged is not None:
        provider_filter += " AND acknowledged = ?"
        params.append(1 if acknowledged else 0)

    rows = db.execute(
        f"""SELECT id, alert_type, severity, title, message, provider,
                   current_value, threshold_value, currency,
                   acknowledged, notified, timestamp
            FROM alerts {provider_filter}
            ORDER BY timestamp DESC LIMIT ?""",
        params + [limit],
    ).fetchall()
    db.close()

    return {
        "alerts": [
            {
                "id": r[0],
                "type": r[1],
                "severity": r[2],
                "title": r[3],
                "message": r[4],
                "provider": r[5],
                "current_value": r[6],
                "threshold_value": r[7],
                "currency": r[8],
                "acknowledged": bool(r[9]),
                "notified": bool(r[10]),
                "timestamp": r[11],
            }
            for r in rows
        ]
    }


@app.post("/api/alerts/{alert_id}/acknowledge", dependencies=[Depends(verify_token)])
async def acknowledge_alert(alert_id: int):
    """Acknowledge an alert."""
    db = _get_db()
    db.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    db.commit()
    db.close()
    return {"status": "ok"}


@app.get("/api/trends", dependencies=[Depends(verify_token)])
async def get_trends(months: int = Query(6)):
    """Get cost trends over last N months."""
    today = date.today()
    trend = []
    for i in range(months - 1, -1, -1):
        d = date(today.year, today.month, 1) - timedelta(days=i * 30)
        y, m = d.year, d.month
        data = _query_month_data(y, m)

        # Daily average
        daily_avg = 0
        import calendar
        days_in_month = calendar.monthrange(y, m)[1]
        if data["total_cost"] > 0:
            daily_avg = round(data["total_cost"] / days_in_month, 2)

        trend.append({
            "year": y,
            "month": m,
            "label": f"{y}-{m:02d}",
            "total_cost": data["total_cost"],
            "daily_avg": daily_avg,
            "providers": {p: v["cost"] for p, v in data["providers"].items()},
            "top_service": data["services"][0] if data["services"] else None,
        })

    # Calculate MoM changes
    for i in range(1, len(trend)):
        prev = trend[i - 1]["total_cost"]
        curr = trend[i]["total_cost"]
        if prev > 0:
            trend[i]["mom_change"] = round((curr - prev) / prev * 100, 1)
        else:
            trend[i]["mom_change"] = None

    return {"trend": trend}


@app.get("/api/sync/status", dependencies=[Depends(verify_token)])
async def get_sync_status():
    """Get sync status information."""
    db = _get_db()

    # Last sync time from cost_records
    last_record = db.execute(
        "SELECT MAX(created_at) FROM cost_records"
    ).fetchone()

    # Record counts
    counts = {}
    for table in ["cost_records", "alerts", "balance_snapshots"]:
        row = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        counts[table] = row[0]

    # Latest balance
    balance = db.execute(
        """SELECT provider, available_amount, snapshot_at
           FROM balance_snapshots
           WHERE snapshot_at IN (
               SELECT MAX(snapshot_at) FROM balance_snapshots GROUP BY provider
           )
           ORDER BY provider"""
    ).fetchall()

    db.close()

    return {
        "last_sync": last_record[0] if last_record else None,
        "record_counts": counts,
        "latest_balance": [
            {"provider": r[0], "name": PROVIDER_NAMES.get(r[0], r[0]), "available": round(r[1] or 0, 2), "updated": r[2]}
            for r in balance
        ],
    }


# ── Serve Dashboard HTML ──


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the dashboard HTML."""
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


def create_app():
    """Factory for creating the FastAPI app."""
    return app
