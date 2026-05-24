"""Tests for the SwarmCoordinator."""

import pytest
from unittest.mock import AsyncMock

from src.coordinator import SwarmCoordinator
from src.models import (
    AgentRole,
    Priority,
    Task,
    TaskStatus,
)


@pytest.fixture
def coordinator() -> SwarmCoordinator:
    return SwarmCoordinator(
        model="mimo-v2.5",
        max_agents=5,
        conflict_resolution=True,
    )


class TestCoordinatorInit:
    def test_defaults(self, coordinator: SwarmCoordinator) -> None:
        assert coordinator.model == "mimo-v2.5"
        assert coordinator.max_agents == 5
        assert coordinator.conflict_resolution is True
        assert len(coordinator.agents) == 0


class TestAgentSpawning:
    def test_spawn_agents(self, coordinator: SwarmCoordinator) -> None:
        task = Task(
            description="test",
            required_roles=[AgentRole.SCOUT, AgentRole.ANALYST, AgentRole.EXECUTOR],
        )
        agents = coordinator._spawn_agents(task.required_roles)
        assert len(agents) == 3
        roles = {a.role for a in agents}
        assert roles == {AgentRole.SCOUT, AgentRole.ANALYST, AgentRole.EXECUTOR}

    def test_spawn_deduplicates_roles(self, coordinator: SwarmCoordinator) -> None:
        task = Task(
            description="test",
            required_roles=[AgentRole.SCOUT, AgentRole.SCOUT, AgentRole.ANALYST],
        )
        agents = coordinator._spawn_agents(task.required_roles)
        assert len(agents) == 2  # two unique roles

    def test_spawn_respects_max_agents(self, coordinator: SwarmCoordinator) -> None:
        coordinator.max_agents = 2
        task = Task(
            description="test",
            required_roles=[AgentRole.SCOUT, AgentRole.ANALYST, AgentRole.EXECUTOR],
        )
        agents = coordinator._spawn_agents(task.required_roles)
        assert len(agents) == 2


class TestExecution:
    @pytest.mark.asyncio
    async def test_execute_end_to_end(self, coordinator: SwarmCoordinator) -> None:
        """Test full execution with mocked reasoning (no API calls)."""
        # Patch the agents' reason methods
        for role_cls in coordinator.__class__.__mro__:
            pass  # just checking the fixture works

        task = Task(
            description="Analyze ETH yield opportunities",
            required_roles=[AgentRole.SCOUT, AgentRole.ANALYST],
        )

        # Pre-spawn and mock
        agents = coordinator._spawn_agents(task.required_roles)
        for agent in agents:
            agent.reason = AsyncMock(return_value="mocked reasoning via mimo v2.5")

        results = await coordinator._delegate(agents, task)
        assert len(results) == 2
        assert all(r.status == TaskStatus.COMPLETED for r in results)

    @pytest.mark.asyncio
    async def test_execute_full_lifecycle(self, coordinator: SwarmCoordinator) -> None:
        """Test the full execute() lifecycle with mocked agents."""
        task = Task(
            description="Portfolio rebalance",
            required_roles=[AgentRole.SCOUT],
        )

        # Pre-spawn and register agents, then mock their reason method
        from src.agents.scout import ScoutAgent
        mock_scout = ScoutAgent(bus=coordinator.bus, agent_id="mock-scout-1")
        mock_scout.reason = AsyncMock(return_value="reasoning result")
        coordinator._agents[mock_scout.agent_id] = mock_scout

        # Override _spawn_agents to return our pre-mocked agent
        original_spawn = coordinator._spawn_agents
        coordinator._spawn_agents = lambda roles: [mock_scout]  # type: ignore[assignment]

        try:
            result = await coordinator.execute(task)
            assert result.status == TaskStatus.COMPLETED
            assert result.total_tokens_used >= 0
            assert "mock-scout-1" in result.summary
        finally:
            coordinator._spawn_agents = original_spawn


class TestConflictDetection:
    def test_no_conflict(self, coordinator: SwarmCoordinator) -> None:
        from src.models import TaskResult
        results = [
            TaskResult(task_id="t1", status=TaskStatus.COMPLETED, summary="ok", agent_results={"a": {"recommendation": "buy"}}),
            TaskResult(task_id="t1", status=TaskStatus.COMPLETED, summary="ok", agent_results={"b": {"recommendation": "buy"}}),
        ]
        conflicts = coordinator._detect_conflicts(results)
        assert len(conflicts) == 0

    def test_detects_conflict(self, coordinator: SwarmCoordinator) -> None:
        from src.models import TaskResult, AgentProposal, AgentRole
        results = [
            TaskResult(
                task_id="t1",
                status=TaskStatus.COMPLETED,
                summary="ok",
                agent_results={
                    "a": {"proposal": AgentProposal(agent_id="a", role=AgentRole.ANALYST, proposal="buy").model_dump()},
                },
            ),
            TaskResult(
                task_id="t1",
                status=TaskStatus.COMPLETED,
                summary="ok",
                agent_results={
                    "b": {"proposal": AgentProposal(agent_id="b", role=AgentRole.ANALYST, proposal="sell").model_dump()},
                },
            ),
        ]
        conflicts = coordinator._detect_conflicts(results)
        assert len(conflicts) == 1
        assert len(conflicts[0]) == 2


class TestAggregation:
    def test_aggregate(self, coordinator: SwarmCoordinator) -> None:
        from src.models import TaskResult
        task = Task(description="test")
        results = [
            TaskResult(task_id="t1", status=TaskStatus.COMPLETED, summary="scout done", total_tokens_used=1000),
            TaskResult(task_id="t1", status=TaskStatus.COMPLETED, summary="analyst done", total_tokens_used=2000),
        ]
        final = coordinator._aggregate(task, results)
        assert final.total_tokens_used == 3000
        assert final.status == TaskStatus.COMPLETED
        assert "scout done" in final.summary
