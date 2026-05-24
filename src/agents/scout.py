"""Scout agent — reconnaissance, data collection, on-chain monitoring."""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseAgent
from ..models import (
    AgentMessage,
    AgentRole,
    MessageType,
    Task,
    TaskResult,
    TaskStatus,
)
from ..message_bus import MessageBus

logger = logging.getLogger(__name__)


class ScoutAgent(BaseAgent):
    """Collects external data and feeds it into the swarm.

    Typical crypto/Web3 duties:
    - Monitor mempool for pending transactions
    - Fetch on-chain metrics (TVL, volume, liquidity)
    - Track price feeds and oracle updates
    """

    role = AgentRole.SCOUT

    async def execute(self, task: Task) -> TaskResult:
        """Run the scout workflow for *task*."""
        logger.info("[%s] Starting reconnaissance for task %s", self.agent_id, task.id)
        self.state.task_id = task.id
        self.state.is_busy = True

        try:
            collected = await self._collect_data(task)

            # Share findings with the swarm
            await self.send(self.make_message(
                MessageType.DATA_SHARE,
                task.id,
                payload={"source": self.agent_id, "data": collected},
            ))

            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                summary=f"Scout {self.agent_id} collected {len(collected)} data points",
                details=collected,
                agent_results={self.agent_id: collected},
                total_tokens_used=self.state.tokens_used,
            )
        except Exception as exc:
            logger.error("[%s] Scout failed: %s", self.agent_id, exc)
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                summary=f"Scout failed: {exc}",
                total_tokens_used=self.state.tokens_used,
            )
        finally:
            self.state.is_busy = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _collect_data(self, task: Task) -> dict[str, Any]:
        """Use MiMo V2.5 to reason about what data to collect."""
        prompt = (
            f"Task: {task.description}\n\n"
            "Identify the key data sources needed and outline a collection plan. "
            "Return a JSON-serializable dict with keys: sources, metrics, priority_order."
        )
        reasoning = await self.reason(prompt)
        return {
            "sources": ["on_chain", "dex_aggregators", "oracle_feeds"],
            "metrics": ["tvl", "volume_24h", "price", "liquidity_depth"],
            "priority_order": ["price", "liquidity_depth", "tvl", "volume_24h"],
            "mimo_reasoning": reasoning,
        }
