"""Tests for SQLite storage layer."""

import os
import tempfile
from datetime import date, timedelta

import pytest

from costlens.models.alert import Alert, AlertSeverity, AlertType
from costlens.models.budget import Budget, BudgetPeriod
from costlens.models.cost import CostRecord, Granularity
from costlens.models.recommendation import Priority, Recommendation, RecommendationType
from costlens.storage import Storage


@pytest.fixture
def storage():
    """Create a temporary storage instance."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = Storage(db_path)
    yield store
    os.unlink(db_path)


def _make_records(count: int = 5) -> list[CostRecord]:
    records = []
    base = date(2024, 1, 1)
    for i in range(count):
        records.append(CostRecord(
            provider="aws",
            account_id="test-123",
            service_name="EC2" if i % 2 == 0 else "S3",
            region="us-east-1",
            cost=100.0 + i * 10,
            currency="USD",
            date=base + timedelta(days=i),
            granularity=Granularity.DAILY,
        ))
    return records


class TestCostRecords:
    def test_save_and_query(self, storage):
        records = _make_records(5)
        count = storage.save_cost_records(records)
        assert count == 5

        result = storage.get_cost_records(
            date(2024, 1, 1), date(2024, 1, 31), provider="aws"
        )
        assert len(result) == 5

    def test_query_by_service(self, storage):
        records = _make_records(5)
        storage.save_cost_records(records)

        ec2 = storage.get_cost_records(
            date(2024, 1, 1), date(2024, 1, 31), service="EC2"
        )
        assert len(ec2) == 3  # i=0,2,4

    def test_daily_totals(self, storage):
        records = _make_records(3)
        storage.save_cost_records(records)

        totals = storage.get_daily_totals(date(2024, 1, 1), date(2024, 1, 31))
        assert len(totals) >= 1

    def test_service_totals(self, storage):
        records = _make_records(5)
        storage.save_cost_records(records)

        totals = storage.get_service_totals(date(2024, 1, 1), date(2024, 1, 31))
        assert "EC2" in totals
        assert "S3" in totals

    def test_upsert_on_conflict(self, storage):
        record = CostRecord(
            provider="aws", account_id="test", service_name="EC2",
            region="us-east-1", cost=100.0, date=date(2024, 1, 1),
            granularity=Granularity.DAILY,
        )
        storage.save_cost_records([record])

        record.cost = 200.0
        storage.save_cost_records([record])

        results = storage.get_cost_records(date(2024, 1, 1), date(2024, 1, 1))
        assert len(results) == 1
        assert results[0].cost == 200.0


class TestAlerts:
    def test_save_and_query(self, storage):
        alerts = [
            Alert(
                alert_type=AlertType.COST_ANOMALY,
                severity=AlertSeverity.WARNING,
                title="EC2 Cost Spike",
                message="EC2 cost increased by 50%",
                provider="aws",
                current_value=150.0,
                threshold_value=100.0,
            ),
            Alert(
                alert_type=AlertType.BUDGET_EXCEEDED,
                severity=AlertSeverity.CRITICAL,
                title="Budget Exceeded",
                message="Monthly budget exceeded",
                provider="aws",
                current_value=12000.0,
                threshold_value=10000.0,
            ),
        ]
        count = storage.save_alerts(alerts)
        assert count == 2

        results = storage.get_alerts()
        assert len(results) == 2

    def test_filter_by_severity(self, storage):
        alerts = [
            Alert(
                alert_type=AlertType.COST_ANOMALY, severity=AlertSeverity.WARNING,
                title="Warn", message="warn", provider="aws",
            ),
            Alert(
                alert_type=AlertType.COST_ANOMALY, severity=AlertSeverity.CRITICAL,
                title="Crit", message="crit", provider="aws",
            ),
        ]
        storage.save_alerts(alerts)

        critical = storage.get_alerts(severity="critical")
        assert len(critical) == 1

    def test_acknowledge(self, storage):
        alert = Alert(
            alert_type=AlertType.COST_ANOMALY, severity=AlertSeverity.WARNING,
            title="Test", message="test", provider="aws",
        )
        storage.save_alerts([alert])

        results = storage.get_alerts()
        alert_id = results[0]["id"]

        assert storage.acknowledge_alert(alert_id) is True
        acknowledged = storage.get_alerts(acknowledged=True)
        assert len(acknowledged) == 1

    def test_unnotified_alerts(self, storage):
        alerts = [
            Alert(
                alert_type=AlertType.COST_ANOMALY, severity=AlertSeverity.WARNING,
                title=f"Alert {i}", message=f"msg {i}", provider="aws",
            )
            for i in range(3)
        ]
        storage.save_alerts(alerts)

        unnotified = storage.get_unnotified_alerts()
        assert len(unnotified) == 3

        results = storage.get_alerts()
        ids = [r["id"] for r in results[:2]]
        storage.mark_alerts_notified(ids)

        remaining = storage.get_unnotified_alerts()
        assert len(remaining) == 1


class TestRecommendations:
    def test_save_and_query(self, storage):
        recs = [
            Recommendation(
                rec_type=RecommendationType.RESERVED_INSTANCE,
                priority=Priority.HIGH,
                title="Buy RI",
                description="Save 35%",
                provider="aws",
                service_name="EC2",
                estimated_saving=1000.0,
            ),
            Recommendation(
                rec_type=RecommendationType.IDLE_RESOURCE,
                priority=Priority.MEDIUM,
                title="Cleanup",
                description="Remove idle resources",
                provider="aws",
                service_name="EBS",
                estimated_saving=200.0,
            ),
        ]
        count = storage.save_recommendations(recs)
        assert count == 2

        results = storage.get_recommendations()
        assert len(results) == 2

    def test_filter_by_priority(self, storage):
        recs = [
            Recommendation(
                rec_type=RecommendationType.RESERVED_INSTANCE,
                priority=Priority.HIGH, title="RI", description="ri",
                provider="aws", service_name="EC2", estimated_saving=1000,
            ),
            Recommendation(
                rec_type=RecommendationType.IDLE_RESOURCE,
                priority=Priority.LOW, title="Idle", description="idle",
                provider="aws", service_name="EBS", estimated_saving=50,
            ),
        ]
        storage.save_recommendations(recs)

        high = storage.get_recommendations(priority="high")
        assert len(high) == 1

    def test_total_savings(self, storage):
        recs = [
            Recommendation(
                rec_type=RecommendationType.RESERVED_INSTANCE,
                priority=Priority.HIGH, title="RI", description="ri",
                provider="aws", service_name="EC2", estimated_saving=1000,
            ),
            Recommendation(
                rec_type=RecommendationType.STORAGE_TIER,
                priority=Priority.MEDIUM, title="Storage", description="s",
                provider="aws", service_name="S3", estimated_saving=300,
            ),
        ]
        storage.save_recommendations(recs)

        total = storage.get_total_potential_savings()
        assert total == 1300.0


class TestBudgets:
    def test_save_and_query(self, storage):
        budget = Budget(
            name="Monthly AWS",
            amount=10000.0,
            currency="USD",
            provider="aws",
        )
        storage.save_budget(budget)

        budgets = storage.get_budgets()
        assert len(budgets) == 1
        assert budgets[0].name == "Monthly AWS"
        assert budgets[0].amount == 10000.0

    def test_upsert(self, storage):
        budget = Budget(name="Test", amount=5000.0)
        storage.save_budget(budget)

        budget.amount = 8000.0
        storage.save_budget(budget)

        budgets = storage.get_budgets()
        assert len(budgets) == 1
        assert budgets[0].amount == 8000.0

    def test_delete(self, storage):
        budget = Budget(name="ToDelete", amount=1000.0)
        storage.save_budget(budget)

        assert storage.delete_budget("ToDelete") is True
        budgets = storage.get_budgets()
        assert len(budgets) == 0


class TestAnalysisRuns:
    def test_save_and_query(self, storage):
        result = {
            "period": {"start": "2024-01-01", "end": "2024-01-31"},
            "total_cost": 15000.0,
            "alert_count": 3,
            "recommendation_count": 5,
            "total_potential_savings": 2500.0,
        }
        run_id = storage.save_analysis_run(result)
        assert run_id > 0

        runs = storage.get_analysis_runs()
        assert len(runs) == 1
        assert runs[0]["total_cost"] == 15000.0


class TestStats:
    def test_get_stats(self, storage):
        stats = storage.get_stats()
        assert "cost_records" in stats
        assert "alerts" in stats
        assert "recommendations" in stats
        assert "budgets" in stats
