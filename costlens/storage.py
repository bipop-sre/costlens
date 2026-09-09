"""SQLite persistent storage for CostLens data."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Generator, Optional

from costlens.models.alert import Alert, AlertSeverity, AlertType
from costlens.models.budget import Budget, BudgetPeriod
from costlens.models.cost import CostRecord, CostSummary, Granularity
from costlens.models.recommendation import Priority, Recommendation, RecommendationType

logger = logging.getLogger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    account_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    region TEXT DEFAULT '',
    cost REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    usage_amount REAL DEFAULT 0.0,
    usage_unit TEXT DEFAULT '',
    tags TEXT DEFAULT '{}',
    record_date DATE NOT NULL,
    granularity TEXT DEFAULT 'daily',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, account_id, service_name, region, record_date, granularity)
);

CREATE INDEX IF NOT EXISTS idx_cost_records_date ON cost_records(record_date);
CREATE INDEX IF NOT EXISTS idx_cost_records_provider ON cost_records(provider);
CREATE INDEX IF NOT EXISTS idx_cost_records_service ON cost_records(service_name);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    provider TEXT NOT NULL,
    current_value REAL DEFAULT 0.0,
    threshold_value REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'USD',
    resource_id TEXT,
    details TEXT DEFAULT '{}',
    acknowledged INTEGER DEFAULT 0,
    notified INTEGER DEFAULT 0,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON alerts(acknowledged);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rec_type TEXT NOT NULL,
    priority TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    provider TEXT NOT NULL,
    service_name TEXT NOT NULL,
    region TEXT DEFAULT '',
    resource_id TEXT,
    current_cost REAL DEFAULT 0.0,
    estimated_saving REAL DEFAULT 0.0,
    estimated_saving_pct REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'USD',
    effort TEXT DEFAULT 'medium',
    impact TEXT DEFAULT 'medium',
    details TEXT DEFAULT '{}',
    action_items TEXT DEFAULT '[]',
    applied INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_recommendations_priority ON recommendations(priority);
CREATE INDEX IF NOT EXISTS idx_recommendations_created ON recommendations(created_at);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    period TEXT DEFAULT 'monthly',
    provider TEXT,
    service_name TEXT,
    tags TEXT DEFAULT '{}',
    alert_thresholds TEXT DEFAULT '[50.0, 80.0, 100.0]',
    start_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_cost REAL DEFAULT 0.0,
    alert_count INTEGER DEFAULT 0,
    recommendation_count INTEGER DEFAULT 0,
    total_savings REAL DEFAULT 0.0,
    status TEXT DEFAULT 'completed',
    error_message TEXT,
    result_json TEXT DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS balance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    available_amount REAL DEFAULT 0.0,
    credit_amount REAL DEFAULT 0.0,
    credit_balance REAL DEFAULT 0.0,
    owe_amount REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'CNY',
    raw_data TEXT DEFAULT '{}',
    snapshot_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_balance_provider ON balance_snapshots(provider);
CREATE INDEX IF NOT EXISTS idx_balance_snapshot_at ON balance_snapshots(snapshot_at);

CREATE TABLE IF NOT EXISTS monthly_cost_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    provider TEXT NOT NULL,
    total_cost REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'CNY',
    service_breakdown TEXT DEFAULT '{}',
    daily_avg REAL DEFAULT 0.0,
    record_count INTEGER DEFAULT 0,
    snapshot_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(year, month, provider)
);

CREATE INDEX IF NOT EXISTS idx_monthly_cost_period ON monthly_cost_snapshots(year, month);
"""


class Storage:
    """SQLite storage for CostLens data."""

    def __init__(self, db_path: str = "costlens.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connect() as conn:
            conn.executescript(DB_SCHEMA)
            conn.commit()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    # ── Cost Records ──

    def save_cost_records(self, records: list[CostRecord]) -> int:
        """Save cost records, returning count of inserted/updated records."""
        if not records:
            return 0

        with self._connect() as conn:
            count = 0
            for r in records:
                try:
                    # Extract subscription_type from tags
                    subscription_type = r.tags.get('subscription_type', '')
                    conn.execute(
                        """INSERT INTO cost_records
                           (provider, account_id, service_name, region, cost, currency,
                            usage_amount, usage_unit, tags, record_date, granularity, subscription_type)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(provider, account_id, service_name, region, record_date, granularity, subscription_type)
                           DO UPDATE SET cost=excluded.cost, usage_amount=excluded.usage_amount,
                                         tags=excluded.tags""",
                        (
                            r.provider, r.account_id, r.service_name, r.region,
                            r.cost, r.currency, r.usage_amount, r.usage_unit,
                            json.dumps(r.tags), r.date.isoformat(), r.granularity.value,
                            subscription_type,
                        ),
                    )
                    count += 1
                except Exception as e:
                    logger.warning("Failed to save cost record: %s", e)
            conn.commit()
            return count

    def _delete_monthly_records(self, provider: str, start_date: date, end_date: date) -> int:
        """Delete monthly granularity records for a provider in the given date range.
        Used to prevent double-counting when daily data is available.
        """
        with self._connect() as conn:
            cur = conn.execute(
                """DELETE FROM cost_records
                   WHERE provider = ? AND granularity = 'monthly'
                   AND record_date >= ? AND record_date <= ?""",
                (provider, start_date.isoformat(), end_date.isoformat()),
            )
            conn.commit()
            return cur.rowcount


    def get_cost_records(
        self,
        start_date: date,
        end_date: date,
        provider: Optional[str] = None,
        service: Optional[str] = None,
    ) -> list[CostRecord]:
        """Query cost records within date range."""
        query = "SELECT * FROM cost_records WHERE record_date BETWEEN ? AND ?"
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]

        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if service:
            query += " AND service_name = ?"
            params.append(service)

        query += " ORDER BY record_date DESC, cost DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_cost_record(row) for row in rows]

    def get_daily_totals(
        self,
        start_date: date,
        end_date: date,
        provider: Optional[str] = None,
    ) -> dict[str, float]:
        """Get daily cost totals."""
        query = "SELECT record_date, SUM(cost) as total FROM cost_records WHERE record_date BETWEEN ? AND ?"
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]

        if provider:
            query += " AND provider = ?"
            params.append(provider)

        query += " GROUP BY record_date ORDER BY record_date"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return {row["record_date"]: row["total"] for row in rows}

    def get_service_totals(
        self,
        start_date: date,
        end_date: date,
        provider: Optional[str] = None,
    ) -> dict[str, float]:
        """Get cost totals by service."""
        query = """SELECT service_name, SUM(cost) as total
                   FROM cost_records
                   WHERE record_date BETWEEN ? AND ?"""
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]

        if provider:
            query += " AND provider = ?"
            params.append(provider)

        query += " GROUP BY service_name ORDER BY total DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return {row["service_name"]: row["total"] for row in rows}

    # ── Alerts ──

    def save_alerts(self, alerts: list[Alert]) -> int:
        """Save alerts to database."""
        if not alerts:
            return 0

        with self._connect() as conn:
            count = 0
            for a in alerts:
                conn.execute(
                    """INSERT INTO alerts
                       (alert_type, severity, title, message, provider,
                        current_value, threshold_value, currency, resource_id,
                        details, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        a.alert_type.value, a.severity.value, a.title, a.message,
                        a.provider, a.current_value, a.threshold_value, a.currency,
                        a.resource_id, json.dumps(a.details), a.timestamp.isoformat(),
                    ),
                )
                count += 1
            conn.commit()
            return count

    def get_alerts(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        severity: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query alerts with filters."""
        query = "SELECT * FROM alerts WHERE 1=1"
        params: list[Any] = []

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date.isoformat())
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if acknowledged is not None:
            query += " AND acknowledged = ?"
            params.append(1 if acknowledged else 0)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def acknowledge_alert(self, alert_id: int) -> bool:
        """Mark an alert as acknowledged."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_alerts_notified(self, alert_ids: list[int]) -> int:
        """Mark alerts as notified."""
        if not alert_ids:
            return 0
        placeholders = ",".join("?" * len(alert_ids))
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE alerts SET notified = 1 WHERE id IN ({placeholders})",
                alert_ids,
            )
            conn.commit()
            return cursor.rowcount

    def get_unnotified_alerts(self, limit: int = 50) -> list[dict]:
        """Get alerts that haven't been sent as notifications."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE notified = 0 ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ── Recommendations ──

    def save_recommendations(self, recommendations: list[Recommendation]) -> int:
        """Save optimization recommendations."""
        if not recommendations:
            return 0

        with self._connect() as conn:
            count = 0
            for r in recommendations:
                conn.execute(
                    """INSERT INTO recommendations
                       (rec_type, priority, title, description, provider,
                        service_name, region, resource_id, current_cost,
                        estimated_saving, estimated_saving_pct, currency,
                        effort, impact, details, action_items)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        r.rec_type.value, r.priority.value, r.title, r.description,
                        r.provider, r.service_name, r.region, r.resource_id,
                        r.current_cost, r.estimated_saving, r.estimated_saving_pct,
                        r.currency, r.effort, r.impact,
                        json.dumps(r.details), json.dumps(r.action_items),
                    ),
                )
                count += 1
            conn.commit()
            return count

    def get_recommendations(
        self,
        priority: Optional[str] = None,
        applied: Optional[bool] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query recommendations."""
        query = "SELECT * FROM recommendations WHERE 1=1"
        params: list[Any] = []

        if priority:
            query += " AND priority = ?"
            params.append(priority)
        if applied is not None:
            query += " AND applied = ?"
            params.append(1 if applied else 0)

        query += " ORDER BY estimated_saving DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_total_potential_savings(self) -> float:
        """Get total potential savings from unapplied recommendations."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(estimated_saving) as total FROM recommendations WHERE applied = 0"
            ).fetchone()
            return row["total"] or 0.0

    # ── Budgets ──

    def save_budget(self, budget: Budget) -> int:
        """Save or update a budget."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO budgets
                   (name, amount, currency, period, provider, service_name,
                    tags, alert_thresholds, start_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                   amount=excluded.amount, currency=excluded.currency,
                   period=excluded.period, provider=excluded.provider,
                   service_name=excluded.service_name, tags=excluded.tags,
                   alert_thresholds=excluded.alert_thresholds,
                   start_date=excluded.start_date, updated_at=CURRENT_TIMESTAMP""",
                (
                    budget.name, budget.amount, budget.currency, budget.period.value,
                    budget.provider, budget.service_name,
                    json.dumps(budget.tags),
                    json.dumps(budget.alert_thresholds),
                    budget.start_date.isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_budgets(self) -> list[Budget]:
        """Get all budgets."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM budgets ORDER BY name").fetchall()
            return [self._row_to_budget(row) for row in rows]

    def delete_budget(self, name: str) -> bool:
        """Delete a budget by name."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM budgets WHERE name = ?", (name,))
            conn.commit()
            return cursor.rowcount > 0

    # ── Analysis Runs ──

    def save_analysis_run(self, result: dict) -> int:
        """Save an analysis run result."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO analysis_runs
                   (start_date, end_date, total_cost, alert_count,
                    recommendation_count, total_savings, status, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.get("period", {}).get("start", ""),
                    result.get("period", {}).get("end", ""),
                    result.get("total_cost", 0),
                    result.get("alert_count", 0),
                    result.get("recommendation_count", 0),
                    result.get("total_potential_savings", 0),
                    "completed",
                    json.dumps(result, default=str),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_analysis_runs(self, limit: int = 10) -> list[dict]:
        """Get recent analysis runs."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ── Balance Snapshots ──

    def save_balance_record(self, provider: str, balance: dict) -> int:
        """Save a balance snapshot."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO balance_snapshots
                   (provider, available_amount, credit_amount, credit_balance,
                    owe_amount, currency, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    provider,
                    balance.get("available_amount", 0),
                    balance.get("credit_amount", 0),
                    balance.get("credit_balance", 0),
                    balance.get("owe_amount", 0),
                    balance.get("currency", "CNY"),
                    json.dumps(balance, default=str),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_latest_balance(self) -> dict:
        """Get the latest balance for each provider."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT provider, available_amount, credit_amount, credit_balance,
                          owe_amount, currency, snapshot_at
                   FROM balance_snapshots
                   WHERE snapshot_at IN (
                       SELECT MAX(snapshot_at) FROM balance_snapshots GROUP BY provider
                   )
                   ORDER BY provider"""
            ).fetchall()
            return [dict(row) for row in rows]

    # ── Monthly Cost Snapshots ──

    def save_monthly_snapshot(
        self,
        year: int,
        month: int,
        provider: str,
        total_cost: float,
        service_breakdown: dict,
        daily_avg: float,
        record_count: int,
        currency: str = "CNY",
    ) -> int:
        """Save or update a monthly cost snapshot."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO monthly_cost_snapshots
                   (year, month, provider, total_cost, currency,
                    service_breakdown, daily_avg, record_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(year, month, provider) DO UPDATE SET
                   total_cost=excluded.total_cost, currency=excluded.currency,
                   service_breakdown=excluded.service_breakdown,
                   daily_avg=excluded.daily_avg, record_count=excluded.record_count,
                   snapshot_at=CURRENT_TIMESTAMP""",
                (
                    year, month, provider, total_cost, currency,
                    json.dumps(service_breakdown, default=str),
                    daily_avg, record_count,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_monthly_snapshots(self, year: int, month: int) -> list[dict]:
        """Get monthly snapshots for a specific month."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT year, month, provider, total_cost, currency,
                          service_breakdown, daily_avg, record_count, snapshot_at
                   FROM monthly_cost_snapshots
                   WHERE year = ? AND month = ?
                   ORDER BY provider""",
                (year, month),
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data["service_breakdown"] = json.loads(data["service_breakdown"] or "{}")
                result.append(data)
            return result

    def get_monthly_comparison(self, months_back: int = 12) -> list[dict]:
        """Get monthly snapshots for the last N months."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT year, month, provider, total_cost, currency,
                          service_breakdown, daily_avg, record_count
                   FROM monthly_cost_snapshots
                   ORDER BY year DESC, month DESC, provider
                   LIMIT ?""",
                (months_back * 10,),
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data["service_breakdown"] = json.loads(data["service_breakdown"] or "{}")
                result.append(data)
            return result

    # ── Stats ──

    def get_stats(self) -> dict:
        """Get storage statistics."""
        with self._connect() as conn:
            stats = {}
            for table in ["cost_records", "alerts", "recommendations", "budgets", "analysis_runs"]:
                row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
                stats[table] = row["count"]
            return stats

    # ── Helpers ──

    def _row_to_cost_record(self, row: sqlite3.Row) -> CostRecord:
        return CostRecord(
            provider=row["provider"],
            account_id=row["account_id"],
            service_name=row["service_name"],
            region=row["region"] or "",
            cost=row["cost"],
            currency=row["currency"] or "USD",
            usage_amount=row["usage_amount"] or 0.0,
            usage_unit=row["usage_unit"] or "",
            tags=json.loads(row["tags"] or "{}"),
            date=date.fromisoformat(row["record_date"]),
            granularity=Granularity(row["granularity"] or "daily"),
        )

    def _row_to_budget(self, row: sqlite3.Row) -> Budget:
        return Budget(
            name=row["name"],
            amount=row["amount"],
            currency=row["currency"] or "USD",
            period=BudgetPeriod(row["period"] or "monthly"),
            provider=row["provider"],
            service_name=row["service_name"],
            tags=json.loads(row["tags"] or "{}"),
            alert_thresholds=json.loads(row["alert_thresholds"] or "[50.0, 80.0, 100.0]"),
            start_date=date.fromisoformat(row["start_date"]) if row["start_date"] else date.today(),
        )


# Global storage instance
_storage: Storage | None = None


def get_storage(db_path: str = "costlens.db") -> Storage:
    global _storage
    if _storage is None:
        _storage = Storage(db_path)
    return _storage
