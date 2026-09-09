"""Prometheus metrics exporter for CostLens."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from costlens.analysis.analyzer import CostAnalyzer
from costlens.config import get_settings

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects CostLens metrics in Prometheus text format."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def collect(self) -> str:
        """Collect all metrics and return Prometheus text exposition."""
        lines: list[str] = []

        # Cloud cost metrics
        lines.extend(await self._collect_cost_metrics())

        # Budget metrics
        lines.extend(await self._collect_budget_metrics())

        # Alert metrics
        lines.extend(await self._collect_alert_metrics())

        # Recommendation metrics
        lines.extend(await self._collect_recommendation_metrics())

        # Agent metrics
        lines.extend(self._collect_agent_metrics())

        return "\n".join(lines) + "\n"

    async def _collect_cost_metrics(self) -> list[str]:
        """Collect cost-related metrics."""
        lines = []

        # Help and type headers
        lines.append("# HELP costlens_cloud_cost_total Total cloud cost by provider")
        lines.append("# TYPE costlens_cloud_cost_total gauge")

        lines.append("# HELP costlens_cloud_cost_daily_avg Daily average cost by provider")
        lines.append("# TYPE costlens_cloud_cost_daily_avg gauge")

        lines.append("# HELP costlens_cloud_service_cost Cost by service")
        lines.append("# TYPE costlens_cloud_service_cost gauge")

        lines.append("# HELP costlens_cloud_cost_month_to_date Month-to-date cost")
        lines.append("# TYPE costlens_cloud_cost_month_to_date gauge")

        try:
            analyzer = CostAnalyzer(self.settings)
            end = date.today()
            start_mtd = end.replace(day=1)
            start_30d = end - timedelta(days=30)

            # Get multi-cloud summary
            summary = await analyzer.get_multi_cloud_summary(start_mtd, end)

            # Total cost by provider (MTD)
            for provider, data in summary.get("provider_summaries", {}).items():
                cost = data.get("total_cost", 0)
                currency = data.get("currency", "USD")
                lines.append(f'costlens_cloud_cost_total{{provider="{provider}",currency="{currency}"}} {cost:.2f}')

            # MTD total
            total_cost = summary.get("total_cost", 0)
            lines.append(f'costlens_cloud_cost_month_to_date{{currency="USD"}} {total_cost:.2f}')

            # Daily average
            days = max(1, (end - start_mtd).days)
            daily_avg = total_cost / days
            lines.append(f'costlens_cloud_cost_daily_avg{{currency="USD"}} {daily_avg:.2f}')

            # Service breakdown (from 30-day data)
            all_service_costs: dict[str, float] = {}
            for provider in self.settings.get_enabled_providers():
                try:
                    connector = await analyzer._get_connector(provider.value)
                    breakdown = await connector.get_service_breakdown(start_30d, end)
                    for service, cost in breakdown.items():
                        key = f"{provider.value}:{service}"
                        all_service_costs[key] = cost
                except Exception as e:
                    logger.warning(f"Failed to get service breakdown for {provider.value}: {e}")

            # Top 10 services by cost
            top_services = sorted(all_service_costs.items(), key=lambda x: -x[1])[:10]
            for key, cost in top_services:
                provider, service = key.split(":", 1)
                service_safe = service.replace('"', '\\"')
                lines.append(
                    f'costlens_cloud_service_cost{{provider="{provider}",service="{service_safe}"}} {cost:.2f}'
                )

            await analyzer.close()

        except Exception as e:
            logger.error(f"Failed to collect cost metrics: {e}")
            lines.append(f'costlens_cloud_cost_total{{provider="error",currency="USD"}} 0')

        return lines

    async def _collect_budget_metrics(self) -> list[str]:
        """Collect budget-related metrics."""
        lines = []
        lines.append("# HELP costlens_budget_utilization_percent Budget utilization percentage")
        lines.append("# TYPE costlens_budget_utilization_percent gauge")

        lines.append("# HELP costlens_budget_remaining Remaining budget amount")
        lines.append("# TYPE costlens_budget_remaining gauge")

        # Note: Budgets would be loaded from storage in production
        # For now, return placeholder
        lines.append('costlens_budget_utilization_percent{budget="default"} 0')
        lines.append('costlens_budget_remaining{budget="default",currency="USD"} 0')

        return lines

    async def _collect_alert_metrics(self) -> list[str]:
        """Collect alert-related metrics."""
        lines = []
        lines.append("# HELP costlens_alerts_total Total number of alerts by severity")
        lines.append("# TYPE costlens_alerts_total gauge")

        lines.append("# HELP costlens_alerts_critical Critical alerts count")
        lines.append("# TYPE costlens_alerts_critical gauge")

        lines.append("# HELP costlens_alerts_warning Warning alerts count")
        lines.append("# TYPE costlens_alerts_warning gauge")

        # Placeholder - would be populated from recent alerts
        lines.append('costlens_alerts_total{severity="critical"} 0')
        lines.append('costlens_alerts_total{severity="warning"} 0')
        lines.append('costlens_alerts_total{severity="info"} 0')
        lines.append('costlens_alerts_critical 0')
        lines.append('costlens_alerts_warning 0')

        return lines

    async def _collect_recommendation_metrics(self) -> list[str]:
        """Collect recommendation-related metrics."""
        lines = []
        lines.append("# HELP costlens_recommendations_total Total optimization recommendations")
        lines.append("# TYPE costlens_recommendations_total gauge")

        lines.append("# HELP costlens_potential_savings_total Total potential savings")
        lines.append("# TYPE costlens_potential_savings_total gauge")

        lines.append("# HELP costlens_recommendations_by_priority Recommendations by priority")
        lines.append("# TYPE costlens_recommendations_by_priority gauge")

        # Placeholder
        lines.append('costlens_recommendations_total 0')
        lines.append('costlens_potential_savings_total{currency="USD"} 0')
        lines.append('costlens_recommendations_by_priority{priority="high"} 0')
        lines.append('costlens_recommendations_by_priority{priority="medium"} 0')
        lines.append('costlens_recommendations_by_priority{priority="low"} 0')

        return lines

    def _collect_agent_metrics(self) -> list[str]:
        """Collect agent-level metrics."""
        lines = []
        lines.append("# HELP costlens_info CostLens agent information")
        lines.append("# TYPE costlens_info gauge")

        lines.append("# HELP costlens_providers_enabled Number of enabled providers")
        lines.append("# TYPE costlens_providers_enabled gauge")

        providers = self.settings.get_enabled_providers()
        lines.append(
            f'costlens_info{{version="0.1.0",model="{self.settings.openai_model}"}} 1'
        )
        lines.append(f'costlens_providers_enabled {len(providers)}')

        for provider in providers:
            lines.append(f'costlens_provider_enabled{{provider="{provider.value}"}} 1')

        return lines


# Global collector instance
_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
