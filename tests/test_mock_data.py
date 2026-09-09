"""Tests for mock data generator."""

from datetime import date, timedelta

import pytest

from costlens.mock_data import MockCloudConnector, MockDataProvider, generate_demo_dataset
from costlens.models.cost import Granularity


class TestMockDataProvider:
    def test_generate_daily_records(self):
        provider = MockDataProvider(seed=42)
        records = provider.generate_daily_records(provider="aws", days=7)
        assert len(records) > 0
        assert all(r.provider == "aws" for r in records)
        assert all(r.cost > 0 for r in records)

    def test_multi_cloud_data(self):
        provider = MockDataProvider(seed=42)
        records = provider.generate_multi_cloud_data(providers=["aws", "azure"], days=3)
        providers = {r.provider for r in records}
        assert "aws" in providers
        assert "azure" in providers

    def test_anomaly_injection(self):
        provider = MockDataProvider(seed=42)
        records = provider.generate_daily_records(
            provider="aws", days=30, inject_anomaly=True, anomaly_day=15, anomaly_multiplier=5.0
        )
        assert len(records) > 0

    def test_currency_mapping(self):
        provider = MockDataProvider(seed=42)

        aws_records = provider.generate_daily_records(provider="aws", days=1)
        assert all(r.currency == "USD" for r in aws_records)

        alibaba_records = provider.generate_daily_records(provider="alibaba", days=1)
        assert all(r.currency == "CNY" for r in alibaba_records)

    def test_tags_generation(self):
        provider = MockDataProvider(seed=42)
        records = provider.generate_daily_records(provider="aws", days=1)
        for r in records:
            assert "env" in r.tags
            assert "team" in r.tags


class TestMockCloudConnector:
    @pytest.mark.asyncio
    async def test_get_cost_data(self):
        connector = MockCloudConnector(provider="aws", seed=42)
        end = date.today()
        start = end - timedelta(days=7)
        records = await connector.get_cost_data(start, end)
        assert len(records) > 0

    @pytest.mark.asyncio
    async def test_get_cost_summary(self):
        connector = MockCloudConnector(provider="azure", seed=42)
        end = date.today()
        start = end - timedelta(days=7)
        summary = await connector.get_cost_summary(start, end)
        assert summary["total_cost"] > 0
        assert "service_breakdown" in summary

    @pytest.mark.asyncio
    async def test_list_accounts(self):
        connector = MockCloudConnector(provider="aws")
        accounts = await connector.list_accounts()
        assert len(accounts) >= 1


class TestDemoDataset:
    def test_generate_demo(self):
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            result = generate_demo_dataset(db_path)
            assert result["records_generated"] > 0
            assert result["alerts_generated"] > 0
            assert result["recommendations_generated"] > 0
            assert result["budgets_created"] == 4
        finally:
            os.unlink(db_path)
