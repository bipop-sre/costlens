"""AWS Cost Explorer connector."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from costlens.cloud.base import CloudConnector
from costlens.config import get_settings
from costlens.models.cost import CostRecord, CostSummary, Granularity

logger = logging.getLogger(__name__)


class AWSCostConnector(CloudConnector):
    """AWS Cost Explorer API connector."""

    def __init__(self) -> None:
        self._client = None

    @property
    def provider(self) -> str:
        return "aws"

    def _get_client(self):
        if self._client is None:
            import boto3
            settings = get_settings()
            self._client = boto3.client(
                "ce",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
        return self._client

    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "DAILY",
    ) -> list[CostRecord]:
        client = self._get_client()
        response = client.get_cost_and_usage(
            TimePeriod={
                "Start": start_date.isoformat(),
                "End": end_date.isoformat(),
            },
            Granularity=granularity.upper(),
            Metrics=["UnblendedCost", "UsageQuantity"],
            GroupBy=[
                {"Type": "DIMENSION", "Key": "SERVICE"},
                {"Type": "DIMENSION", "Key": "REGION"},
            ],
        )
        records = []
        for result in response.get("ResultsByTime", []):
            period_start = result["TimePeriod"]["Start"]
            for group in result.get("Groups", []):
                service_name = group["Keys"][0]
                region = group["Keys"][1]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                usage = float(group["Metrics"]["UsageQuantity"]["Amount"])
                if cost > 0:
                    records.append(CostRecord(
                        provider=self.provider,
                        account_id=self._get_account_id(),
                        service_name=service_name,
                        region=region,
                        cost=cost,
                        currency="USD",
                        usage_amount=usage,
                        date=date.fromisoformat(period_start),
                        granularity=Granularity.DAILY if granularity.upper() == "DAILY" else Granularity.MONTHLY,
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
            account_id=self._get_account_id(),
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
        import boto3
        settings = get_settings()
        org_client = boto3.client(
            "organizations",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        try:
            response = org_client.list_accounts()
            return [
                {"id": a["Id"], "name": a["Name"], "email": a.get("Email", "")}
                for a in response.get("Accounts", [])
            ]
        except Exception:
            logger.warning("Cannot list AWS Organizations accounts, returning current account")
            return [{"id": self._get_account_id(), "name": "current", "email": ""}]

    async def get_rightsizing_recommendations(self) -> list[dict]:
        """Fetch AWS Compute Optimizer rightsizing recommendations."""
        client = self._get_client()
        try:
            response = client.get_rightsizing_recommendations(
                TargetSavingsPercentage=10.0,
                MaxResults=100,
            )
            return response.get("RightsizingRecommendations", [])
        except Exception as exc:
            logger.warning("Failed to get rightsizing recommendations: %s", exc)
            return []

    async def get_reservation_coverage(self) -> dict[str, Any]:
        """Get RI coverage information."""
        client = self._get_client()
        from datetime import timedelta
        end = date.today()
        start = end - timedelta(days=30)
        try:
            response = client.get_reservation_coverage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            )
            return response.get("CoveragesByTime", [])
        except Exception as exc:
            logger.warning("Failed to get RI coverage: %s", exc)
            return []

    def _get_account_id(self) -> str:
        import boto3
        settings = get_settings()
        try:
            sts = boto3.client(
                "sts",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
            return sts.get_caller_identity()["Account"]
        except Exception:
            return "unknown"

    async def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
