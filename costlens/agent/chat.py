"""Chat session management for CostLens agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from costlens.agent.core import CostLensAgent

logger = logging.getLogger(__name__)


@dataclass
class ChatSession:
    """Manages conversation state for a CostLens agent chat session."""

    session_id: str
    agent: CostLensAgent
    history: list[dict] = field(default_factory=list)
    max_history: int = 50

    async def send(self, message: str) -> str:
        """Send a message and get the agent's response."""
        response = await self.agent.chat(message, self.history)

        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": response})

        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

        return response

    async def stream_send(self, message: str):
        """Send a message and stream the response."""
        self.history.append({"role": "user", "content": message})
        full_response = ""

        async for token in self.agent.stream_chat(message, self.history[:-1]):
            full_response += token
            yield token

        self.history.append({"role": "assistant", "content": full_response})

        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

    def clear_history(self) -> None:
        self.history.clear()

    def get_history(self) -> list[dict]:
        return self.history.copy()
