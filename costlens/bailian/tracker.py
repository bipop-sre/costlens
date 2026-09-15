"""Bailian (百炼) token usage tracker.

Tracks per-AK token consumption from DashScope/Bailian API calls.
Supports both direct usage reporting and OpenAI-compatible response parsing.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from costlens.bailian.models import (
    BailianApiKey,
    BailianModelPricing,
    BailianUsageRecord,
    BailianUsageSummary,
)
from costlens.db import get_backend

logger = logging.getLogger(__name__)

# Default pricing for common Bailian models (CNY per million tokens)
DEFAULT_PRICING: dict[str, BailianModelPricing] = {
    "qwen-max": BailianModelPricing(model_name="qwen-max", input_price=20.0, output_price=60.0),
    "qwen-plus": BailianModelPricing(model_name="qwen-plus", input_price=4.0, output_price=12.0),
    "qwen-turbo": BailianModelPricing(model_name="qwen-turbo", input_price=2.0, output_price=6.0),
    "qwen-long": BailianModelPricing(model_name="qwen-long", input_price=0.5, output_price=2.0),
    "qwen-vl-max": BailianModelPricing(model_name="qwen-vl-max", input_price=20.0, output_price=20.0),
    "qwen-vl-plus": BailianModelPricing(model_name="qwen-vl-plus", input_price=8.0, output_price=8.0),
    "qwen-math-plus": BailianModelPricing(model_name="qwen-math-plus", input_price=4.0, output_price=12.0),
    "qwen-coder-plus": BailianModelPricing(model_name="qwen-coder-plus", input_price=4.0, output_price=12.0),
    "qwen2.5-72b-instruct": BailianModelPricing(model_name="qwen2.5-72b-instruct", input_price=4.0, output_price=12.0),
    "text-embedding-v3": BailianModelPricing(model_name="text-embedding-v3", input_price=0.7, output_price=0.0),
    "text-embedding-v2": BailianModelPricing(model_name="text-embedding-v2", input_price=0.7, output_price=0.0),
}

# Database schema for Bailian usage tracking
BAILIAN_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS bailian_api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_alias TEXT NOT NULL UNIQUE,
    key_prefix TEXT DEFAULT '',
    description TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bailian_usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_alias TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    call_count INTEGER DEFAULT 1,
    estimated_cost REAL DEFAULT 0.0,
    usage_date DATE NOT NULL,
    request_id TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(key_alias, model_name, usage_date, request_id)
);

CREATE INDEX IF NOT EXISTS idx_bailian_usage_date ON bailian_usage_records(usage_date);
CREATE INDEX IF NOT EXISTS idx_bailian_usage_key ON bailian_usage_records(key_alias);
CREATE INDEX IF NOT EXISTS idx_bailian_usage_model ON bailian_usage_records(model_name);
CREATE INDEX IF NOT EXISTS idx_bailian_usage_key_date ON bailian_usage_records(key_alias, usage_date);
"""

BAILIAN_SCHEMA_OCEANBASE = """
CREATE TABLE IF NOT EXISTS bailian_api_keys (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    key_alias VARCHAR(128) NOT NULL UNIQUE,
    key_prefix VARCHAR(64) DEFAULT '',
    description VARCHAR(512) DEFAULT '',
    is_active TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS bailian_usage_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    key_alias VARCHAR(128) NOT NULL,
    model_name VARCHAR(256) NOT NULL,
    input_tokens BIGINT DEFAULT 0,
    output_tokens BIGINT DEFAULT 0,
    total_tokens BIGINT DEFAULT 0,
    call_count INT DEFAULT 1,
    estimated_cost DOUBLE DEFAULT 0.0,
    usage_date DATE NOT NULL,
    request_id VARCHAR(256) DEFAULT '',
    metadata_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_bailian_usage (key_alias, model_name, usage_date, request_id),
    INDEX idx_bailian_usage_date (usage_date),
    INDEX idx_bailian_usage_key (key_alias),
    INDEX idx_bailian_usage_model (model_name),
    INDEX idx_bailian_usage_key_date (key_alias, usage_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


class BailianUsageTracker:
    """Track and analyze Bailian/DashScope token usage per API key."""

    def __init__(self) -> None:
        self._backend = get_backend()
        self._pricing: dict[str, BailianModelPricing] = dict(DEFAULT_PRICING)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create Bailian usage tables if they don't exist."""
        try:
            with self._backend.connect() as conn:
                if self._backend.db_type == "oceanbase":
                    for stmt in BAILIAN_SCHEMA_OCEANBASE.strip().split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            try:
                                conn.execute(stmt)
                            except Exception as exc:
                                if "Duplicate" not in str(exc) and "already exists" not in str(exc).lower():
                                    logger.warning("Bailian schema warning: %s", exc)
                else:
                    conn.executescript(BAILIAN_SCHEMA_SQLITE)
                conn.commit()
            logger.info("Bailian usage tables ensured")
        except Exception as exc:
            logger.error("Failed to ensure Bailian tables: %s", exc)

    # ── API Key Management ──

    def add_api_key(self, key_alias: str, key_prefix: str = "", description: str = "") -> None:
        """Register a Bailian API key for tracking."""
        sql = self._backend.adapt_sql(
            """INSERT INTO bailian_api_keys (key_alias, key_prefix, description)
               VALUES (?, ?, ?)
               ON CONFLICT(key_alias) DO UPDATE SET
               key_prefix=excluded.key_prefix, description=excluded.description, is_active=1"""
        )
        with self._backend.connect() as conn:
            conn.execute(sql, (key_alias, key_prefix, description))
            conn.commit()
        logger.info("Bailian API key registered: %s", key_alias)

    def remove_api_key(self, key_alias: str) -> None:
        """Deactivate an API key (soft delete)."""
        sql = self._backend.adapt_sql(
            "UPDATE bailian_api_keys SET is_active = 0 WHERE key_alias = ?"
        )
        with self._backend.connect() as conn:
            conn.execute(sql, (key_alias,))
            conn.commit()

    def list_api_keys(self, active_only: bool = True) -> list[BailianApiKey]:
        """List all registered API keys."""
        sql = "SELECT key_alias, key_prefix, description, is_active, created_at FROM bailian_api_keys"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY created_at"
        with self._backend.connect() as conn:
            rows = conn.execute(sql).fetchall()
            return [
                BailianApiKey(
                    key_alias=row["key_alias"],
                    key_prefix=row["key_prefix"] or "",
                    description=row["description"] or "",
                    is_active=bool(row["is_active"]),
                    created_at=datetime.fromisoformat(str(row["created_at"])) if row["created_at"] else datetime.now(),
                )
                for row in rows
            ]

    # ── Pricing ──

    def set_model_pricing(self, model_name: str, input_price: float, output_price: float) -> None:
        """Set or update pricing for a model (CNY per million tokens)."""
        self._pricing[model_name] = BailianModelPricing(
            model_name=model_name, input_price=input_price, output_price=output_price
        )

    def get_model_pricing(self, model_name: str) -> Optional[BailianModelPricing]:
        """Get pricing for a model, with fuzzy matching."""
        if model_name in self._pricing:
            return self._pricing[model_name]
        for key, pricing in self._pricing.items():
            if key in model_name or model_name in key:
                return pricing
        return None

    def _estimate_cost(self, model_name: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on model pricing."""
        pricing = self.get_model_pricing(model_name)
        if not pricing:
            return 0.0
        input_cost = (input_tokens / 1_000_000) * pricing.input_price
        output_cost = (output_tokens / 1_000_000) * pricing.output_price
        return round(input_cost + output_cost, 6)

    # ── Usage Recording ──

    def record_usage(
        self,
        key_alias: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        usage_date: Optional[date] = None,
        request_id: str = "",
        call_count: int = 1,
        metadata: Optional[dict] = None,
    ) -> BailianUsageRecord:
        """Record token usage from an API call or batch."""
        if usage_date is None:
            usage_date = date.today()
        total_tokens = input_tokens + output_tokens
        estimated_cost = self._estimate_cost(model_name, input_tokens, output_tokens)
        metadata_json = json.dumps(metadata or {}, default=str)

        if not request_id:
            request_id = f"batch-{usage_date.isoformat()}-{model_name}"

        record = BailianUsageRecord(
            key_alias=key_alias,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            call_count=call_count,
            estimated_cost=estimated_cost,
            usage_date=usage_date,
            request_id=request_id,
            metadata_json=metadata_json,
        )

        sql = self._backend.adapt_sql(
            """INSERT INTO bailian_usage_records
               (key_alias, model_name, input_tokens, output_tokens, total_tokens,
                call_count, estimated_cost, usage_date, request_id, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key_alias, model_name, usage_date, request_id) DO UPDATE SET
               input_tokens=input_tokens + excluded.input_tokens,
               output_tokens=output_tokens + excluded.output_tokens,
               total_tokens=total_tokens + excluded.total_tokens,
               call_count=call_count + excluded.call_count,
               estimated_cost=estimated_cost + excluded.estimated_cost,
               metadata_json=excluded.metadata_json"""
        )
        with self._backend.connect() as conn:
            conn.execute(sql, (
                key_alias, model_name, input_tokens, output_tokens, total_tokens,
                call_count, estimated_cost, usage_date.isoformat(), request_id, metadata_json,
            ))
            conn.commit()

        logger.debug(
            "Bailian usage recorded: %s/%s %d+%d tokens, ¥%.4f",
            key_alias, model_name, input_tokens, output_tokens, estimated_cost,
        )
        return record

    def record_from_response(
        self,
        key_alias: str,
        model_name: str,
        response_usage: dict[str, Any],
        usage_date: Optional[date] = None,
        request_id: str = "",
    ) -> Optional[BailianUsageRecord]:
        """Record usage from an OpenAI-compatible API response.

        Handles both DashScope native and OpenAI-compatible response formats.
        """
        if not response_usage:
            return None

        input_tokens = (
            response_usage.get("prompt_tokens")
            or response_usage.get("input_tokens")
            or 0
        )
        output_tokens = (
            response_usage.get("completion_tokens")
            or response_usage.get("output_tokens")
            or 0
        )

        if input_tokens == 0 and output_tokens == 0:
            return None

        return self.record_usage(
            key_alias=key_alias,
            model_name=model_name,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            usage_date=usage_date,
            request_id=request_id,
        )

    # ── Querying ──

    def get_usage_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        key_alias: Optional[str] = None,
    ) -> list[BailianUsageSummary]:
        """Get aggregated usage summary per key."""
        if start_date is None:
            start_date = date.today() - timedelta(days=30)
        if end_date is None:
            end_date = date.today()

        conditions = ["usage_date >= ?", "usage_date <= ?"]
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]
        if key_alias:
            conditions.append("key_alias = ?")
            params.append(key_alias)

        where = " AND ".join(conditions)
        sql = self._backend.adapt_sql(
            f"""SELECT key_alias,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(total_tokens) as total_tokens,
                      SUM(call_count) as total_calls,
                      SUM(estimated_cost) as total_cost
               FROM bailian_usage_records
               WHERE {where}
               GROUP BY key_alias
               ORDER BY total_tokens DESC"""
        )

        with self._backend.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        days = max(1, (end_date - start_date).days)
        results = []
        for row in rows:
            total_tokens = int(row["total_tokens"] or 0)
            total_cost = float(row["total_cost"] or 0)
            results.append(BailianUsageSummary(
                key_alias=row["key_alias"],
                period_start=start_date,
                period_end=end_date,
                total_input_tokens=int(row["total_input"] or 0),
                total_output_tokens=int(row["total_output"] or 0),
                total_tokens=total_tokens,
                total_calls=int(row["total_calls"] or 0),
                total_cost=round(total_cost, 4),
                daily_avg_tokens=round(total_tokens / days, 0),
                daily_avg_cost=round(total_cost / days, 4),
            ))
        return results

    def get_model_breakdown(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        key_alias: Optional[str] = None,
    ) -> list[BailianUsageSummary]:
        """Get usage breakdown by model."""
        if start_date is None:
            start_date = date.today() - timedelta(days=30)
        if end_date is None:
            end_date = date.today()

        conditions = ["usage_date >= ?", "usage_date <= ?"]
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]
        if key_alias:
            conditions.append("key_alias = ?")
            params.append(key_alias)

        where = " AND ".join(conditions)
        sql = self._backend.adapt_sql(
            f"""SELECT key_alias, model_name,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(total_tokens) as total_tokens,
                      SUM(call_count) as total_calls,
                      SUM(estimated_cost) as total_cost
               FROM bailian_usage_records
               WHERE {where}
               GROUP BY key_alias, model_name
               ORDER BY total_tokens DESC"""
        )

        with self._backend.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            BailianUsageSummary(
                key_alias=row["key_alias"],
                model_name=row["model_name"],
                period_start=start_date,
                period_end=end_date,
                total_input_tokens=int(row["total_input"] or 0),
                total_output_tokens=int(row["total_output"] or 0),
                total_tokens=int(row["total_tokens"] or 0),
                total_calls=int(row["total_calls"] or 0),
                total_cost=round(float(row["total_cost"] or 0), 4),
            )
            for row in rows
        ]

    def get_daily_usage(
        self,
        year: int,
        month: int,
        key_alias: Optional[str] = None,
    ) -> list[dict]:
        """Get daily usage data for a specific month."""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        conditions = ["usage_date >= ?", "usage_date <= ?"]
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]
        if key_alias:
            conditions.append("key_alias = ?")
            params.append(key_alias)

        where = " AND ".join(conditions)
        sql = self._backend.adapt_sql(
            f"""SELECT usage_date, key_alias,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(total_tokens) as total_tokens,
                      SUM(call_count) as total_calls,
                      SUM(estimated_cost) as total_cost
               FROM bailian_usage_records
               WHERE {where}
               GROUP BY usage_date, key_alias
               ORDER BY usage_date"""
        )

        with self._backend.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "date": str(row["usage_date"]),
                "key_alias": row["key_alias"],
                "input_tokens": int(row["total_input"] or 0),
                "output_tokens": int(row["total_output"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "calls": int(row["total_calls"] or 0),
                "cost": round(float(row["total_cost"] or 0), 4),
            }
            for row in rows
        ]

    def get_daily_totals(self, year: int, month: int) -> list[dict]:
        """Get daily total usage (aggregated across all keys) for a month."""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        sql = self._backend.adapt_sql(
            """SELECT usage_date,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(total_tokens) as total_tokens,
                      SUM(call_count) as total_calls,
                      SUM(estimated_cost) as total_cost
               FROM bailian_usage_records
               WHERE usage_date >= ? AND usage_date <= ?
               GROUP BY usage_date
               ORDER BY usage_date"""
        )
        with self._backend.connect() as conn:
            rows = conn.execute(sql, (start_date.isoformat(), end_date.isoformat())).fetchall()

        return [
            {
                "date": str(row["usage_date"]),
                "input_tokens": int(row["total_input"] or 0),
                "output_tokens": int(row["total_output"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "calls": int(row["total_calls"] or 0),
                "cost": round(float(row["total_cost"] or 0), 4),
            }
            for row in rows
        ]

    def get_top_models(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Get top models by token consumption."""
        if start_date is None:
            start_date = date.today() - timedelta(days=30)
        if end_date is None:
            end_date = date.today()

        sql = self._backend.adapt_sql(
            """SELECT model_name,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(total_tokens) as total_tokens,
                      SUM(call_count) as total_calls,
                      SUM(estimated_cost) as total_cost
               FROM bailian_usage_records
               WHERE usage_date >= ? AND usage_date <= ?
               GROUP BY model_name
               ORDER BY total_tokens DESC
               LIMIT ?"""
        )
        with self._backend.connect() as conn:
            rows = conn.execute(sql, (start_date.isoformat(), end_date.isoformat(), limit)).fetchall()

        return [
            {
                "model": row["model_name"],
                "input_tokens": int(row["total_input"] or 0),
                "output_tokens": int(row["total_output"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "calls": int(row["total_calls"] or 0),
                "cost": round(float(row["total_cost"] or 0), 4),
            }
            for row in rows
        ]


_tracker: Optional[BailianUsageTracker] = None


def get_bailian_tracker() -> BailianUsageTracker:
    """Get or create the global Bailian usage tracker."""
    global _tracker
    if _tracker is None:
        _tracker = BailianUsageTracker()
    return _tracker
