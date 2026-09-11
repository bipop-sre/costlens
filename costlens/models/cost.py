"""Cost data models."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Granularity(str, Enum):
    DAILY = "daily"
    MONTHLY = "monthly"
    HOURLY = "hourly"


class CostRecord(BaseModel):
    """Single cost data point from a cloud provider."""
    provider: str
    account_id: str
    service_name: str
    region: str = ""
    cost: float
    currency: str = "USD"
    usage_amount: float = 0.0
    usage_unit: str = ""
    instance_id: str = ""  # 资源实例ID
    instance_name: str = ""  # 资源实例名称
    tags: dict[str, str] = Field(default_factory=dict)
    date: date
    granularity: Granularity = Granularity.DAILY

    @property
    def tag_key(self) -> str:
        parts = [f"{k}={v}" for k, v in sorted(self.tags.items()) if k and v]
        return "|".join(parts) if parts else "untagged"


class CostSummary(BaseModel):
    """Aggregated cost summary."""
    provider: str
    account_id: str
    total_cost: float
    currency: str = "USD"
    period_start: date
    period_end: date
    service_breakdown: dict[str, float] = Field(default_factory=dict)
    region_breakdown: dict[str, float] = Field(default_factory=dict)
    tag_breakdown: dict[str, float] = Field(default_factory=dict)
    daily_costs: list[CostRecord] = Field(default_factory=list)

    @property
    def daily_avg(self) -> float:
        days = max(1, (self.period_end - self.period_start).days)
        return self.total_cost / days


class CostTrend(BaseModel):
    """Cost trend data for analysis."""
    provider: str
    service_name: Optional[str] = None
    period: str
    current_cost: float
    previous_cost: float
    change_amount: float = 0.0
    change_pct: float = 0.0
    currency: str = "USD"

    def compute_change(self) -> None:
        self.change_amount = self.current_cost - self.previous_cost
        if self.previous_cost > 0:
            self.change_pct = (self.change_amount / self.previous_cost) * 100
        elif self.current_cost > 0:
            self.change_pct = 100.0
