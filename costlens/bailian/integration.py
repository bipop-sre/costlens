"""Integration helpers for tracking Bailian/DashScope token usage.

Provides wrappers and utilities to automatically track token usage
from DashScope API calls in your application code.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)


def track_openai_response(
    key_alias: str,
    response: Any,
    model_name: str = "",
    request_id: str = "",
) -> dict:
    """Track token usage from an OpenAI-compatible API response.

    Works with both DashScope native and OpenAI SDK responses.

    Usage:
        from openai import OpenAI

        client = OpenAI(
            api_key="sk-xxx",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        response = client.chat.completions.create(
            model="qwen-max",
            messages=[{"role": "user", "content": "hello"}],
        )

        # Track usage
        track_openai_response("default", response, "qwen-max")

    Returns:
        dict with tracking result (tokens, cost, etc.)
    """
    try:
        from costlens.bailian.tracker import get_bailian_tracker
        tracker = get_bailian_tracker()

        # Extract usage from response (handles both dict and object formats)
        usage = None
        if hasattr(response, "usage"):
            usage = response.usage
        elif isinstance(response, dict):
            usage = response.get("usage")

        if usage is None:
            return {"status": "skipped", "reason": "no usage data"}

        # Convert to dict if it's an object
        if hasattr(usage, "model_dump"):
            usage_dict = usage.model_dump()
        elif hasattr(usage, "__dict__"):
            usage_dict = {k: v for k, v in usage.__dict__.items() if not k.startswith("_")}
        else:
            usage_dict = dict(usage)

        # Extract model name from response if not provided
        if not model_name:
            if hasattr(response, "model"):
                model_name = response.model
            elif isinstance(response, dict):
                model_name = response.get("model", "unknown")

        # Extract request ID if not provided
        if not request_id:
            if hasattr(response, "id"):
                request_id = response.id or ""
            elif isinstance(response, dict):
                request_id = response.get("id", "")

        record = tracker.record_from_response(
            key_alias=key_alias,
            model_name=model_name,
            response_usage=usage_dict,
            request_id=request_id,
        )

        if record is None:
            return {"status": "skipped", "reason": "no token data"}

        return {
            "status": "ok",
            "model": record.model_name,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "total_tokens": record.total_tokens,
            "estimated_cost": record.estimated_cost,
        }
    except Exception as exc:
        logger.warning("Failed to track Bailian usage: %s", exc)
        return {"status": "error", "error": str(exc)}


def track_batch_usage(
    key_alias: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    call_count: int = 1,
    usage_date: Optional[date] = None,
) -> dict:
    """Track batch token usage (e.g., from aggregated logs).

    Usage:
        # Track 100 calls worth 50K input + 20K output tokens
        track_batch_usage("prod", "qwen-max", 50000, 20000, call_count=100)
    """
    try:
        from costlens.bailian.tracker import get_bailian_tracker
        tracker = get_bailian_tracker()
        record = tracker.record_usage(
            key_alias=key_alias,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            call_count=call_count,
            usage_date=usage_date,
        )
        return {
            "status": "ok",
            "total_tokens": record.total_tokens,
            "estimated_cost": record.estimated_cost,
        }
    except Exception as exc:
        logger.warning("Failed to track batch usage: %s", exc)
        return {"status": "error", "error": str(exc)}
