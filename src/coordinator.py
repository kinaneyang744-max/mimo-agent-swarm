"""Swarm Coordinator — orchestrates agents, MiMo V2.5 reasoning, conflict resolution."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .models import (
    AgentMessage,
    AgentProposal,
    AgentRole,
    MessageType,
    Task,
    TaskResult,
    TaskStatus,
)
from .message_bus import MessageBus
from .agents.scout import ScoutAgent
from .agents.analyst import AnalystAgent
from .agents.executor import ExecutorAgent
from .agents.base import BaseAgent

logger = logging.getLogger(__name__)

# Mapping from role → agent class
AGENT_CLASSES: dict[AgentRole, type[BaseAgent]] = {
    AgentRole.SCOUT: ScoutAgent,
    AgentRole.ANALYST: AnalystAgent,
    AgentRole.EXECUTOR: ExecutorAgent,
}


class SwarmCoordinator:
    """Central orchestrator for the mimo-agent-swarm.

    Responsibilities:
    1. Spawn specialised agents based on task requirements
    2. Delegate sub-tasks and collect results
    3. Detect and resolve inter-agent conflicts using MiMo V2.5
    4. Aggregate results into a unified TaskResult
    """

    def __init__(
        self,
        *,
        model: str = "mimo-v2.5",
        max_agents: int = 5,
        conflict_resolution: bool = True,
        api_key: str = "",
        base_url: str = "",
    ) -> None:
        self.model = model
        self.max_agents = max_agents
        self.conflict_resolution = conflict_resolution
        self._api_key = api_key
        self._base_url = base_url
        self.bus = MessageBus()
        self._agents: dict[str, BaseAgent] = {}
        self._task_results: dict[str, TaskResult] = {}
        logger.info(
            "SwarmCoordinator initialised (model=%s, max_agents=%d, conflict_res=%s)",
            model,
            max_agents,
            conflict_resolution,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, task: Task) -> TaskResult:
        """Full lifecycle: spawn agents → delegate → resolve → aggregate."""
        logger.info("Executing task %s: %s", task.id, task.description)
        task.status = TaskStatus.PLANNING

        # 1. Spawn agents for each required role
        agents = self._spawn_agents(task.required_roles)

        # 2. Delegate the task to all agents concurrently
        task.status = TaskStatus.IN_PROGRESS
        results = await self._delegate(agents, task)

        # 3. Conflict resolution
        conflicts = self._detect_conflicts(results)
        if conflicts and self.conflict_resolution:
            task.status = TaskStatus.CONFLICT
            resolved = await self._resolve_conflicts(task.id, conflicts)
            # Merge resolved decisions into results
            results = self._apply_resolution(results, resolved)

        # 4. Aggregate
        task.status = TaskStatus.COMPLETED
        task.updated_at = datetime.now(timezone.utc)

        final = self._aggregate(task, results)
        self._task_results[task.id] = final
        logger.info("Task %s completed (%s)", task.id, final.summary)
        return final

    def get_result(self, task_id: str) -> TaskResult | None:
        return self._task_results.get(task_id)

    @property
    def agents(self) -> dict[str, BaseAgent]:
        return dict(self._agents)

    # ------------------------------------------------------------------
    # Agent management
    # ------------------------------------------------------------------

    def _spawn_agents(self, roles: list[AgentRole]) -> list[BaseAgent]:
        """Instantiate one agent per role (deduplicated)."""
        spawned: list[BaseAgent] = []
        for role in set(roles):
            if len(self._agents) >= self.max_agents:
                logger.warning("Max agents (%d) reached; skipping %s", self.max_agents, role.value)
                continue
            cls = AGENT_CLASSES[role]
            agent = cls(
                bus=self.bus,
                api_key=self._api_key,
                model=self.model,
                base_url=self._base_url,
            )
            self._agents[agent.agent_id] = agent
            spawned.append(agent)
        logger.info("Spawned %d agents: %s", len(spawned), [a.agent_id for a in spawned])
        return spawned

    # ------------------------------------------------------------------
    # Delegation
    # ------------------------------------------------------------------

    async def _delegate(self, agents: list[BaseAgent], task: Task) -> list[TaskResult]:
        """Run all agents in parallel and collect results."""
        # Broadcast task assignment
        for agent in agents:
            await self.bus.publish(AgentMessage(
                sender_id="coordinator",
                recipient_id=agent.agent_id,
                message_type=MessageType.TASK_ASSIGN,
                task_id=task.id,
                payload={"description": task.description, "role": agent.role.value},
            ))

        tasks_coros = [agent.execute(task) for agent in agents]
        results = await asyncio.gather(*tasks_coros, return_exceptions=False)
        return list(results)

    # ------------------------------------------------------------------
    # Conflict detection & resolution
    # ------------------------------------------------------------------

    def _detect_conflicts(self, results: list[TaskResult]) -> list[list[AgentProposal]]:
        """Detect when agents produced conflicting proposals."""
        proposals_by_task: dict[str, list[AgentProposal]] = {}
        for r in results:
            for _aid, data in r.agent_results.items():
                if isinstance(data, dict) and "proposal" in data:
                    prop = data["proposal"]
                    if isinstance(prop, dict):
                        proposals_by_task.setdefault(r.task_id, []).append(AgentProposal(**prop))

        conflicts = []
        for task_id, props in proposals_by_task.items():
            unique_proposals = {p.proposal for p in props}
            if len(unique_proposals) > 1:
                conflicts.append(props)
        return conflicts

    async def _resolve_conflicts(
        self,
        task_id: str,
        conflict_groups: list[list[AgentProposal]],
    ) -> dict[str, str]:
        """Use MiMo V2.5 to resolve each conflict group."""
        from .agents.base import BaseAgent as _BA  # avoid circular at module level

        resolution_map: dict[str, str] = {}
        for proposals in conflict_groups:
            report = await self.bus.report_conflict(task_id, proposals)

            # Build a reasoning prompt for the coordinator
            prompt = (
                "The following agent proposals conflict. Analyse trade-offs "
                "and select the best course of action. Justify your choice.\n\n"
            )
            for p in proposals:
                prompt += f"[{p.role.value}] {p.proposal} (confidence={p.confidence})\n"
                if p.reasoning:
                    prompt += f"  Reasoning: {p.reasoning}\n"
            prompt += "\nRespond with ONLY the winning proposal text."

            # Use a temporary lightweight agent for coordinator reasoning
            temp_agent = _BA.__new__(_BA)
            temp_agent._api_key = self._api_key
            temp_agent._model = self.model
            temp_agent._base_url = self._base_url or "https://api.mimo.xiaomi.com/v2.5"
            from ..models import AgentState as _AgentState
            temp_agent.state = _AgentState(
                agent_id="coordinator-reasoner",
                role=AgentRole.ANALYST,
            )
            # Patch the system prompt method
            temp_agent._system_prompt = lambda: (  # type: ignore[assignment]
                "You are the swarm coordinator. Resolve conflicts between agents."
            )
            resolution = await _BA.reason(temp_agent, prompt)  # type: ignore[arg-type]

            await self.bus.resolve_conflict(report.conflict_id, resolution)
            resolution_map[report.conflict_id] = resolution

        return resolution_map

    def _apply_resolution(
        self,
        results: list[TaskResult],
        resolutions: dict[str, str],
    ) -> list[TaskResult]:
        """Mark results as conflict-resolved."""
        for r in results:
            if resolutions:
                r.conflict_resolved = True
                r.details["conflict_resolution"] = list(resolutions.values())
        return results

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate(self, task: Task, results: list[TaskResult]) -> TaskResult:
        """Merge all agent results into a single TaskResult."""
        total_tokens = sum(r.total_tokens_used for r in results)
        agent_results = {}
        summaries = []
        for r in results:
            agent_results.update(r.agent_results)
            summaries.append(r.summary)

        combined_details: dict[str, Any] = {}
        for r in results:
            combined_details.update(r.details)

        all_succeeded = all(r.status == TaskStatus.COMPLETED for r in results)

        return TaskResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED if all_succeeded else TaskStatus.FAILED,
            summary=" | ".join(summaries) if summaries else "No agent results",
            details=combined_details,
            agent_results=agent_results,
            total_tokens_used=total_tokens,
            conflict_resolved=any(r.conflict_resolved for r in results),
        )
