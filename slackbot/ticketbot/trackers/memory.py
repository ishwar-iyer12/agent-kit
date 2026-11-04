"""In-memory tracker for tests and `--dry-run`. Behaves like Trello lists keyed by state."""

from __future__ import annotations

import itertools

from .base import Item, STATE_KEYS

DEFAULT_NAMES = {
    "ready": "Agent Ready",
    "needsSpec": "Needs Spec",
    "inProgress": "In Progress",
    "inReview": "In Review",
    "done": "Done",
}


class MemoryTracker:
    kind = "memory"

    def __init__(self, items: list[Item] | None = None, state_names: dict | None = None):
        self.state_names = {**DEFAULT_NAMES, **(state_names or {})}
        self.items: dict[str, Item] = {i.id: i for i in (items or [])}
        self._seq = itertools.count(1)
        self.comments: dict[str, list[str]] = {i.id: list(i.comments) for i in self.items.values()}

    def ping(self) -> str:
        return f"memory tracker, {len(self.items)} items"

    def search(self, query: str) -> list[Item]:
        q = query.lower().strip()
        terms = [t for t in q.split() if t]
        out = []
        for it in self.items.values():
            hay = f"{it.title}\n{it.description}".lower()
            if q and (q in hay or any(t in hay for t in terms)):
                out.append(it)
        return out[:10]

    def get(self, item_id: str) -> Item:
        if item_id not in self.items:
            raise KeyError(f"no item {item_id}")
        return self.items[item_id]

    def create(self, title, description, criteria, labels, state_key) -> Item:
        iid = f"M{next(self._seq)}"
        item = Item(
            id=iid,
            title=title,
            url=f"memory://{iid}",
            state_key=state_key,
            state_name=self.state_names[state_key],
            description=description,
            criteria=list(criteria),
            labels=list(labels),
        )
        self.items[iid] = item
        self.comments[iid] = []
        return item

    def update(self, item_id, title=None, description=None, add_criteria=None, labels=None) -> Item:
        it = self.get(item_id)
        if title is not None:
            it.title = title
        if description is not None:
            it.description = description
        if add_criteria:
            it.criteria.extend(add_criteria)
        if labels:
            it.labels = sorted(set(it.labels) | set(labels))
        return it

    def move(self, item_id, state_key) -> Item:
        if state_key not in STATE_KEYS:
            raise ValueError(state_key)
        it = self.get(item_id)
        it.state_key = state_key
        it.state_name = self.state_names[state_key]
        return it

    def comment(self, item_id, body) -> None:
        self.get(item_id)
        self.comments[item_id].append(body)
        self.items[item_id].comments.append(body)
