"""The agent loop: Claude + tracker tools over one Slack thread.

A manual tool loop over `client.beta.messages.create` (not the SDK tool runner) because the request needs
`fallbacks` + the server-side-fallback beta, strict JSON-schema tools, prompt caching on the system prompt,
refusal handling, and has to be testable with a fake client.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .trackers.base import Guarded, GuardError

log = logging.getLogger("ticketbot.agent")

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: (input, output, cache_read, cache_write_5m). Estimates for the run log only.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")

STATE_ENUM = ["ready", "needsSpec"]


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOLS: list[dict] = [
    {
        "name": "search_items",
        "description": "Search the project's tracker (title + description). Use the thread permalink first, then key words. Returns up to 10 items with id, title, state, labels, url.",
        "strict": True,
        "input_schema": _schema({"query": {"type": "string"}}, ["query"]),
    },
    {
        "name": "get_item",
        "description": "Fetch one item in full: description, acceptance criteria, labels, state, last comments.",
        "strict": True,
        "input_schema": _schema({"id": {"type": "string"}}, ["id"]),
    },
    {
        "name": "create_item",
        "description": "Create a new item. description must follow the Source/Layer/Notes shape. state 'ready' = Agent Ready, 'needsSpec' = Needs Spec.",
        "strict": True,
        "input_schema": _schema(
            {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "labels": {"type": "array", "items": {"type": "string"}},
                "state": {"type": "string", "enum": STATE_ENUM},
            },
            ["title", "description", "acceptance_criteria", "labels", "state"],
        ),
    },
    {
        "name": "update_item",
        "description": "Edit an existing item. Pass null for fields you do not change. add_criteria appends to the acceptance criteria; remove_criteria drops criteria whose text matches (exact, or the given text is a distinctive part of it); labels are added, never removed.",
        "strict": True,
        "input_schema": _schema(
            {
                "id": {"type": "string"},
                "title": {"type": ["string", "null"]},
                "description": {"type": ["string", "null"]},
                "add_criteria": {"type": "array", "items": {"type": "string"}},
                "remove_criteria": {"type": "array", "items": {"type": "string"}},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            ["id", "title", "description", "add_criteria", "remove_criteria", "labels"],
        ),
    },
    {
        "name": "move_item",
        "description": "Move an item to 'ready' (Agent Ready) or 'needsSpec' (Needs Spec). Other states are for humans.",
        "strict": True,
        "input_schema": _schema({"id": {"type": "string"}, "state": {"type": "string", "enum": STATE_ENUM}}, ["id", "state"]),
    },
    {
        "name": "comment_item",
        "description": "Add a comment to an item (markdown). Use for new information on items you are not allowed to edit, and to link split siblings.",
        "strict": True,
        "input_schema": _schema({"id": {"type": "string"}, "body": {"type": "string"}}, ["id", "body"]),
    },
]


@dataclass
class RunResult:
    reply: str
    actions: list[str] = field(default_factory=list)
    created: list = field(default_factory=list)
    iterations: int = 0
    stop_reason: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    seconds: float = 0.0
    model: str = ""


EARLIER_TOOL: dict = {
    "name": "load_earlier_messages",
    "description": ("Only available when the context is recent channel messages rather than a thread. Loads the channel "
                    "messages posted before the oldest one you have seen so far, oldest first. Call it again to go further "
                    "back. Stop when you have the whole discussion of the topic, or when it returns no messages."),
    "strict": True,
    "input_schema": _schema({"limit": {"type": "integer", "description": "How many earlier messages to load, 5-50"}}, ["limit"]),
}


def bind_tools(tracker: Guarded) -> dict[str, Callable[[dict], Any]]:
    return {
        "search_items": lambda a: [i.summary() for i in tracker.search(a["query"])],
        "get_item": lambda a: tracker.get(a["id"]).full(),
        "create_item": lambda a: tracker.create(
            a["title"], a["description"], a["acceptance_criteria"], a["labels"], a["state"]
        ).full(),
        "update_item": lambda a: tracker.update(
            a["id"], title=a.get("title"), description=a.get("description"), add_criteria=a.get("add_criteria") or [], labels=a.get("labels") or [],
            remove_criteria=a.get("remove_criteria") or []
        ).full(),
        "move_item": lambda a: tracker.move(a["id"], a["state"]).summary(),
        "comment_item": lambda a: (tracker.comment(a["id"], a["body"]), {"ok": True})[1],
    }


def _text_of(content) -> str:
    return "\n".join(getattr(b, "text", "") for b in content if getattr(b, "type", "") == "text").strip()


def _accumulate(usage: dict, u) -> None:
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        usage[k] = usage.get(k, 0) + (getattr(u, k, 0) or 0)


def estimate_cost(model: str, usage: dict) -> float:
    p = PRICES.get(model)
    if not p:
        return 0.0
    i, o, cr, cw = p
    return (
        usage.get("input_tokens", 0) * i
        + usage.get("output_tokens", 0) * o
        + usage.get("cache_read_input_tokens", 0) * cr
        + usage.get("cache_creation_input_tokens", 0) * cw
    ) / 1_000_000


def run(client, tracker: Guarded, thread_text: str, model: str | None = None, max_iterations: int = 12,
        extra_tools: dict[str, tuple[dict, Callable[[dict], Any]]] | None = None) -> RunResult:
    """Drive Claude over the tracker tools until it answers. `client` is an anthropic.Anthropic (or a fake).
    `extra_tools` maps a tool name to (tool schema, handler); used for context tools such as load_earlier_messages."""
    model = model or os.environ.get("TICKETBOT_MODEL") or DEFAULT_MODEL
    handlers = bind_tools(tracker)
    tools = list(TOOLS)
    for name, (schema, handler) in (extra_tools or {}).items():
        tools.append(schema)
        handlers[name] = handler
    messages: list[dict] = [{"role": "user", "content": thread_text}]
    result = RunResult(reply="", model=model)
    started = time.time()
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    for _ in range(max_iterations):
        result.iterations += 1
        response = client.beta.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=list(messages),
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        _accumulate(result.usage, response.usage)
        result.stop_reason = response.stop_reason or ""

        if response.stop_reason == "refusal":
            cat = getattr(getattr(response, "stop_details", None), "category", None)
            result.reply = f"I can't act on this thread (declined{': ' + cat if cat else ''}). A human should file it."
            break
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            result.reply = _text_of(response.content) or "(no reply)"
            if response.stop_reason == "max_tokens":
                result.reply += "\n(reply truncated)"
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tu in tool_uses:
            args = tu.input if isinstance(tu.input, dict) else json.loads(tu.input)
            try:
                out = handlers[tu.name](args)
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out, default=str)})
            except GuardError as e:
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"Policy: {e}", "is_error": True})
            except Exception as e:  # tracker/network failure: tell the model, let it decide
                log.exception("tool %s failed", tu.name)
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"Error: {type(e).__name__}: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
    else:
        result.reply = "I ran out of steps before finishing. " + (
            f"Done so far: {', '.join(tracker.actions)}." if tracker.actions else "Nothing was changed."
        )

    result.actions = list(tracker.actions)
    result.created = list(tracker.created)
    result.cost_usd = estimate_cost(model, result.usage)
    result.seconds = round(time.time() - started, 1)
    log.info(
        "run model=%s iters=%d stop=%s in=%d out=%d cache_read=%d cost~$%.4f %.1fs actions=%s",
        model, result.iterations, result.stop_reason, result.usage.get("input_tokens", 0),
        result.usage.get("output_tokens", 0), result.usage.get("cache_read_input_tokens", 0),
        result.cost_usd, result.seconds, result.actions,
    )
    return result
