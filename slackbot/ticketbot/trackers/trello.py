"""Trello adapter. REST v1 with key/token. Lists and labels resolved by name per agent.json.trello.

Card ids: we expose the shortLink (what appears in https://trello.com/c/<shortLink>); Trello accepts it
wherever a card id is expected.
"""

from __future__ import annotations

import httpx

from .base import CRITERIA_HEADING, Item

BASE = "https://api.trello.com/1"
CARD_FIELDS = "name,desc,idList,labels,shortLink,shortUrl,idBoard"


class TrelloTracker:
    kind = "trello"

    def __init__(self, cfg: dict, key: str, token: str, client: httpx.Client | None = None):
        self.board_id = cfg["boardId"]
        self.list_names: dict[str, str] = dict(cfg.get("lists") or {})  # state_key -> list name
        self.http = client or httpx.Client(base_url=BASE, timeout=20.0)
        self._auth = {"key": key, "token": token}
        self._lists: dict[str, str] | None = None  # name -> id
        self._labels: dict[str, str] | None = None  # name -> id

    # -- http -------------------------------------------------------------
    def _req(self, method: str, path: str, params: dict | None = None, json: dict | None = None):
        r = self.http.request(method, path, params={**self._auth, **(params or {})}, json=json)
        if r.status_code >= 400:
            raise RuntimeError(f"Trello {method} {path} -> {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    # -- lookups ----------------------------------------------------------
    def lists(self) -> dict[str, str]:
        if self._lists is None:
            data = self._req("GET", f"/boards/{self.board_id}/lists", {"fields": "name"})
            self._lists = {l["name"]: l["id"] for l in data}
        return self._lists

    def list_id(self, state_key: str) -> str:
        name = self.list_names.get(state_key)
        if not name:
            raise RuntimeError(f"agent.json trello.lists has no '{state_key}'")
        lid = self.lists().get(name)
        if not lid:
            raise RuntimeError(f"Board has no list named '{name}'")
        return lid

    def state_key_for_list(self, list_id: str) -> tuple[str, str]:
        id_to_name = {v: k for k, v in self.lists().items()}
        name = id_to_name.get(list_id, "?")
        for key, lname in self.list_names.items():
            if lname == name:
                return key, name
        return "other", name

    def labels(self) -> dict[str, str]:
        if self._labels is None:
            data = self._req("GET", f"/boards/{self.board_id}/labels", {"fields": "name,color", "limit": 1000})
            self._labels = {l["name"]: l["id"] for l in data if l.get("name")}
        return self._labels

    def label_ids(self, names: list[str]) -> list[str]:
        out = []
        for n in names:
            n = n.strip()
            if not n:
                continue
            if n not in self.labels():
                created = self._req("POST", "/labels", {"name": n, "color": "null", "idBoard": self.board_id})
                self._labels[n] = created["id"]
            out.append(self._labels[n])
        return out

    # -- mapping ----------------------------------------------------------
    def _item(self, card: dict, checklists: list[dict] | None = None, actions: list[dict] | None = None) -> Item:
        state_key, state_name = self.state_key_for_list(card.get("idList", ""))
        criteria: list[str] = []
        for cl in checklists or []:
            if cl.get("name", "").lower() == CRITERIA_HEADING.lower():
                criteria = [ci["name"] for ci in sorted(cl.get("checkItems", []), key=lambda c: c.get("pos", 0))]
        comments = [a["data"]["text"] for a in (actions or []) if a.get("type") == "commentCard"][:5]
        return Item(
            id=card["shortLink"],
            title=card["name"],
            url=card.get("shortUrl") or f"https://trello.com/c/{card['shortLink']}",
            state_key=state_key,
            state_name=state_name,
            description=card.get("desc", ""),
            criteria=criteria,
            labels=[l["name"] for l in card.get("labels", []) if l.get("name")],
            comments=comments,
        )

    # -- contract ---------------------------------------------------------
    def ping(self) -> str:
        board = self._req("GET", f"/boards/{self.board_id}", {"fields": "name,url"})
        missing = [n for n in self.list_names.values() if n not in self.lists()]
        if missing:
            raise RuntimeError(f"Board '{board['name']}' is missing lists: {missing}")
        return f"Trello board '{board['name']}' ({board['url']}), lists ok"

    def search(self, query: str) -> list[Item]:
        data = self._req(
            "GET",
            "/search",
            {
                "query": query[:200],
                "idBoards": self.board_id,
                "modelTypes": "cards",
                "card_fields": CARD_FIELDS,
                "cards_limit": 10,
                "partial": "true",
            },
        )
        return [self._item(c) for c in data.get("cards", [])]

    def get(self, item_id: str) -> Item:
        card = self._req(
            "GET",
            f"/cards/{item_id}",
            {"fields": CARD_FIELDS, "checklists": "all", "actions": "commentCard", "actions_limit": 5},
        )
        return self._item(card, card.get("checklists"), card.get("actions"))

    def create(self, title, description, criteria, labels, state_key) -> Item:
        params = {"idList": self.list_id(state_key), "name": title, "desc": description, "pos": "bottom"}
        ids = self.label_ids(labels)
        if ids:
            params["idLabels"] = ",".join(ids)
        card = self._req("POST", "/cards", params)
        if criteria:
            self._add_criteria(card["id"], None, criteria)
        return self.get(card["shortLink"])

    def _add_criteria(self, card_id: str, checklists: list[dict] | None, criteria: list[str]) -> None:
        cl_id = None
        for cl in checklists or []:
            if cl.get("name", "").lower() == CRITERIA_HEADING.lower():
                cl_id = cl["id"]
        if cl_id is None:
            cl = self._req("POST", f"/cards/{card_id}/checklists", {"name": CRITERIA_HEADING})
            cl_id = cl["id"]
        for c in criteria:
            if c.strip():
                self._req("POST", f"/checklists/{cl_id}/checkItems", {"name": c.strip(), "pos": "bottom"})

    def update(self, item_id, title=None, description=None, add_criteria=None, labels=None) -> Item:
        params: dict = {}
        if title is not None:
            params["name"] = title
        if description is not None:
            params["desc"] = description
        if labels:
            current = self._req("GET", f"/cards/{item_id}", {"fields": "idLabels"})
            params["idLabels"] = ",".join(sorted(set(current.get("idLabels", [])) | set(self.label_ids(labels))))
        if params:
            self._req("PUT", f"/cards/{item_id}", params)
        if add_criteria:
            card = self._req("GET", f"/cards/{item_id}", {"fields": "id", "checklists": "all"})
            self._add_criteria(card["id"], card.get("checklists"), add_criteria)
        return self.get(item_id)

    def move(self, item_id, state_key) -> Item:
        self._req("PUT", f"/cards/{item_id}", {"idList": self.list_id(state_key), "pos": "bottom"})
        return self.get(item_id)

    def comment(self, item_id, body) -> None:
        self._req("POST", f"/cards/{item_id}/actions/comments", {"text": body})
