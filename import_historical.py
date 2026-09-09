"""Import historical billing data (May-August 2026) for cost trend analysis."""

import asyncio
import logging
from datetime import date, timedelta
from collections import defaultdict
from costlens.config import get_settings
from costlens.analysis.analyzer import CostAnalyzer
from costlens.storage import get_storage

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


async def import_monthly_data(year: int, month: int):
    """Import billing data for a specific month."""
    settings = get_settings()
    analyzer = CostAnalyzer(settings)
    storage = get_storage()
    
    # Calculate date range for the month
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    end_date = end_date - timedelta(days=1)
    
    # Don't import future data
    if end_date > date.today():
        end_date = date.today()
    
    logger.info(f"Importing data for {year}-{month:02d} ({start_date} to {end_date})")
    
    total_records = 0
    total_cost = 0.0
    
    for provider in settings.get_enabled_providers():
        try:
            connector = await analyzer._get_connector(provider.value)
            records = await connector.get_cost_data(start_date, end_date)
            
            # Save to cost_records table
            count = storage.save_cost_records(records)
            cost = sum(r.cost for r in records)
            
            # Build service breakdown
            service_breakdown = defaultdict(float)
            for record in records:
                service_breakdown[record.service_name] += record.cost
            
            # Save to monthly_cost_snapshots
            daily_avg = cost / max((end_date - start_date).days + 1, 1)
            storage.save_monthly_snapshot(
                year=year,
                month=month,
                provider=provider.value,
                total_cost=cost,
                daily_avg=daily_avg,
                record_count=len(records),
                service_breakdown=dict(service_breakdown),
            )
            
            total_records += len(records)
            total_cost += cost
            
            logger.info(f"  {provider.value}: {len(records)} records, {cost:,.2f} CNY")
            
        except Exception as e:
            logger.error(f"  {provider.value} failed: {e}")
            import traceback
            traceback.print_exc()
    
    await analyzer.close()
    return total_records, total_cost


async def main():
    """Import May, June, July, August 2026 data."""
    logger.info("=" * 60)
    logger.info("Importing historical billing data (May-August 2026)")
    logger.info("=" * 60)
    
    months = [
        (2026, 5),  # May
        (2026, 6),  # June
        (2026, 7),  # July
        (2026, 8),  # August
    ]
    
    grand_total_records = 0
    grand_total_cost = 0.0
    
    for year, month in months:
        records, cost = await import_monthly_data(year, month)
        grand_total_records += records
        grand_total_cost += cost
        logger.info(f"  Month total: {records} records, {cost:,.2f} CNY")
    
    logger.info("=" * 60)
    logger.info(f"Import completed!")
    logger.info(f"  Total records: {grand_total_records}")
    logger.info(f"  Total cost: {grand_total_cost:,.2f} CNY")
    logger.info("=" * 60)
    
    # Show database statistics
    storage = get_storage()
    stats = storage.get_stats()
    logger.info("\nDatabase statistics:")
    for table, count in stats.items():
        logger.info(f"  {table}: {count} records")
    
    # Show monthly breakdown
    logger.info("\nMonthly cost summary:")
    for year, month in months:
        snapshots = storage.get_monthly_snapshots(year, month)
        total = sum(s['total_cost'] for s in snapshots)
        logger.info(f"  {year}-{month:02d}: {total:,.2f} CNY")


if __name__ == "__main__":
    asyncio.run(main())
