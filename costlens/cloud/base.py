"""Base cloud connector interface."""

from __future__ import annotations

import abc
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from costlens.config import CloudProvider
    from costlens.models.cost import CostRecord, CostSummary


class CloudConnector(abc.ABC):
    """Abstract base class for cloud cost connectors."""

    @property
    @abc.abstractmethod
    def provider(self) -> str:
        """Cloud provider identifier."""

    @abc.abstractmethod
    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "daily",
    ) -> list[CostRecord]:
        """Fetch raw cost data records."""

    @abc.abstractmethod
    async def get_cost_summary(
        self,
        start_date: date,
        end_date: date,
    ) -> CostSummary:
        """Get aggregated cost summary."""

    @abc.abstractmethod
    async def get_service_breakdown(
        self,
        start_date: date,
        end_date: date,
    ) -> dict[str, float]:
        """Get cost breakdown by service."""

    @abc.abstractmethod
    async def list_accounts(self) -> list[dict]:
        """List accounts/subscriptions/projects."""

    async def __aenter__(self) -> CloudConnector:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def get_account_balance(self) -> dict:
        """Get account balance/credit information.
        
        Returns:
            dict with keys: provider, available_amount, credit_amount, currency, raw
        """
        return {}

    async def close(self) -> None:
        """Cleanup resources."""


class CloudConnectorFactory:
    """Factory for creating cloud connectors based on provider."""

    @staticmethod
    def create(provider: CloudProvider) -> CloudConnector:
        from costlens.config import CloudProvider as CP
        if provider == CP.AWS:
            from costlens.cloud.aws import AWSCostConnector
            return AWSCostConnector()
        if provider == CP.AZURE:
            from costlens.cloud.azure import AzureCostConnector
            return AzureCostConnector()
        if provider == CP.GCP:
            from costlens.cloud.gcp import GCPCostConnector
            return GCPCostConnector()
        if provider == CP.ALIBABA:
            from costlens.cloud.alibaba import AlibabaCloudCostConnector
            return AlibabaCloudCostConnector()
        if provider == CP.TENCENT:
            from costlens.cloud.tencent import TencentCloudCostConnector
            return TencentCloudCostConnector()
        raise ValueError(f"Unsupported cloud provider: {provider}")
