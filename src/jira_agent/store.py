"""In-memory Jira stand-in with synthetic issues.

Mirrors the shape of Jira REST API v3 fields we use. Swap `MockJira` for a
real client implementing the same three methods to go live.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

STATUSES = ["To Do", "In Progress", "Code Review", "Waiting to Test", "Testing", "Done"]


@dataclass
class JiraIssue:
    key: str
    summary: str
    status: str
    issue_type: str
    priority: str
    assignee_id: str  # pseudonymous ID only, never a name or e-mail
    updated: datetime
    labels: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "key": self.key,
            "summary": self.summary,
            "status": self.status,
            "type": self.issue_type,
            "priority": self.priority,
            "assignee": self.assignee_id,
            "updated": self.updated.isoformat(timespec="minutes"),
            "labels": list(self.labels),
        }


class MockJira:
    def __init__(self, issues: list[JiraIssue]):
        self._issues = {i.key: i for i in issues}

    def search(self, status: str | None = None, label: str | None = None) -> list[JiraIssue]:
        out = list(self._issues.values())
        if status:
            out = [i for i in out if i.status == status]
        if label:
            out = [i for i in out if label in i.labels]
        return sorted(out, key=lambda i: i.key)

    def get(self, key: str) -> JiraIssue:
        if key not in self._issues:
            raise KeyError(f"issue {key} not found")
        return self._issues[key]

    def transition(self, key: str, to_status: str, at: datetime) -> JiraIssue:
        if to_status not in STATUSES:
            raise ValueError(f"unknown status {to_status!r}")
        issue = self.get(key)
        issue.status = to_status
        issue.updated = at
        return issue

    def add_label(self, key: str, label: str, at: datetime) -> JiraIssue:
        issue = self.get(key)
        if label not in issue.labels:
            issue.labels.append(label)
        issue.updated = at
        return issue


SUMMARIES = [
    "Ajustar regra de conciliação", "Criar endpoint de consulta", "Corrigir cálculo de taxa",
    "Atualizar dashboard de squad", "Migrar job de extração", "Revisar política de retenção",
    "Automatizar relatório semanal", "Tratar erro de paginação", "Documentar fluxo de aprovação",
]


def sample_jira(n: int = 40, now: datetime | None = None, seed: int = 3) -> MockJira:
    rng = random.Random(seed)
    now = now or datetime(2026, 11, 27, 10, 0)
    issues = []
    for i in range(n):
        issues.append(
            JiraIssue(
                key=f"DEMO-{i + 1:03d}",
                summary=rng.choice(SUMMARIES),
                status=rng.choice(STATUSES),
                issue_type=rng.choice(["Story", "Bug", "Task"]),
                priority=rng.choice(["Low", "Medium", "High"]),
                assignee_id=f"user-{rng.randint(1, 6):02d}",
                updated=now - timedelta(days=rng.uniform(0, 20)),
            )
        )
    return MockJira(issues)
