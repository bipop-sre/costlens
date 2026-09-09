# Read the alibaba.py file
with open('costlens/cloud/alibaba.py', 'r') as f:
    content = f.read()

# Find the get_cost_data method and modify it to aggregate records before returning
old_code = '''    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "monthly",
    ) -> list[CostRecord]:
        """Fetch cost data via QueryAccountBill API with full pagination."""
        settings = get_settings()
        client = self._get_client()
        billing_months = self._get_billing_months(start_date, end_date)
        records = []

        logger.info("阿里云: 开始查询 %s 到 %s 的成本数据", start_date, end_date)
        logger.info("阿里云: 使用 AK=%s...", settings.alibaba_cloud_access_key_id[:6] if settings.alibaba_cloud_access_key_id else "NOT SET")

        for month in billing_months:
            try:
                logger.info("阿里云: 正在查询 %s 的账单 (分页模式)", month)
                all_items, account_id = self._fetch_all_items(client, month, "MONTHLY")

                if account_id and not self._account_id:
                    self._account_id = account_id

                if all_items:
                    logger.info("阿里云: %s 共获取 %d 条产品数据", month, len(all_items))
                    for item in all_items:
                        cost = float(item.pretax_amount or 0)
                        product = item.product_name or item.product_code or "Unknown"
                        logger.info("  - %s: %.2f CNY", product, cost)
                        if cost > 0:
                            records.append(CostRecord(
                                provider=self.provider,
                                account_id=account_id or self._account_id or "default",
                                service_name=item.product_name or item.product_code or "Unknown",
                                region="",
                                cost=cost,
                                currency=item.currency or "CNY",
                                date=date.fromisoformat(month + "-01"),
                                granularity=Granularity.MONTHLY,
                                tags={
                                    "product_code": item.product_code or "",
                                    "subscription_type": item.subscription_type or "",
                                    "biz_type": item.biz_type or "",
                                },
                            ))'''

new_code = '''    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "monthly",
    ) -> list[CostRecord]:
        """Fetch cost data via QueryAccountBill API with full pagination."""
        settings = get_settings()
        client = self._get_client()
        billing_months = self._get_billing_months(start_date, end_date)
        records = []

        logger.info("阿里云: 开始查询 %s 到 %s 的成本数据", start_date, end_date)
        logger.info("阿里云: 使用 AK=%s...", settings.alibaba_cloud_access_key_id[:6] if settings.alibaba_cloud_access_key_id else "NOT SET")

        for month in billing_months:
            try:
                logger.info("阿里云: 正在查询 %s 的账单 (分页模式)", month)
                all_items, account_id = self._fetch_all_items(client, month, "MONTHLY")

                if account_id and not self._account_id:
                    self._account_id = account_id

                if all_items:
                    logger.info("阿里云: %s 共获取 %d 条产品数据", month, len(all_items))
                    # Aggregate by unique key before creating records
                    from collections import defaultdict
                    aggregated = defaultdict(lambda: {"cost": 0.0, "currency": "CNY", "tags": {}})
                    for item in all_items:
                        cost = float(item.pretax_amount or 0)
                        if cost > 0:
                            service_name = item.product_name or item.product_code or "Unknown"
                            subscription_type = item.subscription_type or ""
                            key = (service_name, subscription_type)
                            aggregated[key]["cost"] += cost
                            aggregated[key]["currency"] = item.currency or "CNY"
                            aggregated[key]["tags"] = {
                                "product_code": item.product_code or "",
                                "subscription_type": subscription_type,
                                "biz_type": item.biz_type or "",
                            }
                    
                    for (service_name, subscription_type), data in aggregated.items():
                        records.append(CostRecord(
                            provider=self.provider,
                            account_id=account_id or self._account_id or "default",
                            service_name=service_name,
                            region="",
                            cost=data["cost"],
                            currency=data["currency"],
                            date=date.fromisoformat(month + "-01"),
                            granularity=Granularity.MONTHLY,
                            tags=data["tags"],
                        ))'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('costlens/cloud/alibaba.py', 'w') as f:
        f.write(content)
    print("Successfully updated alibaba.py")
else:
    print("Could not find the code to replace")
