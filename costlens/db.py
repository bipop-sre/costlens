"""Database abstraction layer supporting SQLite and OceanBase (MySQL-compatible)."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


# ── OceanBase (MySQL) DDL ──

OCEANBASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_records (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    provider VARCHAR(64) NOT NULL,
    account_id VARCHAR(128) NOT NULL,
    service_name VARCHAR(256) NOT NULL,
    region VARCHAR(128) DEFAULT '',
    cost DOUBLE NOT NULL,
    currency VARCHAR(16) DEFAULT 'USD',
    usage_amount DOUBLE DEFAULT 0.0,
    usage_unit VARCHAR(64) DEFAULT '',
    tags TEXT,
    record_date DATE NOT NULL,
    granularity VARCHAR(16) DEFAULT 'daily',
    subscription_type VARCHAR(128) DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_cost_record (provider, account_id, service_name, region, record_date, granularity, subscription_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS alerts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    alert_type VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    title VARCHAR(512) NOT NULL,
    message TEXT NOT NULL,
    provider VARCHAR(64) NOT NULL,
    current_value DOUBLE DEFAULT 0.0,
    threshold_value DOUBLE DEFAULT 0.0,
    currency VARCHAR(16) DEFAULT 'USD',
    resource_id VARCHAR(256) DEFAULT NULL,
    details TEXT,
    acknowledged TINYINT DEFAULT 0,
    notified TINYINT DEFAULT 0,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_alerts_timestamp (timestamp),
    INDEX idx_alerts_severity (severity),
    INDEX idx_alerts_acknowledged (acknowledged)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recommendations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    rec_type VARCHAR(64) NOT NULL,
    priority VARCHAR(32) NOT NULL,
    title VARCHAR(512) NOT NULL,
    description TEXT NOT NULL,
    provider VARCHAR(64) NOT NULL,
    service_name VARCHAR(256) NOT NULL,
    region VARCHAR(128) DEFAULT '',
    resource_id VARCHAR(256) DEFAULT NULL,
    current_cost DOUBLE DEFAULT 0.0,
    estimated_saving DOUBLE DEFAULT 0.0,
    estimated_saving_pct DOUBLE DEFAULT 0.0,
    currency VARCHAR(16) DEFAULT 'USD',
    effort VARCHAR(32) DEFAULT 'medium',
    impact VARCHAR(32) DEFAULT 'medium',
    details TEXT,
    action_items TEXT,
    applied TINYINT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recommendations_priority (priority),
    INDEX idx_recommendations_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS budgets (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(256) NOT NULL UNIQUE,
    amount DOUBLE NOT NULL,
    currency VARCHAR(16) DEFAULT 'USD',
    period VARCHAR(32) DEFAULT 'monthly',
    provider VARCHAR(64) DEFAULT NULL,
    service_name VARCHAR(256) DEFAULT NULL,
    tags TEXT,
    alert_thresholds TEXT,
    start_date DATE DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS analysis_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_cost DOUBLE DEFAULT 0.0,
    alert_count INT DEFAULT 0,
    recommendation_count INT DEFAULT 0,
    total_savings DOUBLE DEFAULT 0.0,
    status VARCHAR(32) DEFAULT 'completed',
    error_message TEXT DEFAULT NULL,
    result_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS balance_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    provider VARCHAR(64) NOT NULL,
    available_amount DOUBLE DEFAULT 0.0,
    credit_amount DOUBLE DEFAULT 0.0,
    credit_balance DOUBLE DEFAULT 0.0,
    owe_amount DOUBLE DEFAULT 0.0,
    currency VARCHAR(16) DEFAULT 'CNY',
    raw_data TEXT,
    snapshot_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_balance_provider (provider),
    INDEX idx_balance_snapshot_at (snapshot_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS monthly_cost_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    year INT NOT NULL,
    month INT NOT NULL,
    provider VARCHAR(64) NOT NULL,
    total_cost DOUBLE DEFAULT 0.0,
    currency VARCHAR(16) DEFAULT 'CNY',
    service_breakdown TEXT,
    daily_avg DOUBLE DEFAULT 0.0,
    record_count INT DEFAULT 0,
    snapshot_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_monthly_cost (year, month, provider),
    INDEX idx_monthly_cost_period (year, month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


class _DictRow:
    """Mimics sqlite3.Row for PyMySQL results."""

    def __init__(self, cursor, row):
        self._desc = [d[0] for d in cursor.description]
        self._data = dict(zip(self._desc, row))

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def keys(self):
        return self._data.keys()

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data.values())


class _MySQLConnectionWrapper:
    """Wraps PyMySQL connection to provide sqlite3-like interface."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=None) -> "_MySQLCursorWrapper":
        cursor = self._conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        return _MySQLCursorWrapper(cursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class _MySQLCursorWrapper:
    """Wraps PyMySQL cursor to return dict-like rows."""

    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _DictRow(self._cursor, row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [_DictRow(self._cursor, row) for row in rows]


def _convert_sql_to_mysql(sql: str) -> str:
    """Convert SQLite SQL to MySQL/OceanBase compatible SQL."""
    # Replace ? placeholders with %s
    sql = sql.replace('?', '%s')

    # Replace ON CONFLICT(...) DO UPDATE SET with ON DUPLICATE KEY UPDATE
    import re
    pattern = r'ON CONFLICT\([^)]+\)\s+DO UPDATE SET'
    sql = re.sub(pattern, 'ON DUPLICATE KEY UPDATE', sql, flags=re.IGNORECASE)

    # Replace excluded.xxx with VALUES(xxx) for MySQL ON DUPLICATE KEY UPDATE
    sql = re.sub(r'excluded\.(\w+)', r'VALUES(\1)', sql)

    # Replace INTEGER PRIMARY KEY AUTOINCREMENT
    sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGINT AUTO_INCREMENT PRIMARY KEY')

    return sql


def _convert_sql_to_sqlite(sql: str) -> str:
    """Ensure SQL is SQLite compatible (no-op for most cases)."""
    return sql


class DatabaseBackend:
    """Unified database backend supporting SQLite and OceanBase."""

    def __init__(self, db_type: str = "sqlite", **kwargs):
        self.db_type = db_type
        self._kwargs = kwargs

        if db_type == "oceanbase":
            self._host = kwargs.get("host", "127.0.0.1")
            self._port = kwargs.get("port", 2881)
            self._user = kwargs.get("user", "root")
            self._password = kwargs.get("password", "")
            self._database = kwargs.get("database", "costlens")
            self._placeholder = "%s"
        else:
            self._db_path = kwargs.get("db_path", "costlens.db")
            self._placeholder = "?"

    @contextmanager
    def connect(self) -> Generator:
        """Context manager yielding a database connection with dict-row access."""
        if self.db_type == "oceanbase":
            import pymysql
            conn = pymysql.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.Cursor,
                autocommit=False,
            )
            wrapper = _MySQLConnectionWrapper(conn)
            try:
                yield wrapper
            finally:
                conn.close()
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
            finally:
                conn.close()

    def raw_connect(self):
        """Get a raw connection (for external use like web app)."""
        if self.db_type == "oceanbase":
            import pymysql
            conn = pymysql.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.Cursor,
                autocommit=False,
            )
            return _MySQLConnectionWrapper(conn)
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            return conn

    def init_schema(self):
        """Initialize database schema."""
        with self.connect() as conn:
            if self.db_type == "oceanbase":
                for statement in OCEANBASE_SCHEMA.strip().split(';'):
                    stmt = statement.strip()
                    if stmt:
                        try:
                            conn.execute(stmt)
                        except Exception as e:
                            if 'Duplicate' not in str(e) and 'already exists' not in str(e).lower():
                                logger.warning("Schema init warning: %s", e)
                conn.commit()
            else:
                from costlens.storage import DB_SCHEMA
                conn.executescript(DB_SCHEMA)
                conn.commit()

    @property
    def placeholder(self) -> str:
        return self._placeholder

    def adapt_sql(self, sql: str) -> str:
        """Adapt SQL for the current backend."""
        if self.db_type == "oceanbase":
            return _convert_sql_to_mysql(sql)
        return sql

    def get_stats(self) -> dict:
        """Get table row counts."""
        stats = {}
        with self.connect() as conn:
            for table in ["cost_records", "alerts", "recommendations", "budgets",
                          "analysis_runs", "balance_snapshots", "monthly_cost_snapshots"]:
                row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
                stats[table] = row["count"]
        return stats


# ── Global backend instance ──

_backend: Optional[DatabaseBackend] = None


def get_backend() -> DatabaseBackend:
    """Get or create the global database backend."""
    global _backend
    if _backend is None:
        from costlens.config import get_settings
        settings = get_settings()
        if settings.db_type == "oceanbase":
            _backend = DatabaseBackend(
                db_type="oceanbase",
                host=settings.oceanbase_host,
                port=settings.oceanbase_port,
                user=settings.oceanbase_user,
                password=settings.oceanbase_password,
                database=settings.oceanbase_database,
            )
            logger.info("Using OceanBase backend: %s:%d/%s",
                       settings.oceanbase_host, settings.oceanbase_port,
                       settings.oceanbase_database)
        else:
            _backend = DatabaseBackend(
                db_type="sqlite",
                db_path=settings.db_path,
            )
            logger.info("Using SQLite backend: %s", settings.db_path)
    return _backend


def reset_backend():
    """Reset the global backend (for testing)."""
    global _backend
    _backend = None
