"""Optimization recommendation models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RecommendationType(str, Enum):
    RESERVED_INSTANCE = "reserved_instance"
    SPOT_INSTANCE = "spot_instance"
    RIGHT_SIZE = "right_size"
    IDLE_RESOURCE = "idle_resource"
    STORAGE_TIER = "storage_tier"
    COMMITMENT_DISCOUNT = "commitment_discount"
    UNUSED_RESOURCE = "unused_resource"
    ARCHITECTURE = "architecture"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Recommendation(BaseModel):
    """A single optimization recommendation."""
    rec_type: RecommendationType
    priority: Priority = Priority.MEDIUM
    title: str
    description: str
    provider: str
    service_name: str
    region: str = ""
    resource_id: Optional[str] = None
    current_cost: float = 0.0
    estimated_saving: float = 0.0
    estimated_saving_pct: float = 0.0
    currency: str = "USD"
    effort: str = "medium"
    impact: str = "medium"
    details: dict = Field(default_factory=dict)
    action_items: list[str] = Field(default_factory=list)
