"""GovernedJira: the tool surface the LLM sees.

Every public method is one MCP tool. Each call is checked against the
policy and recorded in the audit trail, whether it succeeds or is denied.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .policy import Policy, PolicyError, Stage
from .store import MockJira


@dataclass
class AuditEvent:
    at: str
    actor: str
    tool: str
    args: dict
    outcome: str  # ok | denied | queued | approved | rejected | error
    detail: str = ""


@dataclass
class Proposal:
    id: int
    issue_key: str
    action: str  # transition | label
    value: str
    reason: str
    status: str = "pending"  # pending | approved | rejected
    decided_by: str | None = None


@dataclass
class GovernedJira:
    jira: MockJira
    policy: Policy
    clock: callable = field(default=datetime.now)
    audit: list[AuditEvent] = field(default_factory=list)
    proposals: dict[int, Proposal] = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _auto_writes: int = 0

    # ---- audit -------------------------------------------------------------
    def _log(self, tool: str, args: dict, outcome: str, detail: str = "", actor: str = "agent") -> None:
        self.audit.append(AuditEvent(self.clock().isoformat(timespec="seconds"), actor, tool, args, outcome, detail))

    def audit_jsonl(self) -> str:
        return "\n".join(json.dumps(asdict(e), ensure_ascii=False) for e in self.audit)

    def _guard(self, minimum: Stage, tool: str, args: dict) -> None:
        try:
            self.policy.require(minimum, tool)
        except PolicyError as exc:
            self._log(tool, args, "denied", str(exc))
            raise

    # ---- stage 1: read -----------------------------------------------------
    def search_issues(self, status: str | None = None, label: str | None = None) -> list[dict]:
        args = {"status": status, "label": label}
        self._guard(Stage.READ_ONLY, "search_issues", args)
        res = [i.public() for i in self.jira.search(status, label)]
        self._log("search_issues", args, "ok", f"{len(res)} issues")
        return res

    def get_issue(self, key: str) -> dict:
        self._guard(Stage.READ_ONLY, "get_issue", {"key": key})
        res = self.jira.get(key).public()
        self._log("get_issue", {"key": key}, "ok")
        return res

    # ---- stage 2: alerts ---------------------------------------------------
    def find_stale(self) -> list[dict]:
        """Open items without updates for more than policy.stale_after_days."""
        self._guard(Stage.ALERTS, "find_stale", {})
        now = self.clock()
        stale = []
        for i in self.jira.search():
            if i.status in self.policy.protected_statuses:
                continue
            idle = (now - i.updated).total_seconds() / 86400
            if idle > self.policy.stale_after_days:
                stale.append({**i.public(), "idle_days": round(idle, 1)})
        self._log("find_stale", {}, "ok", f"{len(stale)} stale")
        return stale

    # ---- stage 3/4: writes -------------------------------------------------
    def request_transition(self, key: str, to_status: str, reason: str) -> dict:
        """Apply directly if the policy allows (stage 4), otherwise queue for a human."""
        args = {"key": key, "to_status": to_status, "reason": reason}
        self._guard(Stage.HUMAN_APPROVED, "request_transition", args)
        issue = self.jira.get(key)
        if issue.status in self.policy.protected_statuses or to_status in self.policy.protected_statuses:
            self._log("request_transition", args, "denied", "protected status")
            raise PolicyError(f"status {issue.status!r} -> {to_status!r} is protected")
        if self.policy.can_auto_transition(issue.status, to_status) and self._budget_ok():
            self.jira.transition(key, to_status, self.clock())
            self._auto_writes += 1
            self._log("request_transition", args, "ok", "applied by policy")
            return {"applied": True, "issue": self.jira.get(key).public()}
        return self._queue(key, "transition", to_status, reason, "request_transition", args)

    def request_label(self, key: str, label: str, reason: str) -> dict:
        args = {"key": key, "label": label, "reason": reason}
        self._guard(Stage.HUMAN_APPROVED, "request_label", args)
        if self.policy.can_auto_label(label) and self._budget_ok():
            self.jira.add_label(key, label, self.clock())
            self._auto_writes += 1
            self._log("request_label", args, "ok", "applied by policy")
            return {"applied": True, "issue": self.jira.get(key).public()}
        return self._queue(key, "label", label, reason, "request_label", args)

    def _budget_ok(self) -> bool:
        return self._auto_writes < self.policy.max_auto_writes_per_run

    def _queue(self, key, action, value, reason, tool, args) -> dict:
        p = Proposal(next(self._ids), key, action, value, reason)
        self.proposals[p.id] = p
        self._log(tool, args, "queued", f"proposal #{p.id}")
        return {"applied": False, "proposal_id": p.id, "status": "pending human approval"}

    # ---- human side (not exposed to the LLM) -------------------------------
    def decide(self, proposal_id: int, approver: str, approve: bool) -> Proposal:
        p = self.proposals[proposal_id]
        if p.status != "pending":
            raise ValueError(f"proposal #{proposal_id} already {p.status}")
        if approve:
            if p.action == "transition":
                self.jira.transition(p.issue_key, p.value, self.clock())
            else:
                self.jira.add_label(p.issue_key, p.value, self.clock())
        p.status, p.decided_by = ("approved" if approve else "rejected"), approver
        self._log("decide", {"proposal_id": proposal_id}, p.status, actor=approver)
        return p
