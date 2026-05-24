"""Base agent class with MiMo V2.5 integration for long-chain reasoning."""

from __future__ import annotations

import abc
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import (
    AgentMessage,
    AgentProposal,
    AgentRole,
    AgentState,
    MessageType,
    Task,
    TaskResult,
    TaskStatus,
)
from ..message_bus import MessageBus

logger = logging.getLogger(__name__)

MIMO_DEFAULT_BASE_URL = "https://api.mimo.xiaomi.com/v2.5"


class BaseAgent(abc.ABC):
    """Abstract base for every swarm agent.

    Provides MiMo V2.5 integration, message-bus hookup, and the
    ``run`` lifecycle that the coordinator calls.
    """

    role: AgentRole

    def __init__(
        self,
        agent_id: str | None = None,
        bus: MessageBus | None = None,
        *,
        api_key: str = "",
        model: str = "mimo-v2.5",
        base_url: str = MIMO_DEFAULT_BASE_URL,
    ) -> None:
        self.agent_id = agent_id or f"{self.role.value}-{uuid.uuid4().hex[:6]}"
        self.state = AgentState(agent_id=self.agent_id, role=self.role)
        self.bus = bus or MessageBus()
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        # Subscribe to messages addressed to us or broadcasts
        self.bus.subscribe(self.agent_id, self._on_message)  # type: ignore[arg-type]
        self.bus.subscribe(None, self._on_broadcast)  # type: ignore[arg-type]
        logger.info("Agent %s (%s) initialised", self.agent_id, self.role.value)

    # ------------------------------------------------------------------
    # MiMo V2.5 reasoning
    # ------------------------------------------------------------------

    async def reason(self, prompt: str, *, max_tokens: int = 4096) -> str:
        """Send *prompt* to MiMo V2.5 and return the model's response.

        In tests this is overridden with a stub.  The production path
        hits the MiMo inference endpoint.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", 0)
            self.state.tokens_used += tokens
            self.state.reasoning_trace.append(prompt[:120])
            return content

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _on_message(self, msg: AgentMessage) -> None:
        """Handle a message addressed directly to this agent."""
        if msg.message_type == MessageType.TASK_ASSIGN:
            logger.info("%s received task assignment: %s", self.agent_id, msg.task_id)

    async def _on_broadcast(self, msg: AgentMessage) -> None:
        """Handle a broadcast message (conflict reports, resolutions)."""
        if msg.message_type == MessageType.CONFLICT_REPORT:
            logger.info("%s saw conflict %s", self.agent_id, msg.payload.get("conflict_id"))
        elif msg.message_type == MessageType.RESOLUTION:
            logger.info("%s received resolution for conflict %s", self.agent_id, msg.payload.get("conflict_id"))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """Execute *task* and return a result.  Subclasses implement this."""

    async def send(self, message: AgentMessage) -> None:
        """Convenience wrapper around the bus."""
        await self.bus.publish(message)

    def heartbeat(self) -> None:
        """Update the heartbeat timestamp."""
        self.state.last_heartbeat = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _system_prompt(self) -> str:
        """Return the system prompt prefix for MiMo V2.5."""
        return (
            f"You are a {self.role.value} agent in the mimo-agent-swarm system. "
            "Use step-by-step reasoning. Be precise and structured."
        )

    def make_proposal(self, proposal: str, confidence: float, reasoning: str = "") -> AgentProposal:
        return AgentProposal(
            agent_id=self.agent_id,
            role=self.role,
            proposal=proposal,
            confidence=confidence,
            reasoning=reasoning,
        )

    def make_message(
        self,
        msg_type: MessageType,
        task_id: str,
        payload: dict[str, Any] | None = None,
        recipient: str | None = None,
    ) -> AgentMessage:
        return AgentMessage(
            sender_id=self.agent_id,
            recipient_id=recipient,
            message_type=msg_type,
            task_id=task_id,
            payload=payload or {},
        )
