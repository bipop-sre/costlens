"""Monthly cost comparison with YoY and MoM analysis."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Optional

from costlens.config import Settings, get_settings
from costlens.db import get_backend

logger = logging.getLogger(__name__)

PROVIDER_NAMES = {
    "alibaba": "阿里云",
    "tencent": "腾讯云",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
}


def _adapt(sql: str) -> str:
    return get_backend().adapt_sql(sql)


def _query_month_data(year: int, month: int) -> dict:
    """Query cost_records with smart dedup for a given month."""
    backend = get_backend()
    db = backend.raw_connect()
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
    all_top = []

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

        # Top services
        if has_daily:
            cur2 = db.execute(
                _adapt(f"SELECT service_name, ROUND(SUM(cost),2) FROM cost_records {base_where} AND provider=? AND granularity='daily' GROUP BY service_name ORDER BY SUM(cost) DESC LIMIT 10"),
                base_params + [p],
            )
            for r in cur2.fetchall():
                all_top.append({"service": r[0], "cost": r[1], "provider": p})

        if has_monthly:
            cur3 = db.execute(
                _adapt(f"""SELECT service_name, ROUND(SUM(cost),2) FROM cost_records
                    {base_where} AND provider=? AND granularity='monthly'
                    AND service_name NOT IN (
                        SELECT DISTINCT service_name FROM cost_records {base_where} AND provider=? AND granularity='daily'
                    )
                    GROUP BY service_name ORDER BY SUM(cost) DESC LIMIT 10"""),
                base_params + [p] + base_params + [p],
            )
            for r in cur3.fetchall():
                all_top.append({"service": r[0], "cost": r[1], "provider": p})

    all_top.sort(key=lambda x: -x["cost"])
    db.close()

    return {
        "providers": providers,
        "total_cost": round(total_cost, 2),
        "top_services": all_top[:10],
    }


class MonthlyComparison:
    """Analyze monthly cost trends with year-over-year and month-over-month comparison."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    async def generate_comparison_report(
        self,
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> str:
        """Generate a monthly comparison report with YoY and MoM analysis."""
        today = date.today()
        if year is None:
            year = today.year
        if month is None:
            month = today.month

        current = _query_month_data(year, month)

        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        prev = _query_month_data(prev_year, prev_month)

        yoy = _query_month_data(year - 1, month)

        lines = []
        lines.append(f"## 📊 {year}年{month}月 成本对比分析\n")
        lines.append(f"### 💰 本月总成本: **{current['total_cost']:,.2f} CNY**\n")

        lines.append("#### 🏢 厂商分布\n")
        for pv in ["alibaba", "tencent"]:
            curr_p = current["providers"].get(pv)
            if not curr_p:
                continue
            cost = curr_p["cost"]
            pct = cost / current["total_cost"] * 100 if current["total_cost"] > 0 else 0
            name = PROVIDER_NAMES.get(pv, pv)

            mom_change = ""
            prev_p = prev["providers"].get(pv)
            if prev_p and prev_p["cost"] > 0:
                change = (cost - prev_p["cost"]) / prev_p["cost"] * 100
                mom_change = f" | 环比 {'+' if change >= 0 else ''}{change:.1f}%"

            lines.append(f"- **{name}**: {cost:,.2f} CNY ({pct:.1f}%){mom_change}")

        lines.append("")

        lines.append("#### 📈 环比分析 (vs 上月)\n")
        if prev["total_cost"] > 0:
            change = current["total_cost"] - prev["total_cost"]
            change_pct = change / prev["total_cost"] * 100
            lines.append(f"- 总成本变化: **{change:+,.2f} CNY** ({change_pct:+.1f}%)")
            lines.append(f"- 上月总成本: {prev['total_cost']:,.2f} CNY")
        else:
            lines.append("- 无上月数据，无法对比")
        lines.append("")

        lines.append("#### 📊 同比分析 (vs 去年同期)\n")
        if yoy["total_cost"] > 0:
            change = current["total_cost"] - yoy["total_cost"]
            change_pct = change / yoy["total_cost"] * 100
            lines.append(f"- 总成本变化: **{change:+,.2f} CNY** ({change_pct:+.1f}%)")
            lines.append(f"- 去年同期总成本: {yoy['total_cost']:,.2f} CNY")
        else:
            lines.append("- 无去年同期数据，无法对比")
        lines.append("")

        if current["top_services"]:
            lines.append("#### 🔝 Top 10 服务\n")
            for i, svc in enumerate(current["top_services"], 1):
                pct = svc["cost"] / current["total_cost"] * 100 if current["total_cost"] > 0 else 0
                lines.append(f"{i}. {svc['service']}: {svc['cost']:,.2f} CNY ({pct:.1f}%)")
            lines.append("")

        return "\n".join(lines)

    async def close(self) -> None:
        pass
