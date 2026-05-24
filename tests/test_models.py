"""Tests for Pydantic models."""

from datetime import datetime, timezone

from src.models import (
    AgentMessage,
    AgentProposal,
    AgentState,
    ConflictReport,
    MessageType,
    Priority,
    Task,
    TaskResult,
    TaskStatus,
    AgentRole,
)


class TestTask:
    def test_create_task_with_defaults(self) -> None:
        task = Task(description="Analyze ETH/BTC pair")
        assert task.status == TaskStatus.PENDING
        assert task.priority == Priority.NORMAL
        assert task.id  # auto-generated
        assert isinstance(task.created_at, datetime)

    def test_task_with_explicit_fields(self) -> None:
        task = Task(
            id="custom-123",
            description="Find MEV opportunities",
            required_roles=[AgentRole.SCOUT, AgentRole.ANALYST],
            priority=Priority.HIGH,
            context={"chain": "ethereum"},
        )
        assert task.id == "custom-123"
        assert len(task.required_roles) == 2
        assert task.priority == Priority.HIGH
        assert task.context["chain"] == "ethereum"


class TestAgentState:
    def test_default_state(self) -> None:
        state = AgentState(agent_id="scout-001", role=AgentRole.SCOUT)
        assert state.is_busy is False
        assert state.confidence == 1.0
        assert state.tokens_used == 0
        assert state.reasoning_trace == []


class TestAgentMessage:
    def test_message_creation(self) -> None:
        msg = AgentMessage(
            sender_id="agent-1",
            message_type=MessageType.TASK_ASSIGN,
            task_id="t-001",
            payload={"description": "do something"},
        )
        assert msg.sender_id == "agent-1"
        assert msg.recipient_id is None  # broadcast
        assert msg.id  # auto-generated

    def test_directed_message(self) -> None:
        msg = AgentMessage(
            sender_id="coordinator",
            recipient_id="analyst-007",
            message_type=MessageType.DATA_SHARE,
            payload={"data": {"key": "value"}},
        )
        assert msg.recipient_id == "analyst-007"


class TestAgentProposal:
    def test_proposal(self) -> None:
        p = AgentProposal(
            agent_id="analyst-1",
            role=AgentRole.ANALYST,
            proposal="buy",
            confidence=0.85,
            reasoning="Strong fundamentals",
        )
        assert p.confidence == 0.85
        assert p.role == AgentRole.ANALYST


class TestConflictReport:
    def test_conflict_creation(self) -> None:
        proposals = [
            AgentProposal(agent_id="a", role=AgentRole.ANALYST, proposal="buy"),
            AgentProposal(agent_id="b", role=AgentRole.EXECUTOR, proposal="sell"),
        ]
        cr = ConflictReport(task_id="t-1", proposals=proposals)
        assert cr.resolution is None
        assert len(cr.proposals) == 2
        assert cr.conflict_id  # auto-generated


class TestTaskResult:
    def test_result_defaults(self) -> None:
        r = TaskResult(task_id="t-1", status=TaskStatus.COMPLETED, summary="done")
        assert r.total_tokens_used == 0
        assert r.conflict_resolved is False
        assert r.agent_results == {}
