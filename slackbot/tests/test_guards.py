import pytest

from ticketbot.trackers.base import Guarded, GuardError, Item, split_criteria, criteria_markdown
from ticketbot.trackers.memory import MemoryTracker


def seeded():
    return MemoryTracker([
        Item("M9", "Old card", "memory://M9", "inReview", "In Review", description="**Source**: https://s/p1"),
        Item("M8", "Open card", "memory://M8", "needsSpec", "Needs Spec"),
    ])


def test_refuses_edit_and_move_on_locked_items_but_allows_comment():
    g = Guarded(seeded())
    with pytest.raises(GuardError, match="In Review"):
        g.update("M9", title="x")
    with pytest.raises(GuardError):
        g.move("M9", "ready")
    g.comment("M9", "new info")
    assert g.actions == ["commented on M9"]


def test_create_cap_and_state_validation():
    g = Guarded(seeded(), max_creates=2)
    g.create("a", "d", ["c1"], [], "ready")
    g.create("b", "d", [], ["cloud"], "needsSpec")
    with pytest.raises(GuardError, match="cap"):
        g.create("c", "d", [], [], "ready")
    with pytest.raises(GuardError, match="state"):
        g.create("d", "d", [], [], "inReview")
    with pytest.raises(GuardError):
        g.move("M8", "done")
    assert len(g.created) == 2 and g.actions[0].startswith("created M1 (Agent Ready)")


def test_search_by_permalink_finds_source():
    g = Guarded(seeded())
    assert [i.id for i in g.search("https://s/p1")] == ["M9"]


def test_split_and_render_criteria_roundtrip():
    body = "**Source**: x\n\n## Acceptance criteria\n- [ ] one\n- [x] two\n\n## Notes\nmore"
    rest, crit = split_criteria(body)
    assert crit == ["one", "two"]
    assert "Acceptance criteria" not in rest and "## Notes" in rest
    assert criteria_markdown(["a"]) == "## Acceptance criteria\n- [ ] a"
