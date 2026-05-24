"""Pydantic data contracts for the mimo-agent-swarm system."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    """Roles available to swarm agents."""
    SCOUT = "scout"
    ANALYST = "analyst"
    EXECUTOR = "executor"


class TaskStatus(str, Enum):
    """Lifecycle states for a task."""
    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    CONFLICT = "conflict"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageType(str, Enum):
    """Message types on the inter-agent bus."""
    TASK_ASSIGN = "task_assign"
    STATUS_UPDATE = "status_update"
    DATA_SHARE = "data_share"
    CONFLICT_REPORT = "conflict_report"
    RESOLUTION = "resolution"
    HEARTBEAT = "heartbeat"


class Priority(int, Enum):
    """Task priority levels (lower = higher priority)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class Task(BaseModel):
    """A unit of work dispatched to the swarm."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str
    required_roles: list[AgentRole] = Field(default_factory=list)
    priority: Priority = Priority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    max_retries: int = 3
    timeout_seconds: int = 120


class AgentState(BaseModel):
    """Internal state for a single agent."""
    agent_id: str
    role: AgentRole
    task_id: str | None = None
    is_busy: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reasoning_trace: list[str] = Field(default_factory=list)
    tokens_used: int = 0


class AgentMessage(BaseModel):
    """A message exchanged between agents via the MessageBus."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender_id: str
    recipient_id: str | None = None  # None = broadcast
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConflictReport(BaseModel):
    """Describes a disagreement between agents."""
    conflict_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    task_id: str
    proposals: list[AgentProposal] = Field(default_factory=list)
    resolution: str | None = None
    resolved_at: datetime | None = None


class AgentProposal(BaseModel):
    """A proposal submitted by an agent during conflict resolution."""
    agent_id: str
    role: AgentRole
    proposal: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = ""


class TaskResult(BaseModel):
    """Final output produced by the swarm for a task."""
    task_id: str
    status: TaskStatus
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    agent_results: dict[str, Any] = Field(default_factory=dict)
    total_tokens_used: int = 0
    conflict_resolved: bool = False
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Rebuild models to resolve forward references
ConflictReport.model_rebuild()
