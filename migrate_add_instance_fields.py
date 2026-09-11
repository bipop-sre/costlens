"""Migration: Add instance_id and instance_name to cost_records table."""

import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def migrate_oceanbase():
    """Add instance fields to OceanBase cost_records table."""
    from costlens.db import get_backend

    backend = get_backend()
    if backend.db_type != "oceanbase":
        logger.info("Not OceanBase, skipping")
        return

    conn = backend.raw_connect()
    try:
        cursor = conn.cursor()

        # Check if columns already exist
        cursor.execute("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = 'cost_records'
              AND COLUMN_NAME IN ('instance_id', 'instance_name')
        """, (backend._database,))

        existing = [row[0] for row in cursor.fetchall()]

        if 'instance_id' not in existing:
            logger.info("Adding instance_id column...")
            cursor.execute("""
                ALTER TABLE cost_records
                ADD COLUMN instance_id VARCHAR(256) DEFAULT ''
            """)
            logger.info("instance_id column added")
        else:
            logger.info("instance_id column already exists")

        if 'instance_name' not in existing:
            logger.info("Adding instance_name column...")
            cursor.execute("""
                ALTER TABLE cost_records
                ADD COLUMN instance_name VARCHAR(256) DEFAULT ''
            """)
            logger.info("instance_name column added")
        else:
            logger.info("instance_name column already exists")

        # Update unique key to include instance_id
        logger.info("Updating unique key to include instance_id...")
        try:
            cursor.execute("ALTER TABLE cost_records DROP INDEX uk_cost_record")
            cursor.execute("""
                ALTER TABLE cost_records
                ADD UNIQUE KEY uk_cost_record (
                    provider, account_id, service_name, region,
                    record_date, granularity, subscription_type, instance_id
                )
            """)
            logger.info("Unique key updated")
        except Exception as e:
            if 'Duplicate' in str(e):
                logger.info("Unique key already updated")
            else:
                raise

        conn.commit()
        logger.info("Migration completed successfully")

    except Exception as e:
        logger.error("Migration failed: %s", e)
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_sqlite():
    """Add instance fields to SQLite cost_records table."""
    from costlens.db import get_backend

    backend = get_backend()
    if backend.db_type != "sqlite":
        logger.info("Not SQLite, skipping")
        return

    conn = backend.raw_connect()
    try:
        # Check if columns already exist
        cursor = conn.execute("PRAGMA table_info(cost_records)")
        columns = {row['name'] for row in cursor.fetchall()}

        if 'instance_id' not in columns:
            logger.info("Adding instance_id column...")
            conn.execute("ALTER TABLE cost_records ADD COLUMN instance_id TEXT DEFAULT ''")
            logger.info("instance_id column added")
        else:
            logger.info("instance_id column already exists")

        if 'instance_name' not in columns:
            logger.info("Adding instance_name column...")
            conn.execute("ALTER TABLE cost_records ADD COLUMN instance_name TEXT DEFAULT ''")
            logger.info("instance_name column added")
        else:
            logger.info("instance_name column already exists")

        conn.commit()
        logger.info("Migration completed successfully")

    except Exception as e:
        logger.error("Migration failed: %s", e)
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    from costlens.config import get_settings
    settings = get_settings()

    logger.info("Running migration for %s database...", settings.db_type)

    if settings.db_type == "oceanbase":
        migrate_oceanbase()
    else:
        migrate_sqlite()

    logger.info("Migration script completed")
