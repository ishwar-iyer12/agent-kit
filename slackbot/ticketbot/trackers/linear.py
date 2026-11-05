"""Linear adapter. GraphQL with a personal/OAuth API key. States and labels resolved by name on the team
per agent.json.linear. Acceptance criteria live in the description under `## Acceptance criteria` as
`- [ ]` items (Linear renders them as a checklist).
"""

from __future__ import annotations

import httpx

from .base import Item, criteria_markdown, criterion_matches, split_criteria

URL = "https://api.linear.app/graphql"

ISSUE_FIELDS = """
  id identifier title description url
  state { id name }
  labels { nodes { id name } }
"""


class LinearTracker:
    kind = "linear"

    def __init__(self, cfg: dict, api_key: str, client: httpx.Client | None = None):
        self.team_key = cfg["teamKey"]
        self.state_names: dict[str, str] = dict(cfg.get("states") or {})  # state_key -> state name
        self.ready_label = cfg.get("readyLabel")
        self.http = client or httpx.Client(timeout=20.0)
        self._headers = {"Authorization": api_key, "Content-Type": "application/json"}
        self._team: dict | None = None

    # -- http -------------------------------------------------------------
    def _gql(self, query: str, variables: dict | None = None) -> dict:
        r = self.http.post(URL, headers=self._headers, json={"query": query, "variables": variables or {}})
        if r.status_code >= 400:
            raise RuntimeError(f"Linear HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if data.get("errors"):
            raise RuntimeError("Linear: " + "; ".join(e.get("message", "?") for e in data["errors"]))
        return data["data"]

    # -- lookups ----------------------------------------------------------
    def team(self) -> dict:
        if self._team is None:
            d = self._gql(
                """query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes {
                     id name key states { nodes { id name } } labels { nodes { id name } } } } }""",
                {"key": self.team_key},
            )
            nodes = d["teams"]["nodes"]
            if not nodes:
                raise RuntimeError(f"Linear team '{self.team_key}' not found")
            t = nodes[0]
            self._team = {
                "id": t["id"],
                "name": t["name"],
                "states": {s["name"]: s["id"] for s in t["states"]["nodes"]},
                "labels": {l["name"]: l["id"] for l in t["labels"]["nodes"]},
            }
        return self._team

    def state_id(self, state_key: str) -> str:
        name = self.state_names.get(state_key)
        if not name:
            raise RuntimeError(f"agent.json linear.states has no '{state_key}'")
        sid = self.team()["states"].get(name)
        if not sid:
            raise RuntimeError(f"Team {self.team_key} has no state '{name}'")
        return sid

    def state_key_for(self, state_name: str) -> str:
        for key, name in self.state_names.items():
            if name == state_name:
                return key
        return "other"

    def label_ids(self, names: list[str]) -> list[str]:
        labels = self.team()["labels"]
        out = []
        for n in names:
            n = n.strip()
            if not n:
                continue
            if n not in labels:
                d = self._gql(
                    """mutation($name: String!, $teamId: String!) {
                         issueLabelCreate(input: { name: $name, teamId: $teamId }) { issueLabel { id } } }""",
                    {"name": n, "teamId": self.team()["id"]},
                )
                labels[n] = d["issueLabelCreate"]["issueLabel"]["id"]
            out.append(labels[n])
        return out

    # -- mapping ----------------------------------------------------------
    def _item(self, issue: dict, comments: list[str] | None = None) -> Item:
        body, criteria = split_criteria(issue.get("description") or "")
        state_name = (issue.get("state") or {}).get("name", "?")
        return Item(
            id=issue["identifier"],
            title=issue["title"],
            url=issue["url"],
            state_key=self.state_key_for(state_name),
            state_name=state_name,
            description=body,
            criteria=criteria,
            labels=[l["name"] for l in (issue.get("labels") or {}).get("nodes", [])],
            comments=comments or [],
        )

    @staticmethod
    def _compose(body: str, criteria: list[str]) -> str:
        return (body.rstrip() + ("\n\n" + criteria_markdown(criteria) if criteria else "")).strip()

    # -- contract ---------------------------------------------------------
    def ping(self) -> str:
        t = self.team()
        missing = [n for n in self.state_names.values() if n not in t["states"]]
        if missing:
            raise RuntimeError(f"Team '{t['name']}' is missing states: {missing}")
        return f"Linear team '{t['name']}' ({self.team_key}), states ok"

    def search(self, query: str) -> list[Item]:
        d = self._gql(
            f"""query($term: String!, $key: String!) {{
                  searchIssues(term: $term, first: 10, filter: {{ team: {{ key: {{ eq: $key }} }} }}) {{
                    nodes {{ {ISSUE_FIELDS} }} }} }}""",
            {"term": query[:200], "key": self.team_key},
        )
        return [self._item(i) for i in d["searchIssues"]["nodes"]]

    def _raw(self, item_id: str) -> dict:
        d = self._gql(
            f"""query($id: String!) {{ issue(id: $id) {{ {ISSUE_FIELDS}
                  comments(first: 5) {{ nodes {{ body }} }} }} }}""",
            {"id": item_id},
        )
        if not d.get("issue"):
            raise RuntimeError(f"Linear issue {item_id} not found")
        return d["issue"]

    def get(self, item_id: str) -> Item:
        issue = self._raw(item_id)
        return self._item(issue, [c["body"] for c in issue["comments"]["nodes"]])

    def create(self, title, description, criteria, labels, state_key) -> Item:
        names = list(labels)
        if state_key == "ready" and self.ready_label and self.ready_label not in names:
            names.append(self.ready_label)
        d = self._gql(
            f"""mutation($input: IssueCreateInput!) {{
                  issueCreate(input: $input) {{ success issue {{ {ISSUE_FIELDS} }} }} }}""",
            {
                "input": {
                    "teamId": self.team()["id"],
                    "title": title,
                    "description": self._compose(description, criteria),
                    "stateId": self.state_id(state_key),
                    "labelIds": self.label_ids(names),
                }
            },
        )
        return self._item(d["issueCreate"]["issue"])

    def update(self, item_id, title=None, description=None, add_criteria=None, labels=None, remove_criteria=None) -> Item:
        issue = self._raw(item_id)
        body, criteria = split_criteria(issue.get("description") or "")
        inp: dict = {}
        if title is not None:
            inp["title"] = title
        if description is not None or add_criteria or remove_criteria:
            new_body = description if description is not None else body
            kept = [c for c in criteria if not any(criterion_matches(c, r) for r in (remove_criteria or []))]
            new_crit = kept + [c for c in (add_criteria or []) if c.strip()]
            inp["description"] = self._compose(new_body, new_crit)
        if labels:
            existing = [l["id"] for l in issue["labels"]["nodes"]]
            inp["labelIds"] = sorted(set(existing) | set(self.label_ids(labels)))
        if inp:
            self._gql(
                """mutation($id: String!, $input: IssueUpdateInput!) {
                     issueUpdate(id: $id, input: $input) { success } }""",
                {"id": issue["id"], "input": inp},
            )
        return self.get(item_id)

    def move(self, item_id, state_key) -> Item:
        issue = self._raw(item_id)
        inp: dict = {"stateId": self.state_id(state_key)}
        if state_key == "ready" and self.ready_label:
            existing = [l["id"] for l in issue["labels"]["nodes"]]
            inp["labelIds"] = sorted(set(existing) | set(self.label_ids([self.ready_label])))
        self._gql(
            """mutation($id: String!, $input: IssueUpdateInput!) {
                 issueUpdate(id: $id, input: $input) { success } }""",
            {"id": issue["id"], "input": inp},
        )
        return self.get(item_id)

    def comment(self, item_id, body) -> None:
        issue = self._raw(item_id)
        self._gql(
            """mutation($issueId: String!, $body: String!) {
                 commentCreate(input: { issueId: $issueId, body: $body }) { success } }""",
            {"issueId": issue["id"], "body": body},
        )
