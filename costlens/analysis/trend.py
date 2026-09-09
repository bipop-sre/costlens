"""Cost trend analysis."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

from costlens.models.cost import CostRecord, CostSummary, CostTrend

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Analyze cost trends over time."""

    def analyze_period_over_period(
        self,
        current_records: list[CostRecord],
        previous_records: list[CostRecord],
        period_label: str = "monthly",
    ) -> list[CostTrend]:
        """Compare current period costs vs previous period, per service."""
        current_by_service: dict[str, float] = defaultdict(float)
        previous_by_service: dict[str, float] = defaultdict(float)

        for r in current_records:
            current_by_service[r.service_name] += r.cost
        for r in previous_records:
            previous_by_service[r.service_name] += r.cost

        all_services = set(current_by_service.keys()) | set(previous_by_service.keys())
        trends = []

        for service in all_services:
            trend = CostTrend(
                provider=current_records[0].provider if current_records else "unknown",
                service_name=service,
                period=period_label,
                current_cost=current_by_service.get(service, 0),
                previous_cost=previous_by_service.get(service, 0),
            )
            trend.compute_change()
            trends.append(trend)

        trends.sort(key=lambda t: abs(t.change_amount), reverse=True)
        return trends

    def analyze_daily_trend(
        self,
        records: list[CostRecord],
    ) -> dict:
        """Analyze daily cost trend and compute moving averages."""
        daily_costs: dict[str, float] = defaultdict(float)
        for r in records:
            daily_costs[r.date.isoformat()] += r.cost

        sorted_dates = sorted(daily_costs.keys())
        if len(sorted_dates) < 3:
            return {"daily_costs": daily_costs, "moving_avg": {}, "trend": "insufficient_data"}

        values = np.array([daily_costs[d] for d in sorted_dates])
        window = min(7, len(values))
        moving_avg = np.convolve(values, np.ones(window) / window, mode="valid")

        trend_direction = "stable"
        if len(values) >= 7:
            first_half = np.mean(values[: len(values) // 2])
            second_half = np.mean(values[len(values) // 2 :])
            if second_half > first_half * 1.1:
                trend_direction = "increasing"
            elif second_half < first_half * 0.9:
                trend_direction = "decreasing"

        return {
            "daily_costs": daily_costs,
            "moving_avg": {
                sorted_dates[i + window - 1]: float(moving_avg[i])
                for i in range(len(moving_avg))
            },
            "trend": trend_direction,
            "avg_daily": float(np.mean(values)),
            "std_daily": float(np.std(values)),
            "max_daily": float(np.max(values)),
            "min_daily": float(np.min(values)),
        }

    def forecast(
        self,
        records: list[CostRecord],
        forecast_days: int = 30,
    ) -> dict:
        """Simple linear forecast for cost projection."""
        daily_costs: dict[str, float] = defaultdict(float)
        for r in records:
            daily_costs[r.date.isoformat()] += r.cost

        sorted_dates = sorted(daily_costs.keys())
        if len(sorted_dates) < 2:
            return {"forecast": [], "confidence": "low"}

        values = np.array([daily_costs[d] for d in sorted_dates])
        x = np.arange(len(values))
        slope, intercept = np.polyfit(x, values, 1)

        forecast_values = []
        base_date = date.fromisoformat(sorted_dates[-1])
        for i in range(1, forecast_days + 1):
            forecast_date = base_date + timedelta(days=i)
            predicted = max(0, slope * (len(values) + i - 1) + intercept)
            forecast_values.append({
                "date": forecast_date.isoformat(),
                "cost": round(float(predicted), 2),
            })

        total_forecast = sum(f["cost"] for f in forecast_values)
        return {
            "forecast": forecast_values,
            "total_forecast_cost": round(total_forecast, 2),
            "daily_slope": round(float(slope), 2),
            "confidence": "high" if len(sorted_dates) >= 30 else "medium" if len(sorted_dates) >= 14 else "low",
        }
