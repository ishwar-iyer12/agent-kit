"""Agent loop against a scripted fake Claude client. No network."""

from types import SimpleNamespace as NS

from ticketbot import agent
from ticketbot.trackers.base import Guarded, Item
from ticketbot.trackers.memory import MemoryTracker


def usage(i=100, o=20, cr=0, cw=0):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr, cache_creation_input_tokens=cw)


def tool_use(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def text(t):
    return NS(type="text", text=t)


class FakeClaude:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        return self.turns.pop(0)


def test_search_then_create_then_reply():
    tracker = Guarded(MemoryTracker())
    fake = FakeClaude([
        NS(stop_reason="tool_use", usage=usage(), content=[tool_use("t1", "search_items", {"query": "https://s/p"})]),
        NS(stop_reason="tool_use", usage=usage(cr=500), content=[tool_use("t2", "create_item", {
            "title": "Revenue tile shows NaN", "description": "**Source**: https://s/p", "acceptance_criteria": ["tile shows 0 when no rows"],
            "labels": ["web"], "state": "ready"})]),
        NS(stop_reason="end_turn", usage=usage(), content=[text("Created <memory://M1|M1> in Agent Ready")]),
    ])
    res = agent.run(fake, tracker, "thread text", model="claude-opus-5-5")
    assert res.reply.startswith("Created") and res.actions == ["created M1 (Agent Ready)"] and res.iterations == 3
    assert res.usage["cache_read_input_tokens"] == 500 and res.cost_usd > 0
    first = fake.requests[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default" and agent.FALLBACK_BETA in first["betas"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"} and all(t["strict"] for t in first["tools"])
    # tool results were fed back as a single user message with matching ids
    second_msgs = fake.requests[1]["messages"]
    assert second_msgs[-1]["role"] == "user" and second_msgs[-1]["content"][0]["tool_use_id"] == "t1"


def test_guard_error_returned_as_tool_error_not_exception():
    tracker = Guarded(MemoryTracker([Item("M9", "Old", "memory://M9", "inReview", "In Review")]))
    fake = FakeClaude([
        NS(stop_reason="tool_use", usage=usage(), content=[tool_use("t1", "move_item", {"id": "M9", "state": "ready"})]),
        NS(stop_reason="end_turn", usage=usage(), content=[text("Can't move M9, it is In Review; left a note.")]),
    ])
    res = agent.run(fake, tracker, "x")
    result_block = fake.requests[1]["messages"][-1]["content"][0]
    assert result_block["is_error"] is True and "In Review" in result_block["content"]
    assert res.actions == []


def test_refusal_and_iteration_cap():
    fake = FakeClaude([NS(stop_reason="refusal", usage=usage(), content=[], stop_details=NS(category="cyber"))])
    res = agent.run(fake, Guarded(MemoryTracker()), "x")
    assert "declined" in res.reply and "cyber" in res.reply

    looping = FakeClaude([NS(stop_reason="tool_use", usage=usage(), content=[tool_use("t", "search_items", {"query": "q"})])] * 3)
    res = agent.run(looping, Guarded(MemoryTracker()), "x", max_iterations=3)
    assert "ran out of steps" in res.reply and res.iterations == 3


def test_extra_tool_is_offered_and_dispatched():
    tracker = Guarded(MemoryTracker())
    calls = []
    extra = {"load_earlier_messages": (agent.EARLIER_TOOL, lambda a: calls.append(a) or {"messages": ["[t] devang: earlier context"], "note": "1 messages"})}
    fake = FakeClaude([
        NS(stop_reason="tool_use", usage=usage(), content=[tool_use("t1", "load_earlier_messages", {"limit": 20})]),
        NS(stop_reason="end_turn", usage=usage(), content=[text("Need more: what should the tile show?")]),
    ])
    res = agent.run(fake, tracker, "Recent channel messages ...", model="claude-opus-5-5", extra_tools=extra)
    assert calls == [{"limit": 20}]
    assert any(t["name"] == "load_earlier_messages" for t in fake.requests[0]["tools"])
    assert "earlier context" in fake.requests[1]["messages"][-1]["content"][0]["content"]
    assert res.actions == [] and "Need more" in res.reply
