"""Proactive cost inspection and alert notification system.

Runs periodic analysis after billing sync and automatically pushes
alerts and reports to WeChat Work.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from costlens.config import Settings, get_settings
from costlens.db import get_backend
from costlens.models.alert import Alert, AlertSeverity, AlertType

logger = logging.getLogger(__name__)

PROVIDER_NAMES = {
    "alibaba": "阿里云",
    "tencent": "腾讯云",
}


def _adapt(sql: str) -> str:
    return get_backend().adapt_sql(sql)


class ProactiveInspector:
    """Proactively analyze cost data and push notifications."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._last_inspection: Optional[datetime] = None
        self._last_daily_report: Optional[date] = None
        self._last_weekly_report: Optional[date] = None
        self._notified_today: set[tuple[str, str, str]] = set()
        self._notified_date: Optional[date] = None

    async def inspect_after_sync(self, broadcast_fn) -> dict:
        """Run inspection after billing sync completes."""
        now = datetime.now()
        today = date.today()
        # Reset daily dedup set if new day
        if self._notified_date != today:
            self._notified_today.clear()
            self._notified_date = today
        results = {
            "alerts_created": 0,
            "alerts_notified": 0,
            "daily_report_sent": False,
            "weekly_report_sent": False,
        }

        # 1. Detect and notify critical anomalies (DISABLED)
        # Anomaly alerts temporarily disabled; daily/weekly reports remain active.

        # 2. Daily cost report (once per day, after 9 AM)
        today = date.today()
        if (self._last_daily_report != today and now.hour >= 9 and 
            now.hour <= 10):
            try:
                report = self._generate_daily_report()
                if report:
                    await broadcast_fn(report)
                    results["daily_report_sent"] = True
                    self._last_daily_report = today
                    logger.info("Daily report sent")
            except Exception as exc:
                logger.error("Failed to send daily report: %s", exc)

        # 3. Weekly cost report (every Monday, 9-10 AM)
        if (today.weekday() == 0 and
            self._last_weekly_report != today and 
            now.hour >= 9 and now.hour <= 10):
            try:
                report = self._generate_weekly_report()
                if report:
                    await broadcast_fn(report)
                    results["weekly_report_sent"] = True
                    self._last_weekly_report = today
                    logger.info("Weekly report sent")
            except Exception as exc:
                logger.error("Failed to send weekly report: %s", exc)

        self._last_inspection = now
        return results

    def _detect_anomalies(self) -> list[Alert]:
        """Detect cost anomalies from recent data."""
        from costlens.analysis.anomaly import AnomalyDetector
        from costlens.storage import get_storage
        
        storage = get_storage()
        detector = AnomalyDetector(threshold_sigma=3.0, spike_threshold_pct=50.0)
        
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        
        alerts = []
        for provider in ["alibaba", "tencent"]:
            records = storage.get_cost_records(
                start_date=start_date,
                end_date=end_date,
                provider=provider,
            )
            if records:
                provider_alerts = detector.detect_anomalies(records, provider)
                today_str = end_date.isoformat()
                for alert in provider_alerts:
                    if today_str in alert.message:
                        # Dedup: skip if we already notified this provider+service today
                        dedup_key = (alert.provider, alert.title, today_str)
                        if dedup_key in self._notified_today:
                            continue
                        self._notified_today.add(dedup_key)
                        alerts.append(alert)
                        storage.save_alert(alert)
        
        return alerts

    def _format_critical_alerts(self, alerts: list[Alert]) -> str:
        """Format critical alerts for WeChat Work message."""
        lines = ["## 🚨 成本异常告警\n"]
        
        for alert in alerts[:5]:
            provider_name = PROVIDER_NAMES.get(alert.provider, alert.provider)
            lines.append(f"**{provider_name}** - {alert.title}")
            lines.append(f"> {alert.message}\n")
        
        return "\n".join(lines)

    def _generate_daily_report(self) -> str:
        """Generate daily cost summary report."""
        backend = get_backend()
        db = backend.raw_connect()
        
        today = date.today()
        yesterday = today - timedelta(days=1)
        
        rows = db.execute(_adapt("""
            SELECT provider, ROUND(SUM(cost), 2) as total
            FROM cost_records
            WHERE record_date = ? AND granularity = 'daily'
            GROUP BY provider
        """), (yesterday.isoformat(),)).fetchall()
        
        if not rows:
            db.close()
            return ""
        
        total_cost = sum(r["total"] for r in rows)
        
        prev_rows = db.execute(_adapt("""
            SELECT provider, ROUND(SUM(cost), 2) as total
            FROM cost_records
            WHERE record_date = ? AND granularity = 'daily'
            GROUP BY provider
        """), ((yesterday - timedelta(days=1)).isoformat(),)).fetchall()
        prev_total = sum(r["total"] for r in prev_rows) if prev_rows else 0
        
        month_start = today.replace(day=1)
        mtd_rows = db.execute(_adapt("""
            SELECT ROUND(SUM(cost), 2) as total
            FROM cost_records
            WHERE record_date >= ? AND record_date <= ? AND granularity = 'daily'
        """), (month_start.isoformat(), yesterday.isoformat())).fetchone()
        mtd_cost = mtd_rows["total"] if mtd_rows else 0
        
        db.close()
        
        lines = [f"## 📊 {today.strftime('%m月%d日')} 成本日报\n"]
        lines.append(f"**昨日总成本**: ¥{total_cost:,.2f}")
        
        if prev_total > 0:
            change_pct = ((total_cost - prev_total) / prev_total * 100)
            change_symbol = "↑" if change_pct > 0 else "↓"
            change_color = "red" if change_pct > 0 else "green"
            lines.append(f"- 日环比: <font color='{change_color}'>{change_symbol} {abs(change_pct):.1f}%</font>")
        
        lines.append(f"\n**本月累计**: ¥{mtd_cost:,.2f}")
        
        lines.append("\n**厂商明细**:")
        for row in rows:
            provider_name = PROVIDER_NAMES.get(row["provider"], row["provider"])
            lines.append(f"- {provider_name}: ¥{row['total']:,.2f}")
        
        return "\n".join(lines)

    def _generate_weekly_report(self) -> str:
        """Generate weekly cost summary report."""
        backend = get_backend()
        db = backend.raw_connect()
        
        today = date.today()
        week_start = today - timedelta(days=7)
        prev_week_start = week_start - timedelta(days=7)
        
        this_week_rows = db.execute(_adapt("""
            SELECT provider, ROUND(SUM(cost), 2) as total
            FROM cost_records
            WHERE record_date >= ? AND record_date < ? AND granularity = 'daily'
            GROUP BY provider
        """), (week_start.isoformat(), today.isoformat())).fetchall()
        this_week_total = sum(r["total"] for r in this_week_rows)
        
        last_week_rows = db.execute(_adapt("""
            SELECT provider, ROUND(SUM(cost), 2) as total
            FROM cost_records
            WHERE record_date >= ? AND record_date < ? AND granularity = 'daily'
            GROUP BY provider
        """), (prev_week_start.isoformat(), week_start.isoformat())).fetchall()
        last_week_total = sum(r["total"] for r in last_week_rows)
        
        top_services = db.execute(_adapt("""
            SELECT service_name, ROUND(SUM(cost), 2) as total
            FROM cost_records
            WHERE record_date >= ? AND record_date < ? AND granularity = 'daily'
            GROUP BY service_name
            ORDER BY total DESC
            LIMIT 5
        """), (week_start.isoformat(), today.isoformat())).fetchall()
        
        db.close()
        
        if this_week_total == 0:
            return ""
        
        lines = [f"## 📈 成本周报 ({week_start.strftime('%m/%d')} - {today.strftime('%m/%d')})\n"]
        lines.append(f"**本周总成本**: ¥{this_week_total:,.2f}")
        
        if last_week_total > 0:
            change_pct = ((this_week_total - last_week_total) / last_week_total * 100)
            change_symbol = "↑" if change_pct > 0 else "↓"
            change_color = "red" if change_pct > 0 else "green"
            lines.append(f"- 周环比: <font color='{change_color}'>{change_symbol} {abs(change_pct):.1f}%</font>")
            lines.append(f"- 上周成本: ¥{last_week_total:,.2f}")
        
        lines.append("\n**厂商分布**:")
        for row in this_week_rows:
            provider_name = PROVIDER_NAMES.get(row["provider"], row["provider"])
            pct = row["total"] / this_week_total * 100
            lines.append(f"- {provider_name}: ¥{row['total']:,.2f} ({pct:.1f}%)")
        
        if top_services:
            lines.append("\n**Top 5 服务**:")
            for i, row in enumerate(top_services, 1):
                lines.append(f"{i}. {row['service_name']}: ¥{row['total']:,.2f}")
        
        return "\n".join(lines)

    @property
    def last_inspection(self) -> Optional[datetime]:
        return self._last_inspection
