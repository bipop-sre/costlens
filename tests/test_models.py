import pytest
"""Tests for data models."""

from datetime import date

from costlens.models.budget import Budget, BudgetPeriod, BudgetStatus
from costlens.models.cost import CostRecord, CostSummary, CostTrend, Granularity
from costlens.models.recommendation import Priority, Recommendation, RecommendationType


def test_cost_record():
    record = CostRecord(
        provider="aws",
        account_id="123456789",
        service_name="Amazon EC2",
        region="us-east-1",
        cost=150.50,
        currency="USD",
        date=date(2024, 1, 15),
    )
    assert record.provider == "aws"
    assert record.cost == 150.50
    assert record.tag_key == "untagged"


def test_cost_record_with_tags():
    record = CostRecord(
        provider="aws",
        account_id="123",
        service_name="EC2",
        cost=100.0,
        tags={"env": "prod", "team": "backend"},
        date=date(2024, 1, 1),
    )
    assert record.tag_key == "env=prod|team=backend"


def test_cost_summary_daily_avg():
    summary = CostSummary(
        provider="aws",
        account_id="123",
        total_cost=3000.0,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
    )
    assert summary.daily_avg == 100.0


def test_cost_trend_compute():
    trend = CostTrend(
        provider="aws",
        service_name="EC2",
        period="monthly",
        current_cost=1200.0,
        previous_cost=1000.0,
    )
    trend.compute_change()
    assert trend.change_amount == 200.0
    assert trend.change_pct == 20.0


def test_budget_status():
    budget = Budget(name="Monthly", amount=10000.0)

    budget.current_spend = 5500
    assert budget.status == BudgetStatus.WARNING
    assert budget.utilization_pct == pytest.approx(55.0)

    budget.current_spend = 8500
    assert budget.status == BudgetStatus.OVER_BUDGET

    budget.current_spend = 10500
    assert budget.status == BudgetStatus.CRITICAL

    budget.current_spend = 1000
    assert budget.status == BudgetStatus.ON_TRACK


def test_budget_remaining():
    budget = Budget(name="Test", amount=5000.0, current_spend=3500.0)
    assert budget.remaining == 1500.0


def test_recommendation():
    rec = Recommendation(
        rec_type=RecommendationType.RESERVED_INSTANCE,
        priority=Priority.HIGH,
        title="购买 RI",
        description="建议购买预留实例",
        provider="aws",
        service_name="EC2",
        current_cost=5000.0,
        estimated_saving=1750.0,
        estimated_saving_pct=35.0,
    )
    assert rec.estimated_saving == 1750.0
    assert rec.priority == Priority.HIGH
