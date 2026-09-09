#!/usr/bin/env python3
"""获取阿里云所有分页数据"""

import asyncio
from alibabacloud_bssopenapi20171214.client import Client
from alibabacloud_tea_openapi.models import Config
from alibabacloud_bssopenapi20171214.models import QueryAccountBillRequest
from costlens.config import get_settings

async def query_alibaba_all_pages():
    settings = get_settings()
    
    config = Config(
        access_key_id=settings.alibaba_cloud_access_key_id,
        access_key_secret=settings.alibaba_cloud_access_key_secret,
        endpoint="business.aliyuncs.com",
        region_id=settings.alibaba_cloud_region,
    )
    client = Client(config)
    
    billing_cycle = "2026-08"
    
    print(f"=" * 80)
    print(f"查询阿里云 {billing_cycle} 完整账单（所有分页）")
    print(f"=" * 80)
    
    all_items = []
    page_num = 1
    page_size = 100  # 每页 100 条
    
    while True:
        print(f"\n获取第 {page_num} 页...")
        
        request = QueryAccountBillRequest(
            billing_cycle=billing_cycle,
            is_group_by_product=True,
            granularity="MONTHLY",
            page_num=page_num,
            page_size=page_size,
        )
        
        response = client.query_account_bill(request)
        body = response.body
        
        if not body.success:
            print(f"API 调用失败: {body.message}")
            break
        
        if not body.data or not body.data.items or not body.data.items.item:
            print("没有更多数据")
            break
        
        items = body.data.items.item
        all_items.extend(items)
        
        print(f"  获取 {len(items)} 条记录")
        
        # 检查是否还有更多页
        total_count = body.data.total_count
        if len(all_items) >= total_count:
            print(f"\n已获取所有 {total_count} 条记录")
            break
        
        page_num += 1
    
    # 汇总
    print(f"\n" + "=" * 80)
    print(f"汇总所有 {len(all_items)} 条记录")
    print(f"=" * 80)
    
    total = 0
    service_totals = {}
    
    for item in all_items:
        product_name = item.product_name or item.product_code or "Unknown"
        cost = float(item.pretax_amount or 0)
        total += cost
        
        if product_name not in service_totals:
            service_totals[product_name] = 0
        service_totals[product_name] += cost
    
    print(f"\n按服务汇总:")
    for service, cost in sorted(service_totals.items(), key=lambda x: -x[1])[:20]:
        print(f"  {service:40s} {cost:12.2f} CNY")
    
    print(f"\n" + "=" * 80)
    print(f"阿里云 2026-08 总计: {total:,.2f} CNY")
    print(f"=" * 80)
    
    return total

if __name__ == "__main__":
    asyncio.run(query_alibaba_all_pages())
