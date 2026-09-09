"""Budget analysis and monitoring."""

from __future__ import annotations

import logging
from datetime import date

from costlens.analysis.trend import TrendAnalyzer
from costlens.models.alert import Alert, AlertSeverity, AlertType
from costlens.models.budget import Budget, BudgetStatus
from costlens.models.cost import CostRecord

logger = logging.getLogger(__name__)


class BudgetAnalyzer:
    """Analyze costs against configured budgets."""

    def __init__(self) -> None:
        self._trend_analyzer = TrendAnalyzer()

    def evaluate_budgets(
        self,
        budgets: list[Budget],
        records: list[CostRecord],
    ) -> list[Alert]:
        """Evaluate budgets against actual costs and generate alerts."""
        alerts = []
        service_costs = self._aggregate_costs(records)

        for budget in budgets:
            actual_cost = self._get_budget_cost(budget, service_costs)
            budget.current_spend = actual_cost

            forecast = self._trend_analyzer.forecast(records, forecast_days=30)
            if forecast.get("total_forecast_cost"):
                daily_avg = actual_cost / max(1, self._days_elapsed(budget))
                days_in_period = self._days_in_period(budget)
                budget.forecast_spend = daily_avg * days_in_period

            for threshold in sorted(budget.alert_thresholds):
                threshold_amount = budget.amount * threshold / 100
                if actual_cost >= threshold_amount:
                    severity = AlertSeverity.CRITICAL if threshold >= 100 else AlertSeverity.WARNING
                    alerts.append(Alert(
                        alert_type=(
                            AlertType.BUDGET_EXCEEDED if threshold >= 100
                            else AlertType.BUDGET_THRESHOLD
                        ),
                        severity=severity,
                        title=f"预算 {budget.name} 已达 {threshold:.0f}%",
                        message=(
                            f"预算 '{budget.name}' 已使用 {actual_cost:.2f} / {budget.amount:.2f} "
                            f"({budget.utilization_pct:.1f}%)，"
                            f"剩余 {budget.remaining:.2f}"
                        ),
                        provider=budget.provider or "multi-cloud",
                        current_value=actual_cost,
                        threshold_value=threshold_amount,
                    ))

            if budget.forecast_spend > budget.amount:
                alerts.append(Alert(
                    alert_type=AlertType.FORECAST_EXCEEDED,
                    severity=AlertSeverity.WARNING,
                    title=f"预算 {budget.name} 预测将超支",
                    message=(
                        f"按当前趋势，预算 '{budget.name}' 月末预计花费 "
                        f"{budget.forecast_spend:.2f}，超出预算 {budget.amount:.2f} "
                        f"(超支 {budget.forecast_spend - budget.amount:.2f})"
                    ),
                    provider=budget.provider or "multi-cloud",
                    current_value=budget.forecast_spend,
                    threshold_value=budget.amount,
                ))

        return alerts

    def get_budget_status(
        self,
        budgets: list[Budget],
        records: list[CostRecord],
    ) -> list[Budget]:
        """Update budgets with current spend data."""
        service_costs = self._aggregate_costs(records)
        for budget in budgets:
            budget.current_spend = self._get_budget_cost(budget, service_costs)
        return budgets

    def _aggregate_costs(self, records: list[CostRecord]) -> dict[str, float]:
        costs: dict[str, float] = {}
        for r in records:
            costs[r.service_name] = costs.get(r.service_name, 0) + r.cost
        return costs

    def _get_budget_cost(self, budget: Budget, service_costs: dict[str, float]) -> float:
        if budget.service_name:
            return service_costs.get(budget.service_name, 0)
        return sum(service_costs.values())

    def _days_elapsed(self, budget: Budget) -> int:
        return max(1, (date.today() - budget.start_date).days)

    def _days_in_period(self, budget: Budget) -> int:
        from costlens.models.budget import BudgetPeriod
        if budget.period == BudgetPeriod.MONTHLY:
            return 30
        if budget.period == BudgetPeriod.QUARTERLY:
            return 90
        if budget.period == BudgetPeriod.YEARLY:
            return 365
        return 30
