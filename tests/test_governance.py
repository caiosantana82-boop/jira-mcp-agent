import json
from datetime import datetime, timedelta

import pytest

from jira_agent.governed import GovernedJira
from jira_agent.policy import Policy, PolicyError, Stage
from jira_agent.store import JiraIssue, MockJira

NOW = datetime(2026, 11, 27, 10, 0)


def jira():
    return MockJira([
        JiraIssue("DEMO-001", "a", "Code Review", "Story", "High", "user-01", NOW - timedelta(days=8)),
        JiraIssue("DEMO-002", "b", "In Progress", "Bug", "Low", "user-02", NOW - timedelta(days=1)),
        JiraIssue("DEMO-003", "c", "Done", "Task", "Low", "user-03", NOW - timedelta(days=30)),
    ])


def agent(stage):
    return GovernedJira(jira(), Policy(stage=stage), clock=lambda: NOW)


def test_stage1_reads_but_cannot_alert_or_write():
    a = agent(Stage.READ_ONLY)
    assert len(a.search_issues()) == 3
    with pytest.raises(PolicyError):
        a.find_stale()
    with pytest.raises(PolicyError):
        a.request_transition("DEMO-001", "Waiting to Test", "r")
    assert [e.outcome for e in a.audit] == ["ok", "denied", "denied"]


def test_stage2_flags_stale_but_ignores_done():
    stale = agent(Stage.ALERTS).find_stale()
    assert [s["key"] for s in stale] == ["DEMO-001"]


def test_stage3_queues_every_write_until_a_human_decides():
    a = agent(Stage.HUMAN_APPROVED)
    res = a.request_transition("DEMO-001", "Waiting to Test", "review done")
    assert res["applied"] is False
    assert a.jira.get("DEMO-001").status == "Code Review"  # untouched
    a.decide(res["proposal_id"], approver="po-01", approve=True)
    assert a.jira.get("DEMO-001").status == "Waiting to Test"
    assert a.audit[-1].actor == "po-01" and a.audit[-1].outcome == "approved"


def test_stage3_rejection_changes_nothing_and_cannot_be_reused():
    a = agent(Stage.HUMAN_APPROVED)
    pid = a.request_label("DEMO-002", "blocked", "r")["proposal_id"]
    a.decide(pid, "sm-01", approve=False)
    assert "blocked" not in a.jira.get("DEMO-002").labels
    with pytest.raises(ValueError):
        a.decide(pid, "sm-01", approve=True)


def test_stage4_applies_only_whitelisted_writes():
    a = agent(Stage.POLICY_GOVERNED)
    auto = a.request_transition("DEMO-001", "Waiting to Test", "review done")
    assert auto["applied"] is True
    other = a.request_transition("DEMO-002", "Testing", "skip review")
    assert other["applied"] is False and "proposal_id" in other


def test_protected_status_is_never_touched_even_at_stage4():
    a = agent(Stage.POLICY_GOVERNED)
    with pytest.raises(PolicyError):
        a.request_transition("DEMO-003", "In Progress", "reopen")
    with pytest.raises(PolicyError):
        a.request_transition("DEMO-002", "Done", "close")


def test_auto_write_budget_falls_back_to_approval():
    a = GovernedJira(jira(), Policy(stage=Stage.POLICY_GOVERNED, max_auto_writes_per_run=1), clock=lambda: NOW)
    assert a.request_label("DEMO-001", "stale", "idle")["applied"] is True
    assert a.request_label("DEMO-002", "stale", "idle")["applied"] is False


def test_audit_is_valid_jsonl_and_has_no_personal_names():
    a = agent(Stage.ALERTS)
    a.search_issues()
    a.find_stale()
    lines = [json.loads(l) for l in a.audit_jsonl().splitlines()]
    assert {l["tool"] for l in lines} == {"search_issues", "find_stale"}
    assert all(i["assignee"].startswith("user-") for i in a.search_issues())
