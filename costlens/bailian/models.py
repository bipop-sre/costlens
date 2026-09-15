"""Data models for Bailian token usage tracking."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class BailianApiKey(BaseModel):
    """Configuration for a Bailian API key."""
    key_alias: str
    key_prefix: str = ""
    description: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class BailianUsageRecord(BaseModel):
    """Single API call usage record."""
    key_alias: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 1
    estimated_cost: float = 0.0
    usage_date: date = Field(default_factory=date.today)
    request_id: str = ""
    metadata_json: str = "{}"

    @model_validator(mode="after")
    def compute_total(self):
        if self.total_tokens == 0 and (self.input_tokens > 0 or self.output_tokens > 0):
            self.total_tokens = self.input_tokens + self.output_tokens
        return self

    @property
    def completion_ratio(self) -> float:
        if self.input_tokens > 0:
            return self.output_tokens / self.input_tokens
        return 0.0


class BailianUsageSummary(BaseModel):
    """Aggregated usage summary for a key or model."""
    key_alias: str = ""
    model_name: str = ""
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_calls: int = 0
    total_cost: float = 0.0
    daily_avg_tokens: float = 0.0
    daily_avg_cost: float = 0.0

    @property
    def output_ratio(self) -> float:
        if self.total_tokens > 0:
            return self.total_output_tokens / self.total_tokens * 100
        return 0.0


class BailianModelPricing(BaseModel):
    """Pricing configuration for a model (per million tokens)."""
    model_name: str
    input_price: float = 0.0
    output_price: float = 0.0
    currency: str = "CNY"
    price_unit: str = "million"
