"""Bailian API probe - periodically calls DashScope to generate real tracking data."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from openai import AsyncOpenAI

from costlens.bailian.integration import track_openai_response

logger = logging.getLogger(__name__)

PROBE_PROMPTS = [
    "你好，请用一句话介绍自己。",
    "今天天气怎么样？（随便回答即可）",
    "1+1等于几？",
    "请用一句话总结云计算的优势。",
    "什么是大模型？简要回答。",
]


class BailianProbe:
    """Periodically calls DashScope API to generate real token usage data."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        key_alias: str = "default",
        interval_minutes: int = 5,
    ):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._key_alias = key_alias
        self._interval = interval_minutes * 60
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def _probe_once(self) -> dict:
        """Send a single probe request and track the response."""
        import random

        prompt = random.choice(PROBE_PROMPTS)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "你是 CostLens 探针，请简短回答。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=50,
            )

            result = track_openai_response(self._key_alias, response, self._model)
            logger.info("Bailian probe: model=%s result=%s", self._model, result)
            return result
        except Exception as exc:
            logger.error("Bailian probe failed: %s", exc, exc_info=True)
            return {"status": "error", "error": str(exc)}

    async def _loop(self):
        """Main probe loop."""
        logger.info(
            "Bailian probe started: model=%s, interval=%ds, alias=%s",
            self._model,
            self._interval,
            self._key_alias,
        )
        while self._running:
            await self._probe_once()
            await asyncio.sleep(self._interval)

    def start(self):
        """Start the probe background task."""
        if self._task is not None and not self._task.done():
            logger.warning("Bailian probe already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Bailian probe task created")

    async def stop(self):
        """Stop the probe background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Bailian probe stopped")


_probe: Optional[BailianProbe] = None


def get_probe() -> Optional[BailianProbe]:
    return _probe


def start_probe(
    api_key: str,
    base_url: str,
    model: str,
    key_alias: str = "default",
    interval_minutes: int = 5,
) -> BailianProbe:
    """Create and start the global probe."""
    global _probe
    _probe = BailianProbe(
        api_key=api_key,
        base_url=base_url,
        model=model,
        key_alias=key_alias,
        interval_minutes=interval_minutes,
    )
    _probe.start()
    return _probe


async def stop_probe():
    """Stop the global probe."""
    global _probe
    if _probe is not None:
        await _probe.stop()
        _probe = None
