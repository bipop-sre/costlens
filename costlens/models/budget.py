"""Budget models."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BudgetPeriod(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class BudgetStatus(str, Enum):
    ON_TRACK = "on_track"
    WARNING = "warning"
    OVER_BUDGET = "over_budget"
    CRITICAL = "critical"


class Budget(BaseModel):
    """Budget configuration for cost monitoring."""
    name: str
    amount: float
    currency: str = "USD"
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    provider: Optional[str] = None
    service_name: Optional[str] = None
    tags: dict[str, str] = Field(default_factory=dict)
    alert_thresholds: list[float] = Field(default_factory=lambda: [50.0, 80.0, 100.0])
    start_date: date = Field(default_factory=date.today)
    current_spend: float = 0.0
    forecast_spend: float = 0.0

    @property
    def utilization_pct(self) -> float:
        if self.amount <= 0:
            return 0.0
        return (self.current_spend / self.amount) * 100

    @property
    def status(self) -> BudgetStatus:
        pct = self.utilization_pct
        if pct >= 100:
            return BudgetStatus.CRITICAL
        if pct >= 80:
            return BudgetStatus.OVER_BUDGET
        if pct >= 50:
            return BudgetStatus.WARNING
        return BudgetStatus.ON_TRACK

    @property
    def remaining(self) -> float:
        return max(0, self.amount - self.current_spend)
