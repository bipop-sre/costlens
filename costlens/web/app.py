"""FastAPI Web Dashboard for CostLens with Token Authentication."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from costlens.web.auth import verify_token
from costlens.web.budget_routes import router as budget_router
from costlens.bailian.routes import router as bailian_router
from costlens.db import get_backend

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager

_bot_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_service
    from costlens.config import get_settings
    settings = get_settings()

    # Start WeChat bot if configured
    if settings.wechat_work_bot_id and settings.wechat_work_bot_secret:
        try:
            from costlens.wechat_bot import WeChatBotService
            _bot_service = WeChatBotService(settings)
            await _bot_service.start()
            logger.info("WeChat Bot started alongside web server")
        except Exception as exc:
            logger.error("Failed to start WeChat Bot: %s", exc, exc_info=True)
    else:
        logger.info("WeChat Bot not configured (missing BOT_ID/BOT_SECRET)")


    # Auto-register Bailian API keys from config
    bailian_keys = settings.get_bailian_keys()
    if bailian_keys:
        try:
            from costlens.bailian.tracker import get_bailian_tracker
            tracker = get_bailian_tracker()
            for key_cfg in bailian_keys:
                alias = key_cfg.get("alias", "")
                if alias:
                    tracker.add_api_key(
                        key_alias=alias,
                        key_prefix=key_cfg.get("prefix", ""),
                        description=key_cfg.get("description", ""),
                    )
            logger.info("Registered %d Bailian API keys", len(bailian_keys))
        except Exception as exc:
            logger.error("Failed to register Bailian keys: %s", exc)

        # Start Bailian probe for real tracking data
        if settings.openai_api_key and "dashscope" in settings.openai_base_url:
            try:
                from costlens.bailian.probe import start_probe
                start_probe(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.openai_model,
                    key_alias="default",
                    interval_minutes=5,
                )
                logger.info("Bailian probe started (every 5 minutes)")
            except Exception as exc:
                logger.error("Failed to start Bailian probe: %s", exc)
    else:
        logger.info("No Bailian API keys configured")

    yield

    # Stop Bailian probe
    try:
        from costlens.bailian.probe import stop_probe
        await stop_probe()
    except Exception:
        pass

    if _bot_service is not None:
        try:
            await _bot_service.stop()
            logger.info("WeChat Bot stopped")
        except Exception as exc:
            logger.warning("Error stopping bot: %s", exc)


app = FastAPI(title="CostLens Dashboard", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PROVIDER_NAMES = {
    "alibaba": "阿里云",
    "tencent": "腾讯云",
}

ENABLED_PROVIDERS = ["alibaba", "tencent"]

# Include budget routes
app.include_router(budget_router)
app.include_router(bailian_router)


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    from fastapi.responses import PlainTextResponse
    db = _get_db()

    lines = []
    lines.append("# HELP costlens_up Whether the service is up")
    lines.append("# TYPE costlens_up gauge")
    lines.append("costlens_up 1")

    # Record counts
    lines.append("# HELP costlens_records_total Total cost records in database")
    lines.append("# TYPE costlens_records_total gauge")
    try:
        row = db.execute(_adapt("SELECT COUNT(*) FROM cost_records")).fetchone()
        lines.append(f"costlens_records_total {row[0] or 0}")
    except Exception:
        lines.append("costlens_records_total 0")

    # Record counts by provider
    lines.append("# HELP costlens_records_by_provider Cost records per provider")
    lines.append("# TYPE costlens_records_by_provider gauge")
    try:
        rows = db.execute(_adapt("SELECT provider, COUNT(*) FROM cost_records GROUP BY provider")).fetchall()
        for r in rows:
            lines.append(f'costlens_records_by_provider{{provider="{r[0]}"}} {r[1]}')
    except Exception:
        pass

    # Alert counts
    lines.append("# HELP costlens_alerts_total Total alerts by severity")
    lines.append("# TYPE costlens_alerts_total gauge")
    try:
        rows = db.execute(_adapt("SELECT severity, COUNT(*) FROM alerts GROUP BY severity")).fetchall()
        for r in rows:
            lines.append(f'costlens_alerts_total{{severity="{r[0]}"}} {r[1]}')
    except Exception:
        pass

    # Unacknowledged alerts
    lines.append("# HELP costlens_alerts_unacknowledged Unacknowledged alerts count")
    lines.append("# TYPE costlens_alerts_unacknowledged gauge")
    try:
        row = db.execute(_adapt("SELECT COUNT(*) FROM alerts WHERE acknowledged = 0")).fetchone()
        lines.append(f"costlens_alerts_unacknowledged {row[0] or 0}")
    except Exception:
        lines.append("costlens_alerts_unacknowledged 0")

    # Latest balance
    lines.append("# HELP costlens_balance_available Available balance by provider")
    lines.append("# TYPE costlens_balance_available gauge")
    try:
        rows = db.execute(
            """SELECT provider, available_amount FROM balance_snapshots
               WHERE snapshot_at IN (
                   SELECT MAX(snapshot_at) FROM balance_snapshots GROUP BY provider
               )
               ORDER BY provider"""
        ).fetchall()
        for r in rows:
            lines.append(f'costlens_balance_available{{provider="{r[0]}"}} {r[1] or 0:.2f}')
    except Exception:
        pass

    db.close()
    text = "\n".join(lines) + "\n"
    return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    db_ok = True
    try:
        db = _get_db()
        db.execute("SELECT 1")
        db.close()
    except Exception:
        db_ok = False

    status = "healthy" if db_ok else "degraded"
    return {"status": status, "database": "ok" if db_ok else "error"}




def _get_db():
    backend = get_backend()
    return backend.raw_connect()


def _adapt(sql: str) -> str:
    return get_backend().adapt_sql(sql)


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

    check_q = _adapt(f"SELECT provider, granularity, COUNT(*) FROM cost_records {base_where} GROUP BY provider, granularity")
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
                _adapt(f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records {base_where} AND provider=? AND granularity='daily'"),
                base_params + [p],
            ).fetchone()
            mo_row = db.execute(
                _adapt(f"""SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records
                    {base_where} AND provider=? AND granularity='monthly'
                    AND service_name NOT IN (
                        SELECT DISTINCT service_name FROM cost_records {base_where} AND provider=? AND granularity='daily'
                    )"""),
                base_params + [p] + base_params + [p],
            ).fetchone()
            cnt = (d_row[0] or 0) + (mo_row[0] or 0)
            cost = round((d_row[1] or 0) + (mo_row[1] or 0), 2)
        elif has_daily:
            row = db.execute(
                _adapt(f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records {base_where} AND provider=? AND granularity='daily'"),
                base_params + [p],
            ).fetchone()
            cnt = row[0] or 0
            cost = row[1] or 0
        else:
            row = db.execute(
                _adapt(f"SELECT COUNT(*), ROUND(COALESCE(SUM(cost),0),2) FROM cost_records {base_where} AND provider=? AND granularity='monthly'"),
                base_params + [p],
            ).fetchone()
            cnt = row[0] or 0
            cost = row[1] or 0

        providers[p] = {"cost": cost, "record_count": cnt}
        total_cost += cost

        # Collect all services for this provider
        if has_daily:
            cur2 = db.execute(
                _adapt(f"SELECT service_name, ROUND(SUM(cost),2) as cost FROM cost_records {base_where} AND provider=? AND granularity='daily' GROUP BY service_name ORDER BY SUM(cost) DESC"),
                base_params + [p],
            )
            for r in cur2.fetchall():
                all_services.append({"service": r[0], "cost": r[1], "provider": p})

        if has_monthly:
            cur3 = db.execute(
                _adapt(f"""SELECT service_name, ROUND(SUM(cost),2) as cost FROM cost_records
                    {base_where} AND provider=? AND granularity='monthly'
                    AND service_name NOT IN (
                        SELECT DISTINCT service_name FROM cost_records {base_where} AND provider=? AND granularity='daily'
                    )
                    GROUP BY service_name ORDER BY SUM(cost) DESC"""),
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
    if authorization == f"Bearer {settings.web_auth_token}":
        return {"valid": True}
    return {"valid": False}


# ── Dashboard API ──


@app.get("/api/overview", dependencies=[Depends(verify_token)])
async def get_overview():
    """Get cost overview for current month."""
    today = date.today()
    data = _query_month_data(today.year, today.month)

    # Previous month for MoM
    if today.month == 1:
        prev_y, prev_m = today.year - 1, 12
    else:
        prev_y, prev_m = today.year, today.month - 1
    prev_data = _query_month_data(prev_y, prev_m)

    mom_change = None
    if prev_data["total_cost"] > 0:
        mom_change = round(
            (data["total_cost"] - prev_data["total_cost"]) / prev_data["total_cost"] * 100, 1
        )

    # Daily costs for current month
    db = _get_db()
    start = f"{today.year}-{today.month:02d}-01"
    daily_rows = db.execute(
        _adapt("SELECT record_date, ROUND(SUM(cost),2) as total FROM cost_records WHERE record_date >= ? AND granularity='daily' GROUP BY record_date ORDER BY record_date"),
        [start],
    ).fetchall()
    db.close()

    daily_costs = [{"date": r[0], "cost": r[1]} for r in daily_rows]

    return {
        "total_cost": data["total_cost"],
        "providers": {
            p: {**v, "name": PROVIDER_NAMES.get(p, p)}
            for p, v in data["providers"].items()
        },
        "mom_change": mom_change,
        "top_services": data["services"][:10],
        "daily_costs": daily_costs,
    }


@app.get("/api/daily", dependencies=[Depends(verify_token)])
async def get_daily_costs(
    year: int = Query(None),
    month: int = Query(None),
    provider: str = Query(None),
):
    """Get daily cost breakdown."""
    today = date.today()
    y = year or today.year
    m = month or today.month

    start = f"{y}-{m:02d}-01"
    if m == 12:
        end = f"{y + 1}-01-01"
    else:
        end = f"{y}-{m + 1:02d}-01"

    db = _get_db()
    query = "SELECT record_date, provider, ROUND(SUM(cost),2) as total FROM cost_records WHERE record_date >= ? AND record_date < ? AND granularity='daily'"
    params = [start, end]

    if provider:
        query += " AND provider = ?"
        params.append(provider)

    query += " GROUP BY record_date, provider ORDER BY record_date"

    rows = db.execute(_adapt(query), params).fetchall()
    db.close()

    daily = defaultdict(lambda: defaultdict(float))
    for r in rows:
        daily[r[0]][r[1]] = r[2]

    result = []
    for dt, providers in sorted(daily.items()):
        entry = {"date": dt, "total": round(sum(providers.values()), 2)}
        entry.update(providers)
        result.append(entry)

    return {"daily": result}


@app.get("/api/services", dependencies=[Depends(verify_token)])
async def get_services(
    year: int = Query(None),
    month: int = Query(None),
    provider: str = Query(None),
):
    """Get cost breakdown by service with MoM comparison."""
    today = date.today()
    y = year or today.year
    m = month or today.month

    data = _query_month_data(y, m)

    # Get previous month data for comparison
    if m == 1:
        prev_y, prev_m = y - 1, 12
    else:
        prev_y, prev_m = y, m - 1
    prev_data = _query_month_data(prev_y, prev_m)

    # Build previous month service cost map: (provider, service) -> cost
    prev_cost_map = {}
    for s in prev_data["services"]:
        prev_cost_map[(s["provider"], s["service"])] = s["cost"]

    # Add MoM data to each service
    services = []
    for s in data["services"]:
        if provider and s["provider"] != provider:
            continue
        prev_cost = prev_cost_map.get((s["provider"], s["service"]))
        service_entry = {
            "service": s["service"],
            "cost": s["cost"],
            "provider": s["provider"],
            "mom_cost": prev_cost if prev_cost is not None else None,
        }
        if prev_cost is not None and prev_cost > 0:
            service_entry["mom_change"] = round(s["cost"] - prev_cost, 2)
            service_entry["mom_change_pct"] = round((s["cost"] - prev_cost) / prev_cost * 100, 1)
        else:
            service_entry["mom_change"] = None
            service_entry["mom_change_pct"] = None
        services.append(service_entry)

    return {"services": services}


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
        _adapt(f"""SELECT id, alert_type, severity, title, message, provider,
                   current_value, threshold_value, currency,
                   acknowledged, notified, timestamp
            FROM alerts {provider_filter}
            ORDER BY timestamp DESC LIMIT ?"""),
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
    db.execute(_adapt("UPDATE alerts SET acknowledged = 1 WHERE id = ?"), (alert_id,))
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
    return {
        "balance": [
            {
                "provider": r[0],
                "name": PROVIDER_NAMES.get(r[0], r[0]),
                "available_amount": round(r[1] or 0, 2),
                "credit_amount": round(r[2] or 0, 2),
                "credit_balance": round(r[3] or 0, 2),
                "owe_amount": round(r[4] or 0, 2),
                "currency": r[5] or "CNY",
                "updated": r[6],
            }
            for r in rows
        ]
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
