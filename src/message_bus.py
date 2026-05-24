"""Inter-agent message bus for real-time communication and conflict resolution."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Awaitable

from .models import AgentMessage, MessageType, ConflictReport, AgentProposal

logger = logging.getLogger(__name__)


MessageHandler = Callable[[AgentMessage], Awaitable[None]]


class MessageBus:
    """Pub/sub message bus with built-in conflict detection.

    In production this would be backed by Redis Streams or NATS.
    The in-memory implementation here is sufficient for single-process
    coordination and unit tests.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str | None, list[MessageHandler]] = defaultdict(list)
        self._message_log: list[AgentMessage] = []
        self._pending_conflicts: dict[str, ConflictReport] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Pub / Sub
    # ------------------------------------------------------------------

    def subscribe(self, topic: str | None, handler: MessageHandler) -> None:
        """Subscribe *handler* to *topic* (None = all messages)."""
        self._subscribers[topic].append(handler)
        logger.debug("Subscribed handler to topic=%s", topic)

    def unsubscribe(self, topic: str | None, handler: MessageHandler) -> None:
        """Remove *handler* from *topic*."""
        try:
            self._subscribers[topic].remove(handler)
        except ValueError:
            pass

    async def publish(self, message: AgentMessage) -> None:
        """Publish *message* to matching subscribers."""
        async with self._lock:
            self._message_log.append(message)
        logger.info(
            "Published %s from %s (task=%s)",
            message.message_type.value,
            message.sender_id,
            message.task_id,
        )
        # Fan-out to topic-specific + wildcard subscribers
        targets = set(self._subscribers.get(message.message_type.value, []))
        targets.update(self._subscribers.get(None, []))
        for handler in targets:
            try:
                await handler(message)
            except Exception:
                logger.exception("Handler error for message %s", message.id)

    # ------------------------------------------------------------------
    # Conflict Resolution
    # ------------------------------------------------------------------

    async def report_conflict(
        self,
        task_id: str,
        proposals: list[AgentProposal],
    ) -> ConflictReport:
        """Record conflicting proposals and create a ConflictReport."""
        report = ConflictReport(task_id=task_id, proposals=proposals)
        self._pending_conflicts[report.conflict_id] = report
        logger.warning(
            "Conflict %s on task %s with %d proposals",
            report.conflict_id,
            task_id,
            len(proposals),
        )
        # Notify all agents
        msg = AgentMessage(
            sender_id="coordinator",
            message_type=MessageType.CONFLICT_REPORT,
            task_id=task_id,
            payload={"conflict_id": report.conflict_id, "proposals": [p.model_dump() for p in proposals]},
        )
        await self.publish(msg)
        return report

    async def resolve_conflict(
        self,
        conflict_id: str,
        resolution: str,
    ) -> ConflictReport:
        """Mark a conflict as resolved and broadcast the resolution."""
        report = self._pending_conflicts.get(conflict_id)
        if report is None:
            raise KeyError(f"Unknown conflict: {conflict_id}")
        report.resolution = resolution
        from datetime import datetime, timezone
        report.resolved_at = datetime.now(timezone.utc)

        msg = AgentMessage(
            sender_id="coordinator",
            message_type=MessageType.RESOLUTION,
            task_id=report.task_id,
            payload={"conflict_id": conflict_id, "resolution": resolution},
        )
        await self.publish(msg)
        return report

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_message_log(self, task_id: str | None = None) -> list[AgentMessage]:
        """Return the message log, optionally filtered by task."""
        if task_id is None:
            return list(self._message_log)
        return [m for m in self._message_log if m.task_id == task_id]

    @property
    def pending_conflicts(self) -> dict[str, ConflictReport]:
        return dict(self._pending_conflicts)
