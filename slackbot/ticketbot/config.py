"""Project resolution: Slack channel -> project -> agent.json -> tracker.

Config file shape (TICKETBOT_PROJECTS, default ./projects.json; same file the overnight runner uses,
plus optional `channels` per project and a top-level `defaultProject`):

    {
      "defaultProject": "agent-workflow-demo",
      "projects": [
        {"name": "agent-workflow-demo", "path": "C:/.../agent-workflow-demo", "enabled": true,
         "channels": ["#eng-demo", "C0123ABC"]}
      ]
    }

Each project's `<path>/agent.json` supplies tracker type, board/team and list/state names.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class Project:
    name: str
    path: Path
    agent: dict
    channels: list[str] = field(default_factory=list)
    enabled: bool = True

    @property
    def tracker_kind(self) -> str:
        return self.agent.get("tracker", "trello")

    @property
    def slack_channel(self) -> str | None:
        return self.agent.get("slackChannel")


@dataclass
class Settings:
    projects: list[Project]
    default_project: str | None = None

    def resolve(self, channel_id: str | None = None, channel_name: str | None = None) -> Project:
        """Pick the project for a Slack channel. Match by id or `#name`; fall back to defaultProject;
        if there is exactly one enabled project, use it."""
        wanted = {c for c in (channel_id, channel_name) if c}
        if channel_name and not channel_name.startswith("#"):
            wanted.add(f"#{channel_name}")
        for p in self.projects:
            if p.enabled and wanted & set(p.channels):
                return p
        if self.default_project:
            for p in self.projects:
                if p.name == self.default_project:
                    return p
            raise ConfigError(f"defaultProject '{self.default_project}' not in projects")
        enabled = [p for p in self.projects if p.enabled]
        if len(enabled) == 1:
            return enabled[0]
        raise ConfigError(
            f"No project mapped to channel {channel_name or channel_id!r} and no defaultProject set"
        )

    def by_name(self, name: str) -> Project:
        for p in self.projects:
            if p.name == name:
                return p
        raise ConfigError(f"Unknown project '{name}'")


def load_agent_json(path: Path) -> dict:
    f = path / "agent.json"
    if not f.exists():
        raise ConfigError(f"{f} not found (every project repo needs an agent.json at its root)")
    agent = json.loads(f.read_text(encoding="utf-8"))
    kind = agent.get("tracker")
    if kind not in ("trello", "linear"):
        raise ConfigError(f"{f}: tracker must be 'trello' or 'linear', got {kind!r}")
    if kind == "trello" and not (agent.get("trello") or {}).get("boardId"):
        raise ConfigError(f"{f}: trello.boardId missing")
    if kind == "linear" and not (agent.get("linear") or {}).get("teamKey"):
        raise ConfigError(f"{f}: linear.teamKey missing")
    return agent


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    p = Path(path or os.environ.get("TICKETBOT_PROJECTS") or "projects.json")
    if not p.exists():
        raise ConfigError(f"projects file {p} not found (set TICKETBOT_PROJECTS)")
    raw = json.loads(p.read_text(encoding="utf-8"))
    projects: list[Project] = []
    for entry in raw.get("projects", []):
        if not entry.get("enabled", True):
            continue
        repo = Path(entry["path"])
        projects.append(
            Project(
                name=entry["name"],
                path=repo,
                agent=load_agent_json(repo),
                channels=list(entry.get("channels", [])),
                enabled=True,
            )
        )
    if not projects:
        raise ConfigError(f"{p}: no enabled projects")
    return Settings(projects=projects, default_project=raw.get("defaultProject"))


def build_tracker(project: Project, env: os._Environ | dict = os.environ):
    """Instantiate the tracker adapter for a project from env credentials."""
    kind = project.tracker_kind
    if kind == "trello":
        from .trackers.trello import TrelloTracker

        key, token = env.get("TRELLO_KEY"), env.get("TRELLO_TOKEN")
        if not key or not token:
            raise ConfigError("TRELLO_KEY / TRELLO_TOKEN missing")
        return TrelloTracker(project.agent["trello"], key=key, token=token)
    if kind == "linear":
        from .trackers.linear import LinearTracker

        api_key = env.get("LINEAR_API_KEY")
        if not api_key:
            raise ConfigError("LINEAR_API_KEY missing")
        return LinearTracker(project.agent["linear"], api_key=api_key)
    raise ConfigError(f"unsupported tracker {kind!r}")
