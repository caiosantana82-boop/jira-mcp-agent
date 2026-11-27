"""MCP server exposing GovernedJira tools to any MCP client (e.g. Claude).

    pip install -e ".[mcp]"
    AGENT_STAGE=2 python -m jira_agent.server

The human approval step (`decide`) is deliberately NOT exposed as a tool:
the model can propose, but only a person can approve.
"""

from __future__ import annotations

import os

from .governed import GovernedJira
from .policy import Policy, Stage
from .store import sample_jira


def build() -> GovernedJira:
    stage = Stage(int(os.getenv("AGENT_STAGE", "1")))
    return GovernedJira(jira=sample_jira(), policy=Policy(stage=stage))


def main() -> None:
    try:  # MCP Python SDK 2.x
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # SDK 1.x
        from mcp.server.fastmcp import FastMCP as Server

    gj = build()
    mcp = Server("governed-jira")

    @mcp.tool()
    def search_issues(status: str | None = None, label: str | None = None) -> list[dict]:
        """Search issues by status and/or label (stage 1+)."""
        return gj.search_issues(status, label)

    @mcp.tool()
    def get_issue(key: str) -> dict:
        """Read one issue (stage 1+)."""
        return gj.get_issue(key)

    @mcp.tool()
    def find_stale() -> list[dict]:
        """List open issues idle beyond the policy threshold (stage 2+)."""
        return gj.find_stale()

    @mcp.tool()
    def request_transition(key: str, to_status: str, reason: str) -> dict:
        """Move an issue. Applied only if policy allows; otherwise queued for human approval (stage 3+)."""
        return gj.request_transition(key, to_status, reason)

    @mcp.tool()
    def request_label(key: str, label: str, reason: str) -> dict:
        """Add a label. Applied only if policy allows; otherwise queued for human approval (stage 3+)."""
        return gj.request_label(key, label, reason)

    mcp.run()


if __name__ == "__main__":
    main()
