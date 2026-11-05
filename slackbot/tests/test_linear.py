import json

import httpx
import respx

from tests.conftest import LINEAR_CFG
from ticketbot.trackers.linear import URL, LinearTracker

TEAM = {"teams": {"nodes": [{"id": "T1", "name": "TrustLayer", "key": "TL",
        "states": {"nodes": [{"id": "S1", "name": "Todo"}, {"id": "S2", "name": "Backlog"}, {"id": "S3", "name": "In Review"},
                             {"id": "S4", "name": "In Progress"}, {"id": "S5", "name": "Done"}]},
        "labels": {"nodes": [{"id": "LB1", "name": "agent-ready"}]}}]}}


def issue(ident="TL-7", state="Backlog", desc="**Source**: https://s/p\n\n## Acceptance criteria\n- [ ] one"):
    return {"id": "uuid-" + ident, "identifier": ident, "title": "Title", "description": desc,
            "url": f"https://linear.app/x/issue/{ident}", "state": {"id": "S", "name": state}, "labels": {"nodes": []},
            "comments": {"nodes": [{"body": "c"}]}}


def router(responses):
    """Route GraphQL by operation keyword; records variables."""
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        q = body["query"]
        for key, data in responses:
            if key in q:
                return httpx.Response(200, json={"data": data})
        return httpx.Response(200, json={"errors": [{"message": f"unrouted: {q[:40]}"}]})

    return handler, seen


@respx.mock
def test_create_adds_ready_label_and_criteria_section():
    handler, seen = router([("teams(", TEAM), ("issueLabelCreate", {"issueLabelCreate": {"issueLabel": {"id": "LB2"}}}),
                            ("issueCreate", {"issueCreate": {"success": True, "issue": issue(state="Todo")}})])
    respx.post(URL).mock(side_effect=handler)
    t = LinearTracker(LINEAR_CFG, api_key="key")
    item = t.create("Title", "**Source**: https://s/p", ["one", "two"], ["client:acme"], "ready")
    create_vars = [s for s in seen if "issueCreate" in s["query"]][0]["variables"]["input"]
    assert create_vars["stateId"] == "S1" and set(create_vars["labelIds"]) == {"LB1", "LB2"}
    assert "## Acceptance criteria\n- [ ] one\n- [ ] two" in create_vars["description"]
    assert item.state_key == "ready" and item.criteria == ["one"]


@respx.mock
def test_update_appends_criteria_and_keeps_body():
    handler, seen = router([("teams(", TEAM), ("issue(id", {"issue": issue()}), ("issueUpdate", {"issueUpdate": {"success": True}})])
    respx.post(URL).mock(side_effect=handler)
    t = LinearTracker(LINEAR_CFG, api_key="key")
    t.update("TL-7", add_criteria=["two"])
    upd = [s for s in seen if "issueUpdate" in s["query"]][0]["variables"]
    assert upd["id"] == "uuid-TL-7"
    assert upd["input"]["description"] == "**Source**: https://s/p\n\n## Acceptance criteria\n- [ ] one\n- [ ] two"


@respx.mock
def test_search_scoped_to_team_and_state_keys():
    handler, seen = router([("teams(", TEAM), ("searchIssues", {"searchIssues": {"nodes": [issue(state="In Review")]}})])
    respx.post(URL).mock(side_effect=handler)
    res = LinearTracker(LINEAR_CFG, api_key="key").search("https://s/p")
    assert res[0].state_key == "inReview" and res[0].id == "TL-7"
    assert [s for s in seen if "searchIssues" in s["query"]][0]["variables"]["key"] == "TL"


@respx.mock
def test_auth_header_and_graphql_errors_raise():
    respx.post(URL).mock(return_value=httpx.Response(200, json={"errors": [{"message": "nope"}]}))
    t = LinearTracker(LINEAR_CFG, api_key="lin_key")
    try:
        t.ping()
    except RuntimeError as e:
        assert "nope" in str(e)
    assert respx.calls.last.request.headers["Authorization"] == "lin_key"


@respx.mock
def test_update_remove_criteria_recomposes_description():
    handler, seen = router([("teams(", TEAM), ("issue(id", {"issue": issue()}), ("issueUpdate", {"issueUpdate": {"success": True}})])
    respx.post(URL).mock(side_effect=handler)
    t = LinearTracker(LINEAR_CFG, api_key="key")
    t.update("TL-7", remove_criteria=["one"], add_criteria=["two"])
    upd = [s for s in seen if "issueUpdate" in s["query"]][0]["variables"]
    assert upd["input"]["description"] == "**Source**: https://s/p\n\n## Acceptance criteria\n- [ ] two"
