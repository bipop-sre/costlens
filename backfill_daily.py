import json, asyncio, time
from datetime import date, timedelta
from collections import defaultdict
from costlens.config import get_settings
from costlens.analysis.analyzer import CostAnalyzer
from costlens.storage import Storage
from costlens.models.cost import CostRecord, Granularity

async def backfill():
    settings = get_settings()
    analyzer = CostAnalyzer(settings)
    storage = Storage()

    months = [(2026, 4), (2026, 5), (2026, 6), (2026, 7), (2026, 8)]

    for year, month in months:
        print(f"\n===== {year}-{month:02d} =====")
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        last_day = (end - timedelta(days=1)).day

        # Alibaba daily
        try:
            ali_conn = await analyzer._get_connector('alibaba')
            client = ali_conn._get_client()
            month_str = f"{year}-{month:02d}"
            all_items, account_id = ali_conn._fetch_daily_items_for_month(
                client, month_str, start, date(year, month, last_day)
            )
            aggregated = defaultdict(lambda: {"cost": 0.0, "currency": "CNY", "tags": {}})
            for item in all_items:
                cost = float(item.pretax_amount or 0)
                if not item.billing_date:
                    continue
                try:
                    record_date = date.fromisoformat(item.billing_date)
                except ValueError:
                    continue
                service = item.product_name or item.product_code or "Unknown"
                sub_type = getattr(item, 'subscription_type', '') or ''
                key = (service, record_date, sub_type)
                aggregated[key]["cost"] += cost
                aggregated[key]["currency"] = item.currency or "CNY"
                aggregated[key]["tags"] = {
                    "product_code": item.product_code or "",
                    "subscription_type": sub_type,
                    "biz_type": getattr(item, 'biz_type', '') or "",
                }
            records = []
            for (service, record_date, sub_type), data in aggregated.items():
                records.append(CostRecord(
                    provider='alibaba', account_id=account_id or ali_conn._account_id or "default",
                    service_name=service, region="", cost=data["cost"],
                    currency=data["currency"], date=record_date,
                    granularity=Granularity.DAILY, tags=data["tags"],
                ))
            storage.save_cost_records(records)
            daily_cost = sum(r.cost for r in records)
            print(f"  [alibaba] daily: {len(records)} records, {daily_cost:,.2f} CNY")
        except Exception as exc:
            print(f"  [alibaba] daily ERROR: {exc}")

        time.sleep(1)

        # Tencent daily
        try:
            tc_conn = await analyzer._get_connector('tencent')
            daily_records = await tc_conn.get_daily_cost_data(year, month, 1, last_day)
            if daily_records:
                storage.save_cost_records(daily_records)
                daily_cost = sum(r.cost for r in daily_records)
                print(f"  [tencent] daily: {len(daily_records)} records, {daily_cost:,.2f} CNY")
        except Exception as exc:
            print(f"  [tencent] daily ERROR: {exc}")

        time.sleep(1)

    print("\n===== BACKFILL COMPLETE =====")

asyncio.run(backfill())
