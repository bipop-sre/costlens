"""Cost optimization recommendation engine."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

from costlens.models.cost import CostRecord
from costlens.models.recommendation import Priority, Recommendation, RecommendationType

logger = logging.getLogger(__name__)

# Known service patterns for optimization
HIGH_COST_COMPUTE_SERVICES = {
    "aws": ["Amazon Elastic Compute Cloud", "Amazon ECS", "Amazon EKS", "AWS Lambda"],
    "azure": ["Virtual Machines", "Azure Kubernetes Service", "Azure Functions"],
    "gcp": ["Compute Engine", "Google Kubernetes Engine", "Cloud Functions"],
    "alibaba": ["云服务器 ECS", "容器服务 ACK", "函数计算"],
}

STORAGE_SERVICES = {
    "aws": ["Amazon Simple Storage Service", "Amazon Elastic Block Store", "Amazon RDS"],
    "azure": ["Storage Accounts", "Managed Disks", "Azure SQL Database"],
    "gcp": ["Cloud Storage", "Persistent Disk", "Cloud SQL"],
    "alibaba": ["对象存储 OSS", "云盘", "云数据库 RDS"],
}


class OptimizationEngine:
    """Generate cost optimization recommendations."""

    def generate_recommendations(
        self,
        records: list[CostRecord],
        provider: str = "aws",
    ) -> list[Recommendation]:
        """Generate all optimization recommendations."""
        recommendations: list[Recommendation] = []
        recommendations.extend(self._check_idle_resources(records, provider))
        recommendations.extend(self._check_storage_optimization(records, provider))
        recommendations.extend(self._check_commitment_opportunities(records, provider))
        recommendations.extend(self._check_cost_concentration(records, provider))
        recommendations.sort(key=lambda r: r.estimated_saving, reverse=True)
        return recommendations

    def _check_idle_resources(
        self,
        records: list[CostRecord],
        provider: str,
    ) -> list[Recommendation]:
        """Identify potentially idle resources based on low but consistent costs."""
        recommendations = []
        service_daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for r in records:
            service_daily[r.service_name][r.date.isoformat()] += r.cost

        for service, daily in service_daily.items():
            costs = list(daily.values())
            if len(costs) < 7:
                continue

            avg_cost = sum(costs) / len(costs)
            max_cost = max(costs)

            if max_cost > 0 and avg_cost / max_cost < 0.3 and avg_cost > 10:
                total_monthly = avg_cost * 30
                saving = total_monthly * 0.8
                recommendations.append(Recommendation(
                    rec_type=RecommendationType.IDLE_RESOURCE,
                    priority=Priority.MEDIUM,
                    title=f"{service} 可能存在闲置资源",
                    description=(
                        f"{service} 平均日成本 {avg_cost:.2f}，但峰值达 {max_cost:.2f}，"
                        f"利用率可能较低。建议审查是否有未使用的实例或资源。"
                    ),
                    provider=provider,
                    service_name=service,
                    current_cost=total_monthly,
                    estimated_saving=saving,
                    estimated_saving_pct=80.0,
                    effort="low",
                    impact="medium",
                    action_items=[
                        f"检查 {service} 中是否有低利用率的实例",
                        "使用云原生监控工具确认实际使用率",
                        "释放确认闲置的资源",
                    ],
                ))

        return recommendations

    def _check_storage_optimization(
        self,
        records: list[CostRecord],
        provider: str,
    ) -> list[Recommendation]:
        """Check for storage tier optimization opportunities."""
        recommendations = []
        storage_services = STORAGE_SERVICES.get(provider, [])

        for r in records:
            if r.service_name in storage_services and r.cost > 100:
                monthly_cost = r.cost * 30
                saving = monthly_cost * 0.3
                recommendations.append(Recommendation(
                    rec_type=RecommendationType.STORAGE_TIER,
                    priority=Priority.LOW,
                    title=f"{r.service_name} 存储分层优化",
                    description=(
                        f"{r.service_name} 月成本约 {monthly_cost:.2f}。"
                        f"建议审查数据访问模式，将低频访问数据迁移到更低成本的存储层。"
                    ),
                    provider=provider,
                    service_name=r.service_name,
                    region=r.region,
                    current_cost=monthly_cost,
                    estimated_saving=saving,
                    estimated_saving_pct=30.0,
                    effort="medium",
                    impact="medium",
                    action_items=[
                        "分析数据访问频率和访问模式",
                        "配置存储生命周期策略",
                        "启用智能分层存储",
                    ],
                ))
                break

        return recommendations

    def _check_commitment_opportunities(
        self,
        records: list[CostRecord],
        provider: str,
    ) -> list[Recommendation]:
        """Identify services that would benefit from RI/commitment discounts."""
        recommendations = []
        compute_services = HIGH_COST_COMPUTE_SERVICES.get(provider, [])

        service_costs: dict[str, float] = defaultdict(float)
        for r in records:
            service_costs[r.service_name] += r.cost

        for service, total_cost in service_costs.items():
            if service in compute_services and total_cost > 500:
                monthly_cost = total_cost
                saving = monthly_cost * 0.35
                recommendations.append(Recommendation(
                    rec_type=RecommendationType.RESERVED_INSTANCE,
                    priority=Priority.HIGH,
                    title=f"{service} 预留实例/承诺折扣",
                    description=(
                        f"{service} 月成本 {monthly_cost:.2f}，属于持续使用的高成本计算服务。"
                        f"购买预留实例或承诺折扣可节省约 35%。"
                    ),
                    provider=provider,
                    service_name=service,
                    current_cost=monthly_cost,
                    estimated_saving=saving,
                    estimated_saving_pct=35.0,
                    effort="medium",
                    impact="high",
                    action_items=[
                        "分析过去 3 个月的实例使用模式",
                        "评估 1 年/3 年期预留实例的 ROI",
                        "考虑使用 Spot/竞价实例替代部分弹性负载",
                    ],
                ))

        return recommendations

    def _check_cost_concentration(
        self,
        records: list[CostRecord],
        provider: str,
    ) -> list[Recommendation]:
        """Flag services that dominate the cost profile."""
        recommendations = []
        service_costs: dict[str, float] = defaultdict(float)
        total_cost = 0

        for r in records:
            service_costs[r.service_name] += r.cost
            total_cost += r.cost

        if total_cost == 0:
            return recommendations

        for service, cost in sorted(service_costs.items(), key=lambda x: -x[1]):
            pct = cost / total_cost * 100
            if pct >= 40 and cost > 1000:
                recommendations.append(Recommendation(
                    rec_type=RecommendationType.ARCHITECTURE,
                    priority=Priority.HIGH,
                    title=f"{service} 成本占比过高 ({pct:.1f}%)",
                    description=(
                        f"{service} 占总成本 {pct:.1f}%（{cost:.2f} / {total_cost:.2f}）。"
                        f"建议深入分析该服务的架构，寻找降本空间。"
                    ),
                    provider=provider,
                    service_name=service,
                    current_cost=cost,
                    estimated_saving=cost * 0.1,
                    estimated_saving_pct=10.0,
                    effort="high",
                    impact="high",
                    action_items=[
                        f"详细审查 {service} 的使用量和计费模式",
                        "评估架构优化可能性（如 serverless、容器化）",
                        "实施自动扩缩容策略",
                    ],
                ))

        return recommendations
