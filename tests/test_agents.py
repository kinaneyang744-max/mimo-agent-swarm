"""Tests for Scout, Analyst, and Executor agents."""

import pytest
from unittest.mock import AsyncMock, patch

from src.agents.scout import ScoutAgent
from src.agents.analyst import AnalystAgent
from src.agents.executor import ExecutorAgent
from src.models import Task, TaskStatus, AgentRole
from src.message_bus import MessageBus


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus()


def _make_task(**overrides) -> Task:
    defaults = {"description": "Analyze top yield farms", "required_roles": [AgentRole.SCOUT]}
    defaults.update(overrides)
    return Task(**defaults)


# ------------------------------------------------------------------
# Scout
# ------------------------------------------------------------------

class TestScoutAgent:
    def test_initialisation(self, bus: MessageBus) -> None:
        scout = ScoutAgent(bus=bus)
        assert scout.role == AgentRole.SCOUT
        assert scout.agent_id.startswith("scout-")

    @pytest.mark.asyncio
    async def test_execute_calls_reason(self, bus: MessageBus) -> None:
        scout = ScoutAgent(bus=bus)
        scout.reason = AsyncMock(return_value="collected data via mimo reasoning")
        task = _make_task()
        result = await scout.execute(task)
        assert result.status == TaskStatus.COMPLETED
        assert "collected" in result.summary.lower()
        scout.reason.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_handles_failure(self, bus: MessageBus) -> None:
        scout = ScoutAgent(bus=bus)
        scout.reason = AsyncMock(side_effect=RuntimeError("API down"))
        result = await scout.execute(_make_task())
        assert result.status == TaskStatus.FAILED
        assert "API down" in result.summary


# ------------------------------------------------------------------
# Analyst
# ------------------------------------------------------------------

class TestAnalystAgent:
    def test_initialisation(self, bus: MessageBus) -> None:
        analyst = AnalystAgent(bus=bus)
        assert analyst.role == AgentRole.ANALYST
        assert analyst.agent_id.startswith("analyst-")

    @pytest.mark.asyncio
    async def test_execute_calls_reason(self, bus: MessageBus) -> None:
        analyst = AnalystAgent(bus=bus)
        analyst.reason = AsyncMock(return_value="deep analysis result")
        task = _make_task(required_roles=[AgentRole.ANALYST])
        result = await analyst.execute(task)
        assert result.status == TaskStatus.COMPLETED
        assert "analysis" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_execute_handles_failure(self, bus: MessageBus) -> None:
        analyst = AnalystAgent(bus=bus)
        analyst.reason = AsyncMock(side_effect=TimeoutError("timeout"))
        result = await analyst.execute(_make_task())
        assert result.status == TaskStatus.FAILED


# ------------------------------------------------------------------
# Executor
# ------------------------------------------------------------------

class TestExecutorAgent:
    def test_initialisation(self, bus: MessageBus) -> None:
        executor = ExecutorAgent(bus=bus)
        assert executor.role == AgentRole.EXECUTOR
        assert executor.agent_id.startswith("executor-")

    @pytest.mark.asyncio
    async def test_execute_calls_reason(self, bus: MessageBus) -> None:
        executor = ExecutorAgent(bus=bus)
        executor.reason = AsyncMock(return_value="execution plan via mimo")
        task = _make_task(required_roles=[AgentRole.EXECUTOR])
        result = await executor.execute(task)
        assert result.status == TaskStatus.COMPLETED
        assert "transactions" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_execute_handles_failure(self, bus: MessageBus) -> None:
        executor = ExecutorAgent(bus=bus)
        executor.reason = AsyncMock(side_effect=ConnectionError("network"))
        result = await executor.execute(_make_task())
        assert result.status == TaskStatus.FAILED
