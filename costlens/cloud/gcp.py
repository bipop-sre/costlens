"""Google Cloud Billing connector."""

from __future__ import annotations

import logging
from datetime import date

from costlens.cloud.base import CloudConnector
from costlens.config import get_settings
from costlens.models.cost import CostRecord, CostSummary, Granularity

logger = logging.getLogger(__name__)


class GCPCostConnector(CloudConnector):
    """GCP Cloud Billing API connector using BigQuery export."""

    def __init__(self) -> None:
        self._billing_account_id: str = ""
        self._project_id: str = ""

    @property
    def provider(self) -> str:
        return "gcp"

    def _init_config(self) -> None:
        if not self._billing_account_id:
            settings = get_settings()
            self._billing_account_id = settings.gcp_billing_account_id or ""
            self._project_id = settings.gcp_project_id or ""

    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "daily",
    ) -> list[CostRecord]:
        """Fetch cost data from BigQuery billing export."""
        self._init_config()
        try:
            from google.cloud import bigquery

            client = bigquery.Client(project=self._project_id)
            query = f"""
                SELECT
                    service.description AS service_name,
                    location.region AS region,
                    SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount)
                        FROM UNNEST(credits) c), 0)) AS total_cost,
                    SUM(usage.amount) AS total_usage,
                    usage.unit AS usage_unit,
                    DATE(usage_start_time) AS usage_date,
                    currency
                FROM `{self._project_id}.billing_export.gcp_billing_export_v1_{self._billing_account_id}`
                WHERE DATE(usage_start_time) BETWEEN @start AND @end
                GROUP BY service_name, region, usage_date, usage_unit, currency
                ORDER BY usage_date, total_cost DESC
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start", "DATE", start_date.isoformat()),
                    bigquery.ScalarQueryParameter("end", "DATE", end_date.isoformat()),
                ]
            )
            results = client.query(query, job_config=job_config).result()

            records = []
            for row in results:
                if row.total_cost and row.total_cost > 0:
                    records.append(CostRecord(
                        provider=self.provider,
                        account_id=self._project_id,
                        service_name=row.service_name or "Unknown",
                        region=row.region or "global",
                        cost=float(row.total_cost),
                        currency=row.currency or "USD",
                        usage_amount=float(row.total_usage or 0),
                        usage_unit=row.usage_unit or "",
                        date=row.usage_date,
                        granularity=Granularity.DAILY,
                    ))
            return records
        except ImportError:
            logger.warning("google-cloud-bigquery not installed, returning empty results")
            return []
        except Exception as exc:
            logger.error("Failed to query GCP billing BigQuery: %s", exc)
            return []

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
            account_id=self._project_id,
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
        self._init_config()
        return [{"id": self._project_id, "name": f"GCP Project: {self._project_id}"}]

    async def close(self) -> None:
        pass
