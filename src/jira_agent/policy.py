"""Autonomy stages and the policy that gates every action.

Stage 1  READ_ONLY        search and read issues.
Stage 2  ALERTS           + raise alerts (e.g. stale items). No writes.
Stage 3  HUMAN_APPROVED   + propose writes; a named human must approve each one.
Stage 4  POLICY_GOVERNED  + apply low-risk writes listed in the policy directly;
                            anything else still goes to human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Stage(IntEnum):
    READ_ONLY = 1
    ALERTS = 2
    HUMAN_APPROVED = 3
    POLICY_GOVERNED = 4


class PolicyError(PermissionError):
    """Raised when an action is not allowed at the current stage/policy."""


@dataclass
class Policy:
    stage: Stage = Stage.READ_ONLY
    stale_after_days: float = 5.0
    # Writes the agent may apply on its own at stage 4: (from_status, to_status).
    auto_transitions: set[tuple[str, str]] = field(
        default_factory=lambda: {("Code Review", "Waiting to Test")}
    )
    auto_labels: set[str] = field(default_factory=lambda: {"stale"})
    max_auto_writes_per_run: int = 10
    # Never touched by the agent, at any stage.
    protected_statuses: set[str] = field(default_factory=lambda: {"Done"})

    def require(self, minimum: Stage, action: str) -> None:
        if self.stage < minimum:
            raise PolicyError(f"'{action}' requires stage {minimum.name}; current stage is {self.stage.name}")

    def can_auto_transition(self, from_status: str, to_status: str) -> bool:
        return self.stage >= Stage.POLICY_GOVERNED and (from_status, to_status) in self.auto_transitions

    def can_auto_label(self, label: str) -> bool:
        return self.stage >= Stage.POLICY_GOVERNED and label in self.auto_labels
