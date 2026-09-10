#!/usr/bin/env python3
"""Migrate data from SQLite to OceanBase (MySQL-compatible)."""

import json
import sqlite3
import sys
from pathlib import Path

def migrate(sqlite_path: str = "costlens.db"):
    """Migrate all data from SQLite to OceanBase."""
    import pymysql
    from costlens.config import get_settings
    
    settings = get_settings()
    
    print(f"Reading from SQLite: {sqlite_path}")
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    
    print(f"Connecting to OceanBase: {settings.oceanbase_host}:{settings.oceanbase_port}/{settings.oceanbase_database}")
    
    # First create the database if it doesn't exist
    admin_conn = pymysql.connect(
        host=settings.oceanbase_host,
        port=settings.oceanbase_port,
        user=settings.oceanbase_user,
        password=settings.oceanbase_password,
        charset='utf8mb4',
    )
    admin_cur = admin_conn.cursor()
    admin_cur.execute(f"CREATE DATABASE IF NOT EXISTS `{settings.oceanbase_database}` DEFAULT CHARACTER SET utf8mb4")
    admin_conn.commit()
    admin_conn.close()
    
    ob_conn = pymysql.connect(
        host=settings.oceanbase_host,
        port=settings.oceanbase_port,
        user=settings.oceanbase_user,
        password=settings.oceanbase_password,
        database=settings.oceanbase_database,
        charset='utf8mb4',
        autocommit=False,
    )
    ob_cur = ob_conn.cursor()
    
    # Initialize schema
    from costlens.db import OCEANBASE_SCHEMA
    for stmt in OCEANBASE_SCHEMA.strip().split(';'):
        stmt = stmt.strip()
        if stmt:
            try:
                ob_cur.execute(stmt)
            except Exception as e:
                if 'Duplicate' not in str(e) and 'already exists' not in str(e).lower():
                    print(f"  Schema warning: {e}")
    ob_conn.commit()
    print("OceanBase schema initialized")
    
    # Migrate each table
    tables = {
        "cost_records": [
            "provider", "account_id", "service_name", "region", "cost", "currency",
            "usage_amount", "usage_unit", "tags", "record_date", "granularity", "subscription_type"
        ],
        "alerts": [
            "alert_type", "severity", "title", "message", "provider",
            "current_value", "threshold_value", "currency", "resource_id",
            "details", "acknowledged", "notified", "timestamp"
        ],
        "recommendations": [
            "rec_type", "priority", "title", "description", "provider",
            "service_name", "region", "resource_id", "current_cost",
            "estimated_saving", "estimated_saving_pct", "currency",
            "effort", "impact", "details", "action_items", "applied", "created_at"
        ],
        "budgets": [
            "name", "amount", "currency", "period", "provider",
            "service_name", "tags", "alert_thresholds", "start_date",
            "created_at", "updated_at"
        ],
        "analysis_runs": [
            "start_date", "end_date", "total_cost", "alert_count",
            "recommendation_count", "total_savings", "status",
            "error_message", "result_json", "created_at"
        ],
        "balance_snapshots": [
            "provider", "available_amount", "credit_amount", "credit_balance",
            "owe_amount", "currency", "raw_data", "snapshot_at"
        ],
        "monthly_cost_snapshots": [
            "year", "month", "provider", "total_cost", "currency",
            "service_breakdown", "daily_avg", "record_count", "snapshot_at"
        ],
    }
    
    total_migrated = 0
    
    for table, columns in tables.items():
        # Check if table exists in SQLite
        try:
            sqlite_cur = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}")
            count = sqlite_cur.fetchone()[0]
        except sqlite3.OperationalError:
            print(f"  Skipping {table} (not found in SQLite)")
            continue
        
        if count == 0:
            print(f"  {table}: 0 rows (empty)")
            continue
        
        print(f"  Migrating {table}: {count} rows...", end=" ")
        
        # Read from SQLite
        rows = sqlite_conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
        
        # Build INSERT ... ON DUPLICATE KEY UPDATE for OceanBase
        cols_str = ", ".join(f"`{c}`" for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        
        # For tables with unique keys, use ON DUPLICATE KEY UPDATE
        if table == "cost_records":
            update_cols = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in ["cost", "usage_amount", "tags"])
            insert_sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_cols}"
        elif table == "monthly_cost_snapshots":
            update_cols = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in ["total_cost", "currency", "service_breakdown", "daily_avg", "record_count"])
            insert_sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_cols}"
        elif table == "budgets":
            insert_sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE `amount`=VALUES(`amount`)"
        else:
            insert_sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"
        
        # Batch insert
        batch_size = 500
        inserted = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            batch_data = [tuple(row) for row in batch]
            ob_cur.executemany(insert_sql, batch_data)
            ob_conn.commit()
            inserted += len(batch)
        
        print(f"{inserted} rows migrated")
        total_migrated += inserted
    
    # Close connections
    sqlite_conn.close()
    ob_conn.close()
    
    print(f"\nMigration complete! Total rows migrated: {total_migrated}")
    print("You can now set DB_TYPE=oceanbase in .env to use OceanBase.")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "costlens.db"
    migrate(db_path)
