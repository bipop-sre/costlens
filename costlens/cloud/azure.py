"""Azure Cost Management connector."""

from __future__ import annotations

import logging
from datetime import date

from costlens.cloud.base import CloudConnector
from costlens.config import get_settings
from costlens.models.cost import CostRecord, CostSummary, Granularity

logger = logging.getLogger(__name__)


class AzureCostConnector(CloudConnector):
    """Azure Cost Management API connector."""

    def __init__(self) -> None:
        self._client = None
        self._subscription_id: str = ""

    @property
    def provider(self) -> str:
        return "azure"

    def _get_client(self):
        if self._client is None:
            from azure.identity import ClientSecretCredential
            from azure.mgmt.costmanagement import CostManagementClient

            settings = get_settings()
            self._subscription_id = settings.azure_subscription_id or ""
            credential = ClientSecretCredential(
                tenant_id=settings.azure_tenant_id or "",
                client_id=settings.azure_client_id or "",
                client_secret=settings.azure_client_secret or "",
            )
            self._client = CostManagementClient(credential)
        return self._client

    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "daily",
    ) -> list[CostRecord]:
        client = self._get_client()
        scope = f"subscriptions/{self._subscription_id}"

        from azure.mgmt.costmanagement.models import (
            QueryDefinition, QueryTimePeriod, QueryDataset,
            QueryAggregation, QueryGrouping, GranularityType,
        )

        query_def = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(
                from_property=start_date.isoformat(),
                to=end_date.isoformat(),
            ),
            dataset=QueryDataset(
                granularity=GranularityType(granularity.capitalize()),
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                grouping=[
                    QueryGrouping(type="Dimension", name="ServiceName"),
                    QueryGrouping(type="Dimension", name="ResourceLocation"),
                ],
            ),
        )

        result = client.query.usage(scope, query_def)
        records = []
        for row in result.rows:
            cost = float(row[0])
            service_name = str(row[1])
            region = str(row[2])
            usage_date = str(row[3])

            if cost > 0:
                records.append(CostRecord(
                    provider=self.provider,
                    account_id=self._subscription_id,
                    service_name=service_name,
                    region=region,
                    cost=cost,
                    currency=result.properties.next_link or "USD",
                    date=date.fromisoformat(usage_date[:10]) if len(usage_date) >= 10 else start_date,
                    granularity=Granularity.DAILY if granularity.lower() == "daily" else Granularity.MONTHLY,
                ))
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
            region_breakdown[record.region] = (
                region_breakdown.get(record.region, 0) + record.cost
            )
        return CostSummary(
            provider=self.provider,
            account_id=self._subscription_id,
            total_cost=total_cost,
            currency="USD",
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
        return [{"id": self._subscription_id, "name": "Azure Subscription"}]

    async def close(self) -> None:
        self._client = None
