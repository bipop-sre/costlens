#!/usr/bin/env python3
"""查询本月账单（本月1号到今天）"""

import asyncio
from datetime import date, timedelta
from costlens.cloud.alibaba import AlibabaCloudCostConnector
from costlens.cloud.tencent import TencentCloudCostConnector

async def query_this_month():
    # 本月1号到今天
    today = date.today()
    first_day = today.replace(day=1)
    
    print(f"=" * 80)
    print(f"查询时间范围: {first_day} 到 {today}（本月）")
    print(f"=" * 80)
    
    # 阿里云
    print("\n【阿里云 - 本月】")
    print("-" * 80)
    alibaba = AlibabaCloudCostConnector()
    alibaba_records = await alibaba.get_cost_data(first_day, today)
    
    alibaba_total = 0
    alibaba_by_service = {}
    for record in alibaba_records:
        alibaba_total += record.cost
        service = record.service_name
        if service not in alibaba_by_service:
            alibaba_by_service[service] = 0
        alibaba_by_service[service] += record.cost
    
    print(f"\n服务明细 ({len(alibaba_records)} 条记录):")
    for service, cost in sorted(alibaba_by_service.items(), key=lambda x: -x[1]):
        print(f"  {service:40s} {cost:12.2f} CNY")
    print(f"\n阿里云本月总计: {alibaba_total:,.2f} CNY")
    
    # 腾讯云
    print("\n" + "=" * 80)
    print("【腾讯云 - 本月】")
    print("-" * 80)
    tencent = TencentCloudCostConnector()
    tencent_records = await tencent.get_cost_data(first_day, today)
    
    tencent_total = 0
    tencent_by_service = {}
    for record in tencent_records:
        tencent_total += record.cost
        service = record.service_name
        if service not in tencent_by_service:
            tencent_by_service[service] = 0
        tencent_by_service[service] += record.cost
    
    print(f"\n服务明细 ({len(tencent_records)} 条记录):")
    for service, cost in sorted(tencent_by_service.items(), key=lambda x: -x[1]):
        print(f"  {service:40s} {cost:12.2f} CNY")
    print(f"\n腾讯云本月总计: {tencent_total:,.2f} CNY")
    
    # 汇总
    print("\n" + "=" * 80)
    print("【本月汇总】")
    print("=" * 80)
    total = alibaba_total + tencent_total
    print(f"阿里云: {alibaba_total:12,.2f} CNY")
    print(f"腾讯云: {tencent_total:12,.2f} CNY")
    print(f"-" * 40)
    print(f"总计:   {total:12,.2f} CNY")
    print(f"=" * 80)

if __name__ == "__main__":
    asyncio.run(query_this_month())
