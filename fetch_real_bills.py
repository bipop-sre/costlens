#!/usr/bin/env python3
"""直接从云厂商 API 拉取实时账单并重新计算总额"""

import asyncio
from datetime import date, timedelta
from costlens.config import get_settings
from costlens.cloud.alibaba import AlibabaCloudCostConnector
from costlens.cloud.tencent import TencentCloudCostConnector

async def fetch_real_bills():
    settings = get_settings()
    
    # 查询最近 30 天
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    
    print(f"=" * 80)
    print(f"查询时间范围: {start_date} 到 {end_date}")
    print(f"=" * 80)
    
    # 阿里云
    print("\n【阿里云账单】")
    print("-" * 80)
    alibaba = AlibabaCloudCostConnector()
    alibaba_records = await alibaba.get_cost_data(start_date, end_date)
    
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
    print(f"\n阿里云总计: {alibaba_total:,.2f} CNY")
    
    # 腾讯云
    print("\n" + "=" * 80)
    print("【腾讯云账单】")
    print("-" * 80)
    tencent = TencentCloudCostConnector()
    tencent_records = await tencent.get_cost_data(start_date, end_date)
    
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
    print(f"\n腾讯云总计: {tencent_total:,.2f} CNY")
    
    # 汇总
    print("\n" + "=" * 80)
    print("【汇总】")
    print("=" * 80)
    total = alibaba_total + tencent_total
    print(f"阿里云: {alibaba_total:12,.2f} CNY")
    print(f"腾讯云: {tencent_total:12,.2f} CNY")
    print(f"-" * 40)
    print(f"总计:   {total:12,.2f} CNY")
    print(f"=" * 80)
    
    return {
        "alibaba_total": alibaba_total,
        "tencent_total": tencent_total,
        "total": total,
        "alibaba_services": alibaba_by_service,
        "tencent_services": tencent_by_service,
    }

if __name__ == "__main__":
    result = asyncio.run(fetch_real_bills())
