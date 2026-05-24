"""Executor agent — action execution, transaction building, on-chain ops."""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseAgent
from ..models import (
    AgentRole,
    Task,
    TaskResult,
    TaskStatus,
)
from ..message_bus import MessageBus

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """Translates decisions into concrete actions.

    Crypto/Web3 duties:
    - Build and sign DeFi transactions
    - Execute token swaps via DEX aggregators
    - Submit governance votes
    - Place limit orders
    """

    role = AgentRole.EXECUTOR

    async def execute(self, task: Task) -> TaskResult:
        """Run the execution workflow for *task*."""
        logger.info("[%s] Starting execution for task %s", self.agent_id, task.id)
        self.state.task_id = task.id
        self.state.is_busy = True

        try:
            execution_plan = await self._plan_execution(task)
            tx_result = await self._simulate_execution(execution_plan)

            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                summary=f"Executor {self.agent_id} prepared {len(tx_result.get('transactions', []))} transactions",
                details=tx_result,
                agent_results={self.agent_id: execution_plan},
                total_tokens_used=self.state.tokens_used,
            )
        except Exception as exc:
            logger.error("[%s] Executor failed: %s", self.agent_id, exc)
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                summary=f"Executor failed: {exc}",
                total_tokens_used=self.state.tokens_used,
            )
        finally:
            self.state.is_busy = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _plan_execution(self, task: Task) -> dict[str, Any]:
        """Use MiMo V2.5 to reason about execution steps."""
        prompt = (
            f"Task: {task.description}\n"
            f"Context: {task.context}\n\n"
            "Create a detailed execution plan with ordered steps. "
            "Each step should include: action, target, parameters, and estimated_gas. "
            "Return a structured execution plan."
        )
        reasoning = await self.reason(prompt)
        return {
            "steps": [
                {"action": "approve_token", "target": "USDC", "parameters": {"amount": "unlimited"}, "estimated_gas": 46000},
                {"action": "swap", "target": "UniswapV3", "parameters": {"from": "USDC", "to": "ETH", "amount": "10000"}, "estimated_gas": 185000},
            ],
            "mimo_reasoning": reasoning,
        }

    async def _simulate_execution(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Simulate the plan without submitting on-chain."""
        return {
            "simulated": True,
            "transactions": plan.get("steps", []),
            "total_estimated_gas": sum(s.get("estimated_gas", 0) for s in plan.get("steps", [])),
            "success_probability": 0.97,
        }
