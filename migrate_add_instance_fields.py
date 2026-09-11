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
        # Add instance_id column (ignore if exists)
        logger.info("Adding instance_id column...")
        try:
            conn.execute("""
                ALTER TABLE cost_records
                ADD COLUMN instance_id VARCHAR(256) DEFAULT ''
            """)
            logger.info("✓ instance_id column added")
        except Exception as e:
            if 'Duplicate column' in str(e) or 'already exists' in str(e).lower():
                logger.info("✓ instance_id column already exists")
            else:
                raise

        # Add instance_name column (ignore if exists)
        logger.info("Adding instance_name column...")
        try:
            conn.execute("""
                ALTER TABLE cost_records
                ADD COLUMN instance_name VARCHAR(256) DEFAULT ''
            """)
            logger.info("✓ instance_name column added")
        except Exception as e:
            if 'Duplicate column' in str(e) or 'already exists' in str(e).lower():
                logger.info("✓ instance_name column already exists")
            else:
                raise

        # Update unique key to include instance_id
        logger.info("Updating unique key to include instance_id...")
        try:
            conn.execute("ALTER TABLE cost_records DROP INDEX uk_cost_record")
            conn.execute("""
                ALTER TABLE cost_records
                ADD UNIQUE KEY uk_cost_record (
                    provider, account_id, service_name, region,
                    record_date, granularity, subscription_type, instance_id
                )
            """)
            logger.info("✓ Unique key updated")
        except Exception as e:
            if 'Duplicate' in str(e) or 'already exists' in str(e).lower():
                logger.info("✓ Unique key already updated")
            else:
                raise

        conn.commit()
        logger.info("✓ Migration completed successfully")

    except Exception as e:
        logger.error("Migration failed: %s", e)
        try:
            conn.rollback()
        except:
            pass
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
            logger.info("✓ instance_id column added")
        else:
            logger.info("✓ instance_id column already exists")

        if 'instance_name' not in columns:
            logger.info("Adding instance_name column...")
            conn.execute("ALTER TABLE cost_records ADD COLUMN instance_name TEXT DEFAULT ''")
            logger.info("✓ instance_name column added")
        else:
            logger.info("✓ instance_name column already exists")

        conn.commit()
        logger.info("✓ Migration completed successfully")

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
