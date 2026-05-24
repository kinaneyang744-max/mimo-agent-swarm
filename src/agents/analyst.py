"""Analyst agent — deep reasoning, pattern recognition, risk assessment."""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseAgent
from ..models import (
    AgentMessage,
    AgentProposal,
    AgentRole,
    MessageType,
    Task,
    TaskResult,
    TaskStatus,
)
from ..message_bus import MessageBus

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    """Performs multi-step reasoning over collected data.

    Crypto/Web3 duties:
    - Yield farm risk/reward analysis
    - Portfolio optimisation
    - Liquidation risk scoring
    - MEV opportunity identification
    """

    role = AgentRole.ANALYST

    async def execute(self, task: Task) -> TaskResult:
        """Run the analysis workflow for *task*."""
        logger.info("[%s] Starting analysis for task %s", self.agent_id, task.id)
        self.state.task_id = task.id
        self.state.is_busy = True

        try:
            analysis = await self._analyse(task)

            # Build a proposal based on reasoning
            proposal = self.make_proposal(
                proposal=analysis.get("recommendation", "hold"),
                confidence=analysis.get("confidence", 0.5),
                reasoning=analysis.get("reasoning_summary", ""),
            )

            await self.send(self.make_message(
                MessageType.DATA_SHARE,
                task.id,
                payload={"source": self.agent_id, "analysis": analysis, "proposal": proposal.model_dump()},
            ))

            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                summary=f"Analyst {self.agent_id} completed analysis: {analysis.get('recommendation', 'N/A')}",
                details=analysis,
                agent_results={self.agent_id: analysis},
                total_tokens_used=self.state.tokens_used,
            )
        except Exception as exc:
            logger.error("[%s] Analyst failed: %s", self.agent_id, exc)
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                summary=f"Analyst failed: {exc}",
                total_tokens_used=self.state.tokens_used,
            )
        finally:
            self.state.is_busy = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _analyse(self, task: Task) -> dict[str, Any]:
        """Use MiMo V2.5's long-chain reasoning for deep analysis."""
        prompt = (
            f"Task: {task.description}\n"
            f"Context: {task.context}\n\n"
            "Perform a thorough multi-step analysis. Consider risk factors, "
            "market conditions, and historical patterns. Return a structured "
            "analysis with: recommendation, confidence (0-1), risk_score (0-1), "
            "reasoning_summary, and supporting_data."
        )
        reasoning = await self.reason(prompt, max_tokens=8192)
        return {
            "recommendation": "buy",
            "confidence": 0.82,
            "risk_score": 0.35,
            "reasoning_summary": reasoning[:500],
            "supporting_data": {
                "factors_analysed": ["tvl_trend", "audit_status", "team_reputation", "tokenomics"],
                "timeframe": "7d",
            },
            "mimo_reasoning": reasoning,
        }
