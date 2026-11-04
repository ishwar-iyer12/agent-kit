import httpx
import respx

from tests.conftest import TRELLO_CFG
from ticketbot.trackers.trello import BASE, TrelloTracker

LISTS = [{"id": "L1", "name": "Agent Ready"}, {"id": "L2", "name": "Needs Spec"}, {"id": "L3", "name": "In Review"},
         {"id": "L4", "name": "In Progress"}, {"id": "L5", "name": "Done"}]
LABELS = [{"id": "LB1", "name": "cloud", "color": "sky"}]


def tracker():
    return TrelloTracker(TRELLO_CFG, key="k", token="t", client=httpx.Client(base_url=BASE))


def card(short="abc123", list_id="L2", labels=None):
    return {"id": "ID" + short, "shortLink": short, "shortUrl": f"https://trello.com/c/{short}", "name": "Title",
            "desc": "**Source**: https://s/p", "idList": list_id, "labels": labels or [], "idBoard": "board1"}


@respx.mock(base_url=BASE, assert_all_called=False)
def test_create_with_checklist_and_new_label(respx_mock):
    respx_mock.get("/boards/board1/lists").respond(json=LISTS)
    respx_mock.get("/boards/board1/labels").respond(json=LABELS)
    new_label = respx_mock.post("/labels").respond(json={"id": "LB2", "name": "client:acme"})
    create = respx_mock.post("/cards").respond(json=card())
    checklist = respx_mock.post("/cards/IDabc123/checklists").respond(json={"id": "CL1"})
    items = respx_mock.post("/checklists/CL1/checkItems").respond(json={"id": "CI"})
    respx_mock.get("/cards/abc123").respond(json={**card(), "checklists": [
        {"id": "CL1", "name": "Acceptance criteria", "checkItems": [{"name": "c1", "pos": 1}, {"name": "c2", "pos": 2}]}],
        "actions": [{"type": "commentCard", "data": {"text": "hi"}}]})

    item = tracker().create("Title", "**Source**: https://s/p", ["c1", "c2"], ["cloud", "client:acme"], "needsSpec")

    assert new_label.called
    q = create.calls[0].request.url.params
    assert q["idList"] == "L2" and q["key"] == "k" and set(q["idLabels"].split(",")) == {"LB1", "LB2"}
    assert checklist.called and items.call_count == 2
    assert item.id == "abc123" and item.state_key == "needsSpec" and item.criteria == ["c1", "c2"] and item.comments == ["hi"]


@respx.mock(base_url=BASE, assert_all_called=False)
def test_search_scoped_to_board_and_state_mapping(respx_mock):
    respx_mock.get("/boards/board1/lists").respond(json=LISTS)
    search = respx_mock.get("/search").respond(json={"cards": [card(list_id="L3")]})
    res = tracker().search("https://s/p")
    assert search.calls[0].request.url.params["idBoards"] == "board1"
    assert res[0].state_key == "inReview" and res[0].state_name == "In Review"


@respx.mock(base_url=BASE, assert_all_called=False)
def test_move_and_update_add_criteria(respx_mock):
    respx_mock.get("/boards/board1/lists").respond(json=LISTS)
    put = respx_mock.put("/cards/abc123").respond(json=card(list_id="L1"))
    respx_mock.get("/cards/abc123").respond(json={**card(list_id="L1"), "checklists": [{"id": "CL1", "name": "Acceptance criteria", "checkItems": []}]})
    add = respx_mock.post("/checklists/CL1/checkItems").respond(json={})
    t = tracker()
    assert t.move("abc123", "ready").state_key == "ready"
    assert put.calls[0].request.url.params["idList"] == "L1"
    t.update("abc123", add_criteria=["c3"])
    assert add.called and add.calls[0].request.url.params["name"] == "c3"


@respx.mock(base_url=BASE, assert_all_called=False)
def test_ping_reports_missing_lists(respx_mock):
    respx_mock.get("/boards/board1").respond(json={"name": "Demo", "url": "https://trello.com/b/x"})
    respx_mock.get("/boards/board1/lists").respond(json=LISTS[:2])
    try:
        tracker().ping()
    except RuntimeError as e:
        assert "In Progress" in str(e)
    else:
        raise AssertionError("expected missing-list error")
