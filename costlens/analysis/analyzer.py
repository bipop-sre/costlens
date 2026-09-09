"""Main cost analysis orchestrator."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from costlens.analysis.anomaly import AnomalyDetector
from costlens.analysis.budget_analyzer import BudgetAnalyzer
from costlens.analysis.optimizer import OptimizationEngine
from costlens.analysis.trend import TrendAnalyzer
from costlens.cloud.base import CloudConnector, CloudConnectorFactory
from costlens.config import Settings, get_settings
from costlens.models.alert import Alert
from costlens.models.budget import Budget
from costlens.models.cost import CostRecord, CostSummary
from costlens.models.recommendation import Recommendation

logger = logging.getLogger(__name__)


class CostAnalyzer:
    """Main analysis orchestrator that coordinates all analysis modules."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.trend_analyzer = TrendAnalyzer()
        self.anomaly_detector = AnomalyDetector()
        self.budget_analyzer = BudgetAnalyzer()
        self.optimizer = OptimizationEngine()
        self._connectors: dict[str, CloudConnector] = {}

    async def _get_connector(self, provider: str) -> CloudConnector:
        from costlens.config import CloudProvider
        if provider not in self._connectors:
            self._connectors[provider] = CloudConnectorFactory.create(CloudProvider(provider))
        return self._connectors[provider]

    async def get_multi_cloud_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        """Get aggregated cost summary across all configured cloud providers."""
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        providers = self.settings.get_enabled_providers()
        summaries = {}
        all_records = []

        for provider in providers:
            try:
                connector = await self._get_connector(provider.value)
                summary = await connector.get_cost_summary(start_date, end_date)
                summaries[provider.value] = summary
                all_records.extend(summary.daily_costs)
            except Exception as exc:
                logger.error("Failed to get cost summary from %s: %s", provider.value, exc)

        total_cost = sum(s.total_cost for s in summaries.values())
        return {
            "total_cost": total_cost,
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "provider_summaries": {
                p: {"total_cost": s.total_cost, "currency": s.currency}
                for p, s in summaries.items()
            },
            "provider_count": len(summaries),
        }

    async def analyze(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        budgets: Optional[list[Budget]] = None,
    ) -> dict:
        """Run full cost analysis pipeline."""
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        providers = self.settings.get_enabled_providers()
        all_records: list[CostRecord] = []
        all_alerts: list[Alert] = []
        all_recommendations: list[Recommendation] = []

        for provider in providers:
            try:
                connector = await self._get_connector(provider.value)
                records = await connector.get_cost_data(start_date, end_date)
                all_records.extend(records)

                alerts = self.anomaly_detector.detect_anomalies(records, provider.value)
                all_alerts.extend(alerts)

                recommendations = self.optimizer.generate_recommendations(records, provider.value)
                all_recommendations.extend(recommendations)

            except Exception as exc:
                logger.error("Analysis failed for %s: %s", provider.value, exc)
                all_alerts.append(Alert(
                    alert_type="cost_anomaly",
                    severity="critical",
                    title=f"{provider.value} 数据采集失败",
                    message=f"无法从 {provider.value} 获取成本数据: {exc}",
                    provider=provider.value,
                ))

        if budgets:
            budget_alerts = self.budget_analyzer.evaluate_budgets(budgets, all_records)
            all_alerts.extend(budget_alerts)

        trend_data = self.trend_analyzer.analyze_daily_trend(all_records)
        forecast = self.trend_analyzer.forecast(all_records)

        prev_start = start_date - timedelta(days=(end_date - start_date).days)
        prev_end = start_date - timedelta(days=1)
        prev_records: list[CostRecord] = []
        for provider in providers:
            try:
                connector = await self._get_connector(provider.value)
                prev_records.extend(await connector.get_cost_data(prev_start, prev_end))
            except Exception:
                pass

        trends = self.trend_analyzer.analyze_period_over_period(all_records, prev_records)

        total_savings = sum(r.estimated_saving for r in all_recommendations)

        return {
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "total_cost": sum(r.cost for r in all_records),
            "alerts": all_alerts,
            "alert_count": len(all_alerts),
            "recommendations": all_recommendations,
            "recommendation_count": len(all_recommendations),
            "total_potential_savings": total_savings,
            "trend": trend_data,
            "forecast": forecast,
            "period_over_period": [t.model_dump() for t in trends[:10]],
        }

    async def close(self) -> None:
        for connector in self._connectors.values():
            await connector.close()
        self._connectors.clear()
