"""Tracker contract shared by Trello and Linear adapters, plus the guard rails the agent runs behind.

State keys mirror agent.json (`trello.lists` / `linear.states`):
ready, needsSpec, inProgress, inReview, done. Anything else maps to "other".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

STATE_KEYS = ("ready", "needsSpec", "inProgress", "inReview", "done")
LOCKED_STATES = {"inProgress", "inReview", "done"}  # the bot never edits or moves these
CREATABLE_STATES = {"ready", "needsSpec"}
CRITERIA_HEADING = "Acceptance criteria"


@dataclass
class Item:
    id: str
    title: str
    url: str
    state_key: str  # one of STATE_KEYS or "other"
    state_name: str
    description: str = ""
    criteria: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "state": self.state_name,
            "state_key": self.state_key,
            "labels": self.labels,
        }

    def full(self) -> dict:
        d = self.summary()
        d.update(description=self.description, acceptance_criteria=self.criteria, comments=self.comments)
        return d


class Tracker(Protocol):
    kind: str

    def ping(self) -> str: ...
    def search(self, query: str) -> list[Item]: ...
    def get(self, item_id: str) -> Item: ...
    def create(self, title: str, description: str, criteria: list[str], labels: list[str], state_key: str) -> Item: ...
    def update(
        self,
        item_id: str,
        title: str | None = None,
        description: str | None = None,
        add_criteria: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> Item: ...
    def move(self, item_id: str, state_key: str) -> Item: ...
    def comment(self, item_id: str, body: str) -> None: ...


class GuardError(Exception):
    """Raised when the agent asks for something the policy forbids. Returned to the model as a tool error."""


class Guarded:
    """Policy wrapper: no edits to locked items, create cap per run, only ready/needsSpec as targets."""

    def __init__(self, inner: Tracker, max_creates: int = 3):
        self.inner = inner
        self.kind = inner.kind
        self.max_creates = max_creates
        self.created: list[Item] = []
        self.updated: list[Item] = []
        self.actions: list[str] = []

    def ping(self) -> str:
        return self.inner.ping()

    def search(self, query: str) -> list[Item]:
        return self.inner.search(query)

    def get(self, item_id: str) -> Item:
        return self.inner.get(item_id)

    def _unlocked(self, item_id: str, verb: str) -> Item:
        item = self.inner.get(item_id)
        if item.state_key in LOCKED_STATES:
            raise GuardError(
                f"Refusing to {verb} {item.id}: it is in '{item.state_name}', which humans own. "
                "Leave a comment instead."
            )
        return item

    def create(self, title: str, description: str, criteria: list[str], labels: list[str], state_key: str) -> Item:
        if state_key not in CREATABLE_STATES:
            raise GuardError(f"state must be one of {sorted(CREATABLE_STATES)}, got {state_key!r}")
        if len(self.created) >= self.max_creates:
            raise GuardError(f"Create cap reached ({self.max_creates} per request). Ask the human to split the work.")
        if not title.strip():
            raise GuardError("title is empty")
        item = self.inner.create(title.strip(), description, criteria, labels, state_key)
        self.created.append(item)
        self.actions.append(f"created {item.id} ({item.state_name})")
        return item

    def update(self, item_id, title=None, description=None, add_criteria=None, labels=None) -> Item:
        self._unlocked(item_id, "edit")
        item = self.inner.update(item_id, title=title, description=description, add_criteria=add_criteria, labels=labels)
        self.updated.append(item)
        self.actions.append(f"updated {item.id}")
        return item

    def move(self, item_id: str, state_key: str) -> Item:
        if state_key not in CREATABLE_STATES:
            raise GuardError(f"Can only move to {sorted(CREATABLE_STATES)}; '{state_key}' is for humans")
        self._unlocked(item_id, "move")
        item = self.inner.move(item_id, state_key)
        self.actions.append(f"moved {item.id} -> {item.state_name}")
        return item

    def comment(self, item_id: str, body: str) -> None:
        if not body.strip():
            raise GuardError("comment body is empty")
        self.inner.comment(item_id, body)
        self.actions.append(f"commented on {item_id}")


def render_description(source: str, layer: str, notes: str) -> str:
    """The shared card body format (same as prompts/intake-triage.md)."""
    return f"**Source**: {source}\n\n**Layer**: {layer}\n\n**Notes**:\n{notes}".strip()


def criteria_markdown(criteria: list[str]) -> str:
    if not criteria:
        return ""
    return f"## {CRITERIA_HEADING}\n" + "\n".join(f"- [ ] {c}" for c in criteria)


def split_criteria(description: str) -> tuple[str, list[str]]:
    """Split a markdown body into (body without criteria section, criteria list). Used by Linear."""
    lines = description.splitlines()
    body: list[str] = []
    crit: list[str] = []
    in_section = False
    for line in lines:
        if line.strip().lower().lstrip("#").strip() == CRITERIA_HEADING.lower() and line.lstrip().startswith("#"):
            in_section = True
            continue
        if in_section:
            s = line.strip()
            if s.startswith("#"):
                in_section = False
                body.append(line)
                continue
            if s.startswith(("- [ ]", "- [x]", "- [X]")):
                crit.append(s[5:].strip())
                continue
            if s.startswith("- "):
                crit.append(s[2:].strip())
                continue
            if not s:
                continue
            in_section = False
        body.append(line)
    return "\n".join(body).rstrip(), crit
