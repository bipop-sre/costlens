import asyncio
from datetime import date, timedelta
from costlens.config import get_settings
from costlens.analysis.analyzer import CostAnalyzer
from costlens.storage import Storage

async def backfill_monthly():
    settings = get_settings()
    analyzer = CostAnalyzer(settings)
    storage = Storage()

    # Fetch monthly data for 2026-04 to 2026-08
    start = date(2026, 4, 1)
    end = date(2026, 9, 1)

    print(f"=== 重新拉取月度数据: {start} 到 {end} ===\n")

    for provider in ['alibaba', 'tencent']:
        print(f"--- {provider} ---")
        try:
            connector = await analyzer._get_connector(provider)
            records = await connector.get_cost_data(start, end)
            
            # Count by month
            from collections import defaultdict
            monthly_counts = defaultdict(lambda: {"count": 0, "cost": 0.0})
            for r in records:
                month = r.date.strftime('%Y-%m')
                monthly_counts[month]["count"] += 1
                monthly_counts[month]["cost"] += r.cost
            
            for month in sorted(monthly_counts.keys()):
                data = monthly_counts[month]
                print(f"  {month}: {data['count']} records, {data['cost']:,.2f} CNY")
            
            # Save to database
            count = storage.save_cost_records(records)
            print(f"  总计保存: {count} records\n")
            
        except Exception as e:
            print(f"  ERROR: {e}\n")

    print("=== 月度数据拉取完成 ===")

asyncio.run(backfill_monthly())
