"""Tests for analysis engine."""

from datetime import date, timedelta

import pytest

from costlens.analysis.anomaly import AnomalyDetector
from costlens.analysis.budget_analyzer import BudgetAnalyzer
from costlens.analysis.optimizer import OptimizationEngine
from costlens.analysis.trend import TrendAnalyzer
from costlens.models.alert import AlertType
from costlens.models.budget import Budget
from costlens.models.cost import CostRecord, Granularity


def _make_records(service: str, costs: list[float], provider: str = "aws") -> list[CostRecord]:
    records = []
    base = date(2024, 1, 1)
    for i, cost in enumerate(costs):
        records.append(CostRecord(
            provider=provider,
            account_id="test",
            service_name=service,
            region="us-east-1",
            cost=cost,
            date=base + timedelta(days=i),
            granularity=Granularity.DAILY,
        ))
    return records


class TestTrendAnalyzer:
    def test_daily_trend(self):
        records = _make_records("EC2", [100, 120, 110, 130, 140, 150, 160])
        analyzer = TrendAnalyzer()
        result = analyzer.analyze_daily_trend(records)
        assert result["trend"] in ("increasing", "stable", "decreasing")
        assert "avg_daily" in result
        assert result["max_daily"] == 160.0

    def test_period_over_period(self):
        current = _make_records("EC2", [200, 250, 300])
        previous = _make_records("EC2", [100, 120, 150])
        analyzer = TrendAnalyzer()
        trends = analyzer.analyze_period_over_period(current, previous)
        assert len(trends) >= 1
        assert trends[0].service_name == "EC2"
        assert trends[0].current_cost > trends[0].previous_cost

    def test_forecast(self):
        records = _make_records("EC2", list(range(100, 130)))
        analyzer = TrendAnalyzer()
        result = analyzer.forecast(records, forecast_days=7)
        assert len(result["forecast"]) == 7
        assert result["confidence"] in ("low", "medium", "high")

    def test_insufficient_data(self):
        records = _make_records("EC2", [100])
        analyzer = TrendAnalyzer()
        result = analyzer.analyze_daily_trend(records)
        assert result["trend"] == "insufficient_data"


class TestAnomalyDetector:
    def test_detect_spike(self):
        costs = [100] * 10 + [500]
        records = _make_records("EC2", costs)
        detector = AnomalyDetector(threshold_sigma=2.0, spike_threshold_pct=30.0)
        alerts = detector.detect_anomalies(records, "aws")
        assert len(alerts) >= 1
        spike_alerts = [a for a in alerts if a.alert_type == AlertType.COST_SPIKE]
        assert len(spike_alerts) >= 1

    def test_no_anomaly_stable(self):
        costs = [100] * 20
        records = _make_records("EC2", costs)
        detector = AnomalyDetector(threshold_sigma=2.0)
        alerts = detector.detect_anomalies(records, "aws")
        anomaly_alerts = [a for a in alerts if a.alert_type == AlertType.COST_ANOMALY]
        assert len(anomaly_alerts) == 0

    def test_detect_new_services(self):
        records = _make_records("NewService", [500])
        detector = AnomalyDetector()
        alerts = detector.detect_new_services(records, known_services={"EC2"})
        assert len(alerts) == 1
        assert "NewService" in alerts[0].title


class TestBudgetAnalyzer:
    def test_budget_threshold_alert(self):
        budgets = [Budget(name="Monthly", amount=1000.0, alert_thresholds=[80.0, 100.0])]
        records = _make_records("EC2", [900])
        analyzer = BudgetAnalyzer()
        alerts = analyzer.evaluate_budgets(budgets, records)
        assert len(alerts) >= 1

    def test_budget_on_track(self):
        budgets = [Budget(name="Monthly", amount=10000.0, alert_thresholds=[80.0, 100.0])]
        records = _make_records("EC2", [100])
        analyzer = BudgetAnalyzer()
        alerts = analyzer.evaluate_budgets(budgets, records)
        assert len(alerts) == 0


class TestOptimizationEngine:
    def test_idle_resource_detection(self):
        costs = [10] * 10 + [100]
        records = _make_records("EC2", costs)
        engine = OptimizationEngine()
        recs = engine.generate_recommendations(records, "aws")
        idle_recs = [r for r in recs if r.rec_type.value == "idle_resource"]
        assert len(idle_recs) >= 1

    def test_commitment_opportunity(self):
        records = _make_records("Amazon Elastic Compute Cloud", [50] * 30)
        engine = OptimizationEngine()
        recs = engine.generate_recommendations(records, "aws")
        ri_recs = [r for r in recs if r.rec_type.value == "reserved_instance"]
        assert len(ri_recs) >= 1

    def test_no_recommendations_low_cost(self):
        records = _make_records("Lambda", [1] * 10)
        engine = OptimizationEngine()
        recs = engine.generate_recommendations(records, "aws")
        assert len(recs) == 0
