#!/usr/bin/env python3
"""调试阿里云 API 原始响应"""

import asyncio
from datetime import date
from alibabacloud_bssopenapi20171214.client import Client
from alibabacloud_tea_openapi.models import Config
from alibabacloud_bssopenapi20171214.models import QueryAccountBillRequest
from costlens.config import get_settings

async def debug_alibaba_api():
    settings = get_settings()
    
    # 初始化客户端
    config = Config(
        access_key_id=settings.alibaba_cloud_access_key_id,
        access_key_secret=settings.alibaba_cloud_access_key_secret,
        endpoint="business.aliyuncs.com",
        region_id=settings.alibaba_cloud_region,
    )
    client = Client(config)
    
    # 查询2026年8月
    billing_cycle = "2026-08"
    
    print(f"=" * 80)
    print(f"查询阿里云 {billing_cycle} 账单（原始 API 响应）")
    print(f"=" * 80)
    
    request = QueryAccountBillRequest(
        billing_cycle=billing_cycle,
        is_group_by_product=True,
        granularity="MONTHLY",
    )
    
    response = client.query_account_bill(request)
    body = response.body
    
    print(f"\nAPI 调用状态: success={body.success}")
    print(f"账户ID: {body.data.account_id if body.data else 'N/A'}")
    
    if not body.success:
        print(f"错误信息: {body.message}")
        return
    
    if body.data and body.data.items and body.data.items.item:
        print(f"\n返回 {len(body.data.items.item)} 条产品数据:\n")
        
        total = 0
        for i, item in enumerate(body.data.items.item, 1):
            product_name = item.product_name or item.product_code or "Unknown"
            cost = float(item.pretax_amount or 0)
            currency = item.currency or "CNY"
            subscription_type = item.subscription_type or ""
            biz_type = item.biz_type or ""
            
            print(f"{i:3d}. {product_name:40s} {cost:12.2f} {currency}")
            print(f"     订阅类型: {subscription_type}, 业务类型: {biz_type}")
            total += cost
        
        print(f"\n" + "=" * 80)
        print(f"API 返回总计: {total:,.2f} CNY")
        print(f"=" * 80)
    else:
        print("未返回数据")

if __name__ == "__main__":
    asyncio.run(debug_alibaba_api())
