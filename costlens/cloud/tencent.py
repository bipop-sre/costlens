"""Tencent Cloud Billing connector."""

from __future__ import annotations

import logging
import json
import asyncio
from datetime import date

from costlens.cloud.base import CloudConnector
from costlens.config import Settings, get_settings
from costlens.models.cost import CostRecord, CostSummary, Granularity

logger = logging.getLogger(__name__)


class TencentCloudCostConnector(CloudConnector):
    """Tencent Cloud Billing API connector using summary-level endpoints."""

    def __init__(self) -> None:
        self._client = None
        self._account_id: str = ""

    @property
    def provider(self) -> str:
        return "tencent"

    def _get_client(self):
        if self._client is None:
            from tencentcloud.common import credential
            from tencentcloud.billing.v20180709 import billing_client

            settings = get_settings()
            cred = credential.Credential(
                settings.tencent_cloud_secret_id,
                settings.tencent_cloud_secret_key,
            )
            self._client = billing_client.BillingClient(cred, settings.tencent_cloud_region)
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

    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "monthly",
    ) -> list[CostRecord]:
        """Fetch cost data via DescribeBillSummaryByProduct API."""
        from tencentcloud.billing.v20180709 import models

        settings = get_settings()
        client = self._get_client()
        logger.info("腾讯云: 开始查询 %s 到 %s 的成本数据", start_date, end_date)
        logger.info("腾讯云: 使用 SecretId=%s...", settings.tencent_cloud_secret_id[:6] if settings.tencent_cloud_secret_id else "NOT SET")
        billing_months = self._get_billing_months(start_date, end_date)
        records = []

        for month in billing_months:
            try:
                logger.info("腾讯云: 正在查询 %s 的账单", month)
                request = models.DescribeBillSummaryByProductRequest()
                request.BeginTime = month
                request.EndTime = month

                response = client.DescribeBillSummaryByProduct(request)
                logger.info("腾讯云: %s API 调用成功, Ready=%s", month, response.Ready)

                if response.Ready == 0:
                    logger.warning("腾讯云: %s 数据未就绪，请稍后重试", month)
                    continue

                if response.SummaryOverview:
                    logger.info("腾讯云: %s 返回 %d 条产品数据", month, len(response.SummaryOverview))
                    for item in response.SummaryOverview:
                        cost_str = item.RealTotalCost or "0"
                        try:
                            cost = float(cost_str)
                        except (ValueError, TypeError):
                            cost = 0.0

                        product = item.BusinessCodeName or item.BusinessCode or "Unknown"
                        logger.info("  - %s: %.2f CNY", product, cost)
                        if cost > 0:
                            bill_date = date.fromisoformat(month + "-01")
                            records.append(CostRecord(
                                provider=self.provider,
                                account_id=self._account_id or "default",
                                service_name=item.BusinessCodeName or item.BusinessCode or "Unknown",
                                region="",
                                cost=cost,
                                currency="CNY",
                                date=bill_date,
                                granularity=Granularity.MONTHLY,
                                tags={
                                    "product_code": item.BusinessCode or "",
                                    "bill_month": item.BillMonth or month,
                                    "total_cost": item.TotalCost or "",
                                    "cash_pay": item.CashPayAmount or "",
                                },
                            ))

            except Exception as exc:
                logger.error("Failed to query Tencent Cloud billing for %s: %s", month, exc)
                continue

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

        # Try to enrich with region data
        if not region_breakdown:
            try:
                region_data = await self._get_region_breakdown(start_date, end_date)
                region_breakdown = region_data
            except Exception as exc:
                logger.warning("Failed to get region breakdown: %s", exc)

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

    async def _get_region_breakdown(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[str, float]:
        """Fetch region breakdown via DescribeBillSummaryByRegion API."""
        from tencentcloud.billing.v20180709 import models

        client = self._get_client()
        billing_months = self._get_billing_months(start_date, end_date)
        region_costs: dict[str, float] = {}

        for month in billing_months:
            try:
                request = models.DescribeBillSummaryByRegionRequest()
                request.BeginTime = month
                request.EndTime = month

                response = client.DescribeBillSummaryByRegion(request)

                if response.Ready == 0 or not response.SummaryOverview:
                    continue

                for item in response.SummaryOverview:
                    cost_str = item.RealTotalCost or "0"
                    try:
                        cost = float(cost_str)
                    except (ValueError, TypeError):
                        cost = 0.0
                    if cost > 0:
                        region_name = item.RegionName or item.RegionId or "Unknown"
                        region_costs[region_name] = region_costs.get(region_name, 0) + cost

            except Exception as exc:
                logger.warning("Failed to get region data for %s: %s", month, exc)
                continue

        return dict(sorted(region_costs.items(), key=lambda x: -x[1]))

    async def get_service_breakdown(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[str, float]:
        summary = await self.get_cost_summary(start_date, end_date)
        return summary.service_breakdown

    async def list_accounts(self) -> list[dict]:
        return [{"id": self._account_id or "default", "name": "Tencent Cloud Account"}]

    async def get_account_balance(self) -> dict:
        """Query Tencent Cloud account balance and credit."""
        from tencentcloud.billing.v20180709 import models
        
        client = self._get_client()
        try:
            request = models.DescribeAccountBalanceRequest()
            response = client.DescribeAccountBalance(request)
            
            # Tencent Cloud balance values are in cents (分)
            real_balance = (response.RealBalance or 0) / 100.0
            cash_balance = (response.CashAccountBalance or 0) / 100.0
            credit_total = (response.CreditAmount or 0) / 100.0
            credit_remaining = (response.CreditBalance or 0) / 100.0
            owe = (response.OweAmount or 0) / 100.0

            # For credit accounts, RealBalance is negative.
            # available_amount = max(0, cash) + remaining credit
            available = max(0, real_balance) + credit_remaining

            return {
                "provider": self.provider,
                "available_amount": round(available, 2),
                "cash_account_balance": round(cash_balance, 2),
                "real_balance": round(real_balance, 2),
                "credit_amount": round(credit_total, 2),
                "credit_balance": round(credit_remaining, 2),
                "owe_amount": round(owe, 2),
                "currency": "CNY",
            }
        except Exception as exc:
            logger.error("Failed to query Tencent balance: %s", exc)
            return {"provider": self.provider, "error": str(exc)}


    async def get_daily_cost_data(
        self, year: int, month: int, start_day: int = 1, end_day: int = 31
    ) -> list[CostRecord]:
        """获取腾讯云日粒度账单数据（按天+产品聚合）
        
        一次拉取整月明细，按 BillDay + BusinessCodeName 聚合，效率高。
        
        Args:
            year: 年份
            month: 月份 (1-12)
            start_day: 开始日期
            end_day: 结束日期
            
        Returns:
            CostRecord 列表
        """
        from tencentcloud.billing.v20180709 import models
        from collections import defaultdict
        
        client = self._get_client()
        month_str = f"{year}-{month:02d}"
        
        # Fetch all detail items with pagination + rate limiting
        all_items = []
        offset = 0
        page_size = 100
        max_pages = 200
        
        for page in range(max_pages):
            try:
                req = models.DescribeBillDetailRequest()
                req.Month = month_str
                req.Limit = page_size
                req.Offset = offset
                
                resp = client.DescribeBillDetail(req)
                
                if not resp.DetailSet:
                    break
                
                all_items.extend(resp.DetailSet)
                logger.debug("腾讯云明细: 第%d页获取 %d 条 (累计 %d)", page+1, len(resp.DetailSet), len(all_items))
                
                if len(resp.DetailSet) < page_size:
                    break
                offset += page_size
                
                # Rate limit: max 5 req/s, use 0.3s delay
                await asyncio.sleep(0.3)
                
            except Exception as e:
                if "RequestLimitExceeded" in str(e):
                    logger.warning("腾讯云限流，等待2秒后重试...")
                    await asyncio.sleep(2)
                    continue
                logger.warning("腾讯云明细获取失败 (offset=%d): %s", offset, e)
                break
        
        logger.info("腾讯云 %s 明细: 共获取 %d 条原始记录", month_str, len(all_items))
        
        # Aggregate by BillDay + service
        start_date = date(year, month, start_day)
        end_date = date(year, month, min(end_day, 31))
        daily_service: dict[tuple, float] = defaultdict(float)
        
        for item in all_items:
            bill_day = (item.BillDay or "")[:10]
            if not bill_day:
                continue
            try:
                d = date.fromisoformat(bill_day)
            except ValueError:
                continue
            if d < start_date or d > end_date:
                continue
            for comp in (item.ComponentSet or []):
                cost = float(comp.RealCost or 0)
                if cost > 0:
                    daily_service[(bill_day, item.BusinessCodeName or "Unknown")] += cost
        
        records = []
        for (bill_day, service_name), cost in daily_service.items():
            records.append(CostRecord(
                provider=self.provider,
                account_id=self._account_id or "default",
                service_name=service_name,
                region="",
                cost=cost,
                currency="CNY",
                date=date.fromisoformat(bill_day),
                granularity=Granularity.DAILY,
            ))
        
        logger.info("腾讯云日粒度: %s 聚合后 %d 条记录", month_str, len(records))
        return records
        
        return records

    async def close(self) -> None:
        self._client = None
