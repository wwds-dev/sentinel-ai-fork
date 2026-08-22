import json
import re
from datetime import datetime
from services.database import get_connection


def _row_to_agent(row) -> dict:
    d = dict(row)
    d["allowed_providers"] = json.loads(d.get("allowed_providers") or "[]")
    raw_tools = d.get("allowed_tools")
    d["allowed_tools"] = json.loads(raw_tools) if raw_tools is not None else None
    d["enabled"] = bool(d.get("enabled", 1))
    d["requires_approval"] = bool(d.get("requires_approval", 0))
    d["auto_generated"] = bool(d.get("auto_generated", 0))
    return d


def _row_to_tool(row) -> dict:
    d = dict(row)
    d["allowed_providers"] = json.loads(d.get("allowed_providers") or "[]")
    d["enabled"] = bool(d.get("enabled", 1))
    d["requires_approval"] = bool(d.get("requires_approval", 0))
    return d


class Registry:
    def list_projects(self, include_archived: bool = False) -> list[dict]:
        where = "" if include_archived else "WHERE archived = 0"
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM projects {where} ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str | None) -> dict | None:
        if not project_id:
            return None
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_project(self, project: dict) -> dict:
        name = str(project.get("name") or "Untitled project").strip()
        project_id = str(project.get("id") or "").strip()
        if not project_id:
            project_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
            base = project_id
            n = 2
            while self.get_project(project_id):
                project_id, n = f"{base}-{n}", n + 1
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, instructions, default_agent, default_provider,
                    default_model, budget_eur, archived, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, instructions=excluded.instructions,
                     default_agent=excluded.default_agent,
                     default_provider=excluded.default_provider,
                     default_model=excluded.default_model,
                     budget_eur=excluded.budget_eur, archived=excluded.archived""",
                (
                    project_id, name, str(project.get("instructions") or ""),
                    str(project.get("default_agent") or "chat"),
                    str(project.get("default_provider") or ""),
                    str(project.get("default_model") or ""),
                    project.get("budget_eur"), 1 if project.get("archived") else 0,
                    str(project.get("created_at") or datetime.now().isoformat(timespec="seconds")),
                ),
            )
            conn.commit()
        return self.get_project(project_id)

    def archive_project(self, project_id: str, archived: bool = True) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE projects SET archived = ? WHERE id = ?",
                (1 if archived else 0, project_id),
            )
            conn.commit()

    def get_agent(self, name: str) -> dict | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE name = ?", (name,)
            ).fetchone()
        return _row_to_agent(row) if row else None

    def get_tool(self, name: str) -> dict | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tools WHERE name = ?", (name,)
            ).fetchone()
        return _row_to_tool(row) if row else None

    def list_agents(self) -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY name").fetchall()
        return [_row_to_agent(r) for r in rows]

    def list_tools(self) -> list[dict]:
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM tools ORDER BY name").fetchall()
        return [_row_to_tool(r) for r in rows]

    def is_agent_enabled(self, name: str) -> bool:
        a = self.get_agent(name)
        return bool(a and a.get("enabled", False))

    def is_tool_enabled(self, name: str) -> bool:
        t = self.get_tool(name)
        return bool(t and t.get("enabled", False))

    def agent_allows_provider(self, agent_name: str, provider: str) -> bool:
        a = self.get_agent(agent_name)
        if not a:
            return False
        allowed = a.get("allowed_providers", [])
        return not allowed or provider in allowed

    def tool_allows_provider(self, tool_name: str, provider: str) -> bool:
        t = self.get_tool(tool_name)
        if not t:
            return True
        allowed = t.get("allowed_providers", [])
        return not allowed or provider in allowed

    def agent_allows_tool(self, agent_name: str, tool_name: str) -> bool:
        a = self.get_agent(agent_name)
        if not a:
            return False
        allowed_tools = a.get("allowed_tools")
        if allowed_tools is None:
            return True
        return tool_name in allowed_tools

    def get_agent_budget(self, agent_name: str) -> float | None:
        a = self.get_agent(agent_name)
        if not a:
            return None
        limit = a.get("budget_limit_eur")
        return float(limit) if limit is not None else None

    def agent_requires_approval(self, agent_name: str) -> bool:
        a = self.get_agent(agent_name)
        return bool(a and a.get("requires_approval", False))
