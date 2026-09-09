#!/usr/bin/env python3
"""检查阿里云 API 分页和完整数据"""

import asyncio
from alibabacloud_bssopenapi20171214.client import Client
from alibabacloud_tea_openapi.models import Config
from alibabacloud_bssopenapi20171214.models import QueryAccountBillRequest
from costlens.config import get_settings

async def debug_alibaba_pagination():
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
    print(f"查询阿里云 {billing_cycle} 完整账单（检查分页）")
    print(f"=" * 80)
    
    # 第一页
    request = QueryAccountBillRequest(
        billing_cycle=billing_cycle,
        is_group_by_product=True,
        granularity="MONTHLY",
    )
    
    response = client.query_account_bill(request)
    body = response.body
    
    print(f"\nAPI 响应信息:")
    print(f"  success: {body.success}")
    print(f"  account_id: {body.data.account_id if body.data else 'N/A'}")
    
    if body.data:
        print(f"\n  items 总数: {len(body.data.items.item) if body.data.items else 0}")
        
        # 检查是否有分页信息
        if hasattr(body.data, 'page_num'):
            print(f"  page_num: {body.data.page_num}")
        if hasattr(body.data, 'page_size'):
            print(f"  page_size: {body.data.page_size}")
        if hasattr(body.data, 'total_count'):
            print(f"  total_count: {body.data.total_count}")
    
    if body.data and body.data.items and body.data.items.item:
        total = 0
        print(f"\n返回的 {len(body.data.items.item)} 条产品:")
        for i, item in enumerate(body.data.items.item, 1):
            product_name = item.product_name or item.product_code or "Unknown"
            cost = float(item.pretax_amount or 0)
            print(f"{i:3d}. {product_name:40s} {cost:12.2f} CNY")
            total += cost
        
        print(f"\n当前页总计: {total:,.2f} CNY")
        
        # 尝试获取第二页
        print(f"\n" + "=" * 80)
        print(f"尝试获取第二页...")
        print(f"=" * 80)
        
        request2 = QueryAccountBillRequest(
            billing_cycle=billing_cycle,
            is_group_by_product=True,
            granularity="MONTHLY",
            page_num=2,
            page_size=100,  # 增大每页数量
        )
        
        response2 = client.query_account_bill(request2)
        body2 = response2.body
        
        if body2.data and body2.data.items and body2.data.items.item:
            total2 = 0
            print(f"\n第二页返回 {len(body2.data.items.item)} 条产品:")
            for i, item in enumerate(body2.data.items.item, 1):
                product_name = item.product_name or item.product_code or "Unknown"
                cost = float(item.pretax_amount or 0)
                print(f"{i:3d}. {product_name:40s} {cost:12.2f} CNY")
                total2 += cost
            print(f"\n第二页总计: {total2:,.2f} CNY")
            print(f"\n两页合计: {total + total2:,.2f} CNY")
        else:
            print("第二页没有数据")

if __name__ == "__main__":
    asyncio.run(debug_alibaba_pagination())
