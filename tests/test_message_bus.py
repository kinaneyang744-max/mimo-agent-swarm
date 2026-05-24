"""Tests for the MessageBus."""

import asyncio

import pytest

from src.message_bus import MessageBus
from src.models import AgentMessage, MessageType


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


class TestPublishSubscribe:
    @pytest.mark.asyncio
    async def test_publish_reaches_subscriber(self, bus: MessageBus) -> None:
        received: list[AgentMessage] = []

        async def handler(msg: AgentMessage) -> None:
            received.append(msg)

        bus.subscribe(None, handler)  # subscribe to all
        msg = AgentMessage(
            sender_id="test",
            message_type=MessageType.TASK_ASSIGN,
            payload={"hello": "world"},
        )
        await bus.publish(msg)
        assert len(received) == 1
        assert received[0].payload == {"hello": "world"}

    @pytest.mark.asyncio
    async def test_topic_filtered_subscription(self, bus: MessageBus) -> None:
        received: list[AgentMessage] = []

        async def handler(msg: AgentMessage) -> None:
            received.append(msg)

        bus.subscribe(MessageType.DATA_SHARE.value, handler)
        # Publish a different type — should not reach handler
        await bus.publish(AgentMessage(
            sender_id="x",
            message_type=MessageType.HEARTBEAT,
        ))
        assert len(received) == 0

        # Now publish matching type
        await bus.publish(AgentMessage(
            sender_id="x",
            message_type=MessageType.DATA_SHARE,
            task_id="t-1",
        ))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus: MessageBus) -> None:
        received: list[AgentMessage] = []

        async def handler(msg: AgentMessage) -> None:
            received.append(msg)

        bus.subscribe(None, handler)
        bus.unsubscribe(None, handler)
        await bus.publish(AgentMessage(sender_id="x", message_type=MessageType.HEARTBEAT))
        assert len(received) == 0


class TestMessageLog:
    @pytest.mark.asyncio
    async def test_message_log_records_all(self, bus: MessageBus) -> None:
        await bus.publish(AgentMessage(sender_id="a", message_type=MessageType.HEARTBEAT, task_id="t1"))
        await bus.publish(AgentMessage(sender_id="b", message_type=MessageType.HEARTBEAT, task_id="t2"))
        all_msgs = bus.get_message_log()
        assert len(all_msgs) == 2

    @pytest.mark.asyncio
    async def test_message_log_filtered_by_task(self, bus: MessageBus) -> None:
        await bus.publish(AgentMessage(sender_id="a", message_type=MessageType.HEARTBEAT, task_id="t1"))
        await bus.publish(AgentMessage(sender_id="b", message_type=MessageType.HEARTBEAT, task_id="t2"))
        filtered = bus.get_message_log(task_id="t1")
        assert len(filtered) == 1


class TestConflictResolution:
    @pytest.mark.asyncio
    async def test_report_and_resolve(self, bus: MessageBus) -> None:
        from src.models import AgentProposal, AgentRole

        proposals = [
            AgentProposal(agent_id="a", role=AgentRole.ANALYST, proposal="buy"),
            AgentProposal(agent_id="b", role=AgentRole.EXECUTOR, proposal="sell"),
        ]
        report = await bus.report_conflict("t-1", proposals)
        assert report.conflict_id in bus.pending_conflicts

        resolved = await bus.resolve_conflict(report.conflict_id, "buy — higher confidence")
        assert resolved.resolution == "buy — higher confidence"
        assert resolved.resolved_at is not None
        assert bus.pending_conflicts[resolved.conflict_id].resolution == "buy — higher confidence"
