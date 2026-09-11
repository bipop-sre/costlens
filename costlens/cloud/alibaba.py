"""Alibaba Cloud BSS (Billing) connector."""

from __future__ import annotations

import logging
from datetime import date

from costlens.cloud.base import CloudConnector
from costlens.config import Settings, get_settings
from costlens.models.cost import CostRecord, CostSummary, Granularity

logger = logging.getLogger(__name__)


class AlibabaCloudCostConnector(CloudConnector):
    """Alibaba Cloud BSS OpenAPI connector."""

    def __init__(self) -> None:
        self._client = None
        self._account_id: str = ""

    @property
    def provider(self) -> str:
        return "alibaba"

    def _get_client(self):
        if self._client is None:
            from alibabacloud_bssopenapi20171214.client import Client
            from alibabacloud_tea_openapi.models import Config

            settings = get_settings()
            config = Config(
                access_key_id=settings.alibaba_cloud_access_key_id,
                access_key_secret=settings.alibaba_cloud_access_key_secret,
                endpoint="business.aliyuncs.com",
                region_id=settings.alibaba_cloud_region,
            )
            self._client = Client(config)
        return self._client

    def _get_billing_months(self, start_date: date, end_date: date) -> list[str]:
        """Get list of billing months (YYYY-MM) between two dates."""
        months = []
        current = start_date.replace(day=1)
        while current <= end_date:
            months.append(current.strftime("%Y-%m"))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        return months

    def _fetch_all_items(self, client, month: str, granularity_value: str, billing_date: str = None):
        """Fetch all bill items with pagination for a given month and granularity.
        
        For DAILY granularity, billing_date (YYYY-MM-DD) is required.
        """
        from alibabacloud_bssopenapi20171214.models import QueryAccountBillRequest

        all_items = []
        page_num = 1
        page_size = 300
        account_id = ""
        max_pages = 50

        while page_num <= max_pages:
            logger.info("阿里云: 查询 %s (%s) 第 %d 页", month, granularity_value, page_num)
            request_params = {
                "billing_cycle": month,
                "is_group_by_product": True,
                "granularity": granularity_value,
                "page_num": page_num,
                "page_size": page_size,
            }
            if granularity_value == "DAILY" and billing_date:
                request_params["billing_date"] = billing_date
            
            request = QueryAccountBillRequest(**request_params)
            response = client.query_account_bill(request)
            body = response.body

            if not body.success:
                logger.warning("阿里云 API 返回失败: %s (月份: %s, 页: %d)", body.message, month, page_num)
                break

            if not body.data:
                break

            if not account_id and body.data.account_id:
                account_id = body.data.account_id

            if not body.data.items or not body.data.items.item:
                break

            items = body.data.items.item
            all_items.extend(items)
            total_count = body.data.total_count or 0
            logger.info("阿里云: %s 第 %d 页获取 %d 条, 累计 %d/%d", month, page_num, len(items), len(all_items), total_count)

            if len(all_items) >= total_count:
                break

            page_num += 1

        return all_items, account_id

    def _fetch_daily_items_for_month(self, client, month: str, start_date, end_date):
        """Fetch daily granularity data for each day in the specified date range."""
        from datetime import timedelta
        
        all_items = []
        account_id = ""
        current = start_date
        
        while current <= end_date:
            billing_date = current.strftime("%Y-%m-%d")
            logger.info("阿里云: 查询日粒度数据 %s", billing_date)
            
            items, aid = self._fetch_all_items(client, month, "DAILY", billing_date)
            all_items.extend(items)
            
            if aid and not account_id:
                account_id = aid
            
            current += timedelta(days=1)
        
        return all_items, account_id

    async def get_cost_data(
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
                        ))

            except Exception as exc:
                logger.error("Failed to query Alibaba Cloud billing for %s: %s", month, exc)
                continue

        # Also try daily granularity for current month
        if granularity == "daily":
            current_month = date.today().strftime("%Y-%m")
            if current_month in billing_months:
                try:
                    # Fetch daily data for each day in the current month up to today
                    month_start = date.fromisoformat(current_month + "-01")
                    month_end = min(date.today(), end_date)
                    
                    daily_items, account_id = self._fetch_daily_items_for_month(
                        client, current_month, month_start, month_end
                    )

                    if daily_items:
                        daily_records = []
                        for item in daily_items:
                            cost = float(item.pretax_amount or 0)
                            if cost > 0 and item.billing_date:
                                try:
                                    record_date = date.fromisoformat(item.billing_date)
                                except ValueError:
                                    continue
                                daily_records.append(CostRecord(
                                    provider=self.provider,
                                    account_id=account_id or self._account_id or "default",
                                    service_name=item.product_name or item.product_code or "Unknown",
                                    region="",
                                    cost=cost,
                                    currency=item.currency or "CNY",
                                    date=record_date,
                                    granularity=Granularity.DAILY,
                                ))
                        # Replace monthly records for current month with daily ones
                        records = [
                            r for r in records
                            if not (r.date.strftime("%Y-%m") == current_month)
                        ]
                        records.extend(daily_records)

                except Exception as exc:
                    logger.warning("Failed to get daily data for %s: %s", current_month, exc)

        # Filter by date range
        records = [r for r in records if start_date <= r.date <= end_date]
        return records

    async def get_cost_summary(
        self,
        start_date: date,
        end_date: date,
    ) -> CostSummary:
        records = await self.get_cost_data(start_date, end_date)
        total_cost = sum(r.cost for r in records)
        service_breakdown: dict[str, float] = {}
        region_breakdown: dict[str, float] = {}
        for record in records:
            service_breakdown[record.service_name] = (
                service_breakdown.get(record.service_name, 0) + record.cost
            )
            if record.region:
                region_breakdown[record.region] = (
                    region_breakdown.get(record.region, 0) + record.cost
                )
        return CostSummary(
            provider=self.provider,
            account_id=self._account_id or "default",
            total_cost=total_cost,
            currency="CNY",
            period_start=start_date,
            period_end=end_date,
            service_breakdown=dict(sorted(service_breakdown.items(), key=lambda x: -x[1])),
            region_breakdown=dict(sorted(region_breakdown.items(), key=lambda x: -x[1])),
            daily_costs=records,
        )

    async def get_service_breakdown(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[str, float]:
        summary = await self.get_cost_summary(start_date, end_date)
        return summary.service_breakdown

    async def list_accounts(self) -> list[dict]:
        return [{"id": self._account_id or "default", "name": "Alibaba Cloud Account"}]

    async def get_account_balance(self) -> dict:
        """Query Alibaba Cloud account balance and credit."""
        client = self._get_client()
        try:
            response = client.query_account_balance()
            body = response.body
            
            if not body.success:
                logger.warning("Alibaba balance query failed: %s", body.message)
                return {"provider": self.provider, "error": body.message}
            
            data = body.data
            return {
                "provider": self.provider,
                "available_amount": float(data.available_amount.replace(",", "") or 0),
                "available_cash_amount": float(data.available_cash_amount.replace(",", "") or 0),
                "credit_amount": float(data.credit_amount.replace(",", "") or 0),
                "mybank_credit_amount": float(data.mybank_credit_amount.replace(",", "") or 0),
                "currency": data.currency or "CNY",
            }
        except Exception as exc:
            logger.error("Failed to query Alibaba balance: %s", exc)
            return {"provider": self.provider, "error": str(exc)}



    def _fetch_instance_items(self, client, month: str, granularity_value: str, billing_date: str = None):
        """Fetch instance-level bill items with pagination.
        
        Uses QueryInstanceBill API to get resource-level billing data.
        For DAILY granularity, billing_date (YYYY-MM-DD) is required.
        """
        from alibabacloud_bssopenapi20171214.models import QueryInstanceBillRequest

        all_items = []
        page_num = 1
        page_size = 300
        account_id = ""
        max_pages = 50

        while page_num <= max_pages:
            logger.info("阿里云: 查询实例级账单 %s (%s) 第 %d 页", month, granularity_value, page_num)
            request_params = {
                "billing_cycle": month,
                "granularity": granularity_value,
                "page_num": page_num,
                "page_size": page_size,
            }
            if granularity_value == "DAILY" and billing_date:
                request_params["billing_date"] = billing_date
            
            request = QueryInstanceBillRequest(**request_params)
            response = client.query_instance_bill(request)
            body = response.body

            if not body.success:
                logger.warning("阿里云实例级 API 返回失败: %s (月份: %s, 页: %d)", body.message, month, page_num)
                break

            if not body.data:
                break

            if not account_id and body.data.account_id:
                account_id = body.data.account_id

            if not body.data.items or not body.data.items.item:
                break

            items = body.data.items.item
            all_items.extend(items)
            total_count = body.data.total_count or 0
            logger.info("阿里云实例级: %s 第 %d 页获取 %d 条, 累计 %d/%d", month, page_num, len(items), len(all_items), total_count)

            if len(all_items) >= total_count:
                break

            page_num += 1

        return all_items, account_id

    def _fetch_daily_instance_items_for_month(self, client, month: str, start_date, end_date):
        """Fetch daily instance-level data for each day in the specified date range."""
        from datetime import timedelta
        
        all_items = []
        account_id = ""
        current = start_date
        
        while current <= end_date:
            billing_date = current.strftime("%Y-%m-%d")
            logger.info("阿里云: 查询日粒度实例级数据 %s", billing_date)
            
            items, aid = self._fetch_instance_items(client, month, "DAILY", billing_date)
            all_items.extend(items)
            
            if aid and not account_id:
                account_id = aid
            
            current += timedelta(days=1)
        
        return all_items, account_id

    async def get_daily_cost_data(
        self, year: int, month: int, start_day: int = 1, end_day: int = 31
    ) -> list[CostRecord]:
        """获取阿里云日粒度账单数据（实例级）
        
        Args:
            year: 年份
            month: 月份 (1-12)
            start_day: 开始日期
            end_day: 结束日期
            
        Returns:
            CostRecord 列表，每条记录代表一天某实例的成本
        """
        from datetime import date, timedelta
        from collections import defaultdict
        
        settings = get_settings()
        client = self._get_client()
        month_str = f"{year}-{month:02d}"
        start_date = date(year, month, start_day)
        end_date = date(year, month, min(end_day, 31))
        
        # Use instance-level API for resource details
        all_items, account_id = self._fetch_daily_instance_items_for_month(
            client, month_str, start_date, end_date
        )
        
        # Aggregate by date + service + instance to avoid duplicates
        daily_instance: dict[tuple, float] = defaultdict(float)
        instance_names: dict[str, str] = {}
        
        for item in all_items:
            cost = float(item.pretax_amount or 0)
            if item.billing_date:
                instance_id = item.instance_id or ""
                service_name = item.product_name or item.product_code or "Unknown"
                key = (item.billing_date, service_name, instance_id)
                daily_instance[key] += cost
                
                # Store instance name mapping
                if instance_id and hasattr(item, 'instance_name') and item.instance_name:
                    instance_names[instance_id] = item.instance_name
        
        records = []
        for (billing_date, service_name, instance_id), cost in daily_instance.items():
            if cost > 0:
                try:
                    record_date = date.fromisoformat(billing_date)
                except ValueError:
                    continue
                records.append(CostRecord(
                    provider=self.provider,
                    account_id=account_id or self._account_id or "default",
                    service_name=service_name,
                    region="",
                    cost=cost,
                    currency="CNY",
                    instance_id=instance_id,
                    instance_name=instance_names.get(instance_id, ""),
                    date=record_date,
                    granularity=Granularity.DAILY,
                ))
        
        logger.info("阿里云日粒度(实例级): %d-%02d 共 %d 条记录", year, month, len(records))
        return records

    async def close(self) -> None:
        self._client = None
