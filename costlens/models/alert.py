"""Alert models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    BUDGET_EXCEEDED = "budget_exceeded"
    BUDGET_THRESHOLD = "budget_threshold"
    COST_ANOMALY = "cost_anomaly"
    COST_SPIKE = "cost_spike"
    FORECAST_EXCEEDED = "forecast_exceeded"


class Alert(BaseModel):
    """A cost alert."""
    alert_type: AlertType
    severity: AlertSeverity = AlertSeverity.WARNING
    title: str
    message: str
    provider: str
    current_value: float = 0.0
    threshold_value: float = 0.0
    currency: str = "USD"
    resource_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    acknowledged: bool = False
    details: dict = Field(default_factory=dict)
