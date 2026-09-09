"""Mock data generator for end-to-end testing without real cloud credentials."""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Optional

from costlens.models.cost import CostRecord, Granularity


class MockDataProvider:
    """Generates realistic mock cloud cost data for testing."""

    # AWS service catalog with typical cost ranges (daily)
    AWS_SERVICES = {
        "Amazon Elastic Compute Cloud": {"min": 200, "max": 800, "regions": ["us-east-1", "us-west-2", "eu-west-1"]},
        "Amazon Simple Storage Service": {"min": 50, "max": 200, "regions": ["us-east-1", "us-west-2"]},
        "Amazon RDS": {"min": 80, "max": 400, "regions": ["us-east-1", "eu-west-1"]},
        "AWS Lambda": {"min": 10, "max": 80, "regions": ["us-east-1", "us-west-2", "ap-southeast-1"]},
        "Amazon CloudFront": {"min": 30, "max": 150, "regions": ["global"]},
        "Amazon Elastic Load Balancer": {"min": 20, "max": 60, "regions": ["us-east-1", "us-west-2"]},
        "Amazon ElastiCache": {"min": 40, "max": 120, "regions": ["us-east-1"]},
        "Amazon DynamoDB": {"min": 15, "max": 60, "regions": ["us-east-1", "us-west-2"]},
        "Amazon ECS": {"min": 30, "max": 100, "regions": ["us-east-1"]},
        "Amazon Route 53": {"min": 5, "max": 20, "regions": ["global"]},
        "AWS CloudTrail": {"min": 5, "max": 15, "regions": ["us-east-1"]},
        "Amazon SQS": {"min": 3, "max": 12, "regions": ["us-east-1"]},
    }

    # Azure service catalog
    AZURE_SERVICES = {
        "Virtual Machines": {"min": 150, "max": 600, "regions": ["eastus", "westeurope", "southeastasia"]},
        "Storage Accounts": {"min": 30, "max": 120, "regions": ["eastus", "westeurope"]},
        "Azure SQL Database": {"min": 60, "max": 300, "regions": ["eastus", "westeurope"]},
        "Azure Functions": {"min": 5, "max": 40, "regions": ["eastus"]},
        "Azure CDN": {"min": 20, "max": 80, "regions": ["global"]},
        "Azure Kubernetes Service": {"min": 80, "max": 250, "regions": ["eastus"]},
        "Azure App Service": {"min": 40, "max": 150, "regions": ["eastus", "westeurope"]},
        "Azure Cosmos DB": {"min": 25, "max": 100, "regions": ["eastus"]},
    }

    # Alibaba Cloud services
    ALIBABA_SERVICES = {
        "云服务器 ECS": {"min": 100, "max": 500, "regions": ["cn-hangzhou", "cn-shanghai", "cn-beijing"]},
        "对象存储 OSS": {"min": 20, "max": 80, "regions": ["cn-hangzhou"]},
        "云数据库 RDS": {"min": 40, "max": 200, "regions": ["cn-hangzhou", "cn-shanghai"]},
        "函数计算": {"min": 5, "max": 30, "regions": ["cn-hangzhou"]},
        "CDN": {"min": 15, "max": 60, "regions": ["global"]},
        "容器服务 ACK": {"min": 50, "max": 150, "regions": ["cn-hangzhou"]},
        "负载均衡 SLB": {"min": 10, "max": 40, "regions": ["cn-hangzhou"]},
        "NAT 网关": {"min": 8, "max": 25, "regions": ["cn-hangzhou"]},
    }

    SERVICE_CATALOGS = {
        "aws": AWS_SERVICES,
        "azure": AZURE_SERVICES,
        "alibaba": ALIBABA_SERVICES,
    }

    CURRENCY_MAP = {
        "aws": "USD",
        "azure": "USD",
        "alibaba": "CNY",
        "gcp": "USD",
    }

    def __init__(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            random.seed(seed)

    def generate_daily_records(
        self,
        provider: str = "aws",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        days: int = 30,
        inject_anomaly: bool = False,
        anomaly_day: Optional[int] = None,
        anomaly_multiplier: float = 3.0,
    ) -> list[CostRecord]:
        """Generate realistic daily cost records."""
        if start_date is None:
            start_date = date.today() - timedelta(days=days)
        if end_date is None:
            end_date = date.today()

        catalog = self.SERVICE_CATALOGS.get(provider, self.AWS_SERVICES)
        currency = self.CURRENCY_MAP.get(provider, "USD")
        records = []

        current_date = start_date
        day_index = 0

        while current_date <= end_date:
            for service_name, config in catalog.items():
                base_cost = random.uniform(config["min"], config["max"])

                # Add weekly pattern (weekends are cheaper for compute)
                weekday = current_date.weekday()
                if weekday >= 5 and "Compute" in service_name:
                    base_cost *= random.uniform(0.6, 0.8)

                # Add gradual growth trend
                growth_factor = 1 + (day_index * 0.002)
                base_cost *= growth_factor

                # Add noise
                noise = random.uniform(-0.1, 0.1)
                base_cost *= (1 + noise)

                # Inject anomaly
                if inject_anomaly and anomaly_day is not None and day_index == anomaly_day:
                    if service_name in (
                        list(catalog.keys())[:2]
                    ):
                        base_cost *= anomaly_multiplier

                region = random.choice(config["regions"])
                account_id = f"{provider}-account-{random.randint(1, 3)}"

                records.append(CostRecord(
                    provider=provider,
                    account_id=account_id,
                    service_name=service_name,
                    region=region,
                    cost=round(base_cost, 2),
                    currency=currency,
                    usage_amount=round(base_cost * random.uniform(0.5, 2.0), 2),
                    usage_unit="Units",
                    tags=self._generate_tags(provider, service_name),
                    date=current_date,
                    granularity=Granularity.DAILY,
                ))

            current_date += timedelta(days=1)
            day_index += 1

        return records

    def generate_multi_cloud_data(
        self,
        providers: Optional[list[str]] = None,
        days: int = 30,
        inject_anomaly: bool = True,
    ) -> list[CostRecord]:
        """Generate data for multiple cloud providers."""
        if providers is None:
            providers = ["aws", "azure", "alibaba"]

        all_records = []
        for provider in providers:
            anomaly_day = random.randint(15, 25) if inject_anomaly else None
            records = self.generate_daily_records(
                provider=provider,
                days=days,
                inject_anomaly=inject_anomaly and provider == providers[0],
                anomaly_day=anomaly_day,
            )
            all_records.extend(records)

        return all_records

    def _generate_tags(self, provider: str, service_name: str) -> dict[str, str]:
        """Generate realistic tags for cost records."""
        environments = ["production", "staging", "development"]
        teams = ["backend", "frontend", "data", "infra", "ml"]
        projects = ["main-app", "analytics", "api-gateway", "ml-pipeline", "monitoring"]

        tags = {
            "env": random.choice(environments),
            "team": random.choice(teams),
            "project": random.choice(projects),
        }

        if provider == "aws":
            tags["aws:autoscaling:groupName"] = f"{random.choice(projects)}-asg"
        elif provider == "azure":
            tags["cost-center"] = f"CC-{random.randint(1000, 9999)}"
        elif provider == "alibaba":
            tags["biz"] = random.choice(["核心业务", "支撑平台", "数据平台"])

        return tags


class MockCloudConnector:
    """Mock cloud connector that returns generated data instead of calling real APIs."""

    def __init__(self, provider: str = "aws", seed: int = 42) -> None:
        self._provider = provider
        self._data_provider = MockDataProvider(seed=seed)

    @property
    def provider(self) -> str:
        return self._provider

    async def get_cost_data(
        self,
        start_date: date,
        end_date: date,
        granularity: str = "daily",
    ) -> list[CostRecord]:
        return self._data_provider.generate_daily_records(
            provider=self._provider,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_cost_summary(self, start_date: date, end_date: date) -> dict:
        records = await self.get_cost_data(start_date, end_date)
        total_cost = sum(r.cost for r in records)

        service_breakdown: dict[str, float] = {}
        region_breakdown: dict[str, float] = {}
        for r in records:
            service_breakdown[r.service_name] = service_breakdown.get(r.service_name, 0) + r.cost
            region_breakdown[r.region] = region_breakdown.get(r.region, 0) + r.cost

        return {
            "provider": self._provider,
            "account_id": f"{self._provider}-account-1",
            "total_cost": total_cost,
            "currency": self._data_provider.CURRENCY_MAP.get(self._provider, "USD"),
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "service_breakdown": dict(sorted(service_breakdown.items(), key=lambda x: -x[1])),
            "region_breakdown": dict(sorted(region_breakdown.items(), key=lambda x: -x[1])),
            "record_count": len(records),
        }

    async def get_service_breakdown(self, start_date: date, end_date: date) -> dict[str, float]:
        summary = await self.get_cost_summary(start_date, end_date)
        return summary["service_breakdown"]

    async def list_accounts(self) -> list[dict]:
        return [
            {"id": f"{self._provider}-account-1", "name": f"{self._provider.upper()} Production"},
            {"id": f"{self._provider}-account-2", "name": f"{self._provider.upper()} Staging"},
        ]

    async def close(self) -> None:
        pass


def generate_demo_dataset(db_path: str = "costlens_demo.db") -> dict:
    """Generate a complete demo dataset and save to SQLite."""
    from costlens.storage import Storage

    storage = Storage(db_path)
    data_provider = MockDataProvider(seed=42)

    # Generate 90 days of data for 3 providers
    all_records = data_provider.generate_multi_cloud_data(
        providers=["aws", "azure", "alibaba"],
        days=90,
        inject_anomaly=True,
    )

    # Save cost records
    record_count = storage.save_cost_records(all_records)

    # Generate and save some budgets
    from costlens.models.budget import Budget
    budgets = [
        Budget(name="Monthly Total", amount=50000, currency="USD"),
        Budget(name="AWS Monthly", amount=30000, currency="USD", provider="aws"),
        Budget(name="Azure Monthly", amount=15000, currency="USD", provider="azure"),
        Budget(name="阿里云月度", amount=80000, currency="CNY", provider="alibaba"),
    ]
    for budget in budgets:
        storage.save_budget(budget)

    # Run analysis and save alerts/recommendations
    from costlens.analysis.analyzer import CostAnalyzer
    from costlens.config import Settings

    # Use a minimal settings for mock analysis
    from costlens.analysis.anomaly import AnomalyDetector
    from costlens.analysis.optimizer import OptimizationEngine

    detector = AnomalyDetector()
    optimizer = OptimizationEngine()

    all_alerts = []
    all_recs = []

    for provider in ["aws", "azure", "alibaba"]:
        provider_records = [r for r in all_records if r.provider == provider]
        alerts = detector.detect_anomalies(provider_records, provider)
        all_alerts.extend(alerts)
        recs = optimizer.generate_recommendations(provider_records, provider)
        all_recs.extend(recs)

    alert_count = storage.save_alerts(all_alerts)
    rec_count = storage.save_recommendations(all_recs)

    stats = storage.get_stats()

    return {
        "records_generated": record_count,
        "alerts_generated": alert_count,
        "recommendations_generated": rec_count,
        "budgets_created": len(budgets),
        "stats": stats,
        "db_path": db_path,
    }
