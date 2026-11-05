"""Slack side: Bolt app in Socket Mode. @mention or a :ticket: reaction -> agent run -> thread reply."""

from __future__ import annotations

import logging
import os
import threading
import time

import anthropic
import httpx
from slack_bolt import App

from . import agent
from .config import ConfigError, Settings, build_tracker
from .context import SlackReader, strip_bot_mention
from .trackers.base import Guarded

log = logging.getLogger("ticketbot.app")


class SeenEvents:
    """Slack retries deliveries; remember event ids for a while."""

    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def first_time(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            for k, t in list(self._seen.items()):
                if now - t > self.ttl:
                    del self._seen[k]
            if key in self._seen:
                return False
            self._seen[key] = now
            return True


def post_audit(text: str) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        httpx.post(url, json={"text": text}, timeout=10)
    except Exception:
        log.warning("audit webhook failed", exc_info=True)


EARLIER_MAX_CALLS = 6
EARLIER_MAX_MESSAGES = 200


def build_app(settings: Settings, anthropic_client: anthropic.Anthropic | None = None) -> App:
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    bot_user_id = app.client.auth_test()["user_id"]
    reader = SlackReader(app.client)
    seen = SeenEvents()
    reaction_name = os.environ.get("TICKETBOT_REACTION", "ticket")
    claude = anthropic_client or anthropic.Anthropic()

    def react(channel: str, ts: str, name: str, remove: bool = False) -> None:
        try:
            if remove:
                app.client.reactions_remove(channel=channel, timestamp=ts, name=name)
            else:
                app.client.reactions_add(channel=channel, timestamp=ts, name=name)
        except Exception:
            pass  # already_reacted / no permission: cosmetic

    def earlier_tool(channel: str, ctx):
        """load_earlier_messages bound to this channel; walks back from the oldest message already shown, capped."""
        state = {"before": ctx.oldest_ts, "loaded": 0, "calls": 0}

        def load(a: dict):
            if state["calls"] >= EARLIER_MAX_CALLS or state["loaded"] >= EARLIER_MAX_MESSAGES:
                return {"messages": [], "note": "limit reached; if the context is still unclear, ask the requester"}
            state["calls"] += 1
            msgs, oldest = reader.earlier(channel, state["before"], max(5, min(50, int(a.get("limit") or 20))), bot_user_id)
            state["before"], state["loaded"] = oldest, state["loaded"] + len(msgs)
            return {"messages": [f"[{m.when()}] {m.user}: {m.text}" for m in msgs],
                    "note": "no earlier messages" if not msgs else f"{len(msgs)} messages, oldest first"}

        return {"load_earlier_messages": (agent.EARLIER_TOOL, load)}

    def handle(channel: str, msg_ts: str, thread_ts: str, requester: str, instruction: str) -> None:
        react(channel, msg_ts, "eyes")
        try:
            project = settings.resolve(channel_id=channel, channel_name=reader.channel_name(channel))
            tracker = Guarded(build_tracker(project))
            ctx = reader.thread(channel, thread_ts, requester, instruction, bot_user_id)
            res = agent.run(claude, tracker, ctx.render(), extra_tools=earlier_tool(channel, ctx) if ctx.scope == "recent" else None)
            reply = res.reply
            ok = True
        except ConfigError as e:
            reply, ok = f"Config problem: {e}", False
        except anthropic.APIStatusError as e:
            reply, ok = f"Claude API error {e.status_code}: {getattr(e, 'message', e)}", False
        except Exception as e:
            log.exception("handle failed")
            reply, ok = f"Failed: {type(e).__name__}: {e}", False
        app.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=reply)
        react(channel, msg_ts, "eyes", remove=True)
        react(channel, msg_ts, "white_check_mark" if ok else "x")
        if ok:
            post_audit(
                f"TicketBot in #{reader.channel_name(channel)} by {reader.user_name(requester)}: "
                f"{'; '.join(res.actions) or 'no change'} (~${res.cost_usd:.3f}, {res.seconds}s)"
            )

    @app.event("app_mention")
    def on_mention(body, event, logger):
        if not seen.first_time(body.get("event_id") or event["ts"]):
            return
        if event.get("user") == bot_user_id:
            return
        instruction = strip_bot_mention(event.get("text", ""), bot_user_id)
        handle(event["channel"], event["ts"], event.get("thread_ts") or event["ts"], event.get("user", ""), instruction)

    @app.event("reaction_added")
    def on_reaction(body, event, logger):
        if event.get("reaction") != reaction_name or event.get("item", {}).get("type") != "message":
            return
        if not seen.first_time(body.get("event_id") or f"{event['item']['ts']}:{event['user']}"):
            return
        channel, ts = event["item"]["channel"], event["item"]["ts"]
        # the reacted message may be a reply; find its thread root
        try:
            root = app.client.conversations_replies(channel=channel, ts=ts, limit=1)["messages"][0]
            thread_ts = root.get("thread_ts") or ts
        except Exception:
            thread_ts = ts
        handle(channel, ts, thread_ts, event.get("user", ""), "")

    @app.event("message")
    def ignore_messages(body, logger):
        return  # subscribed implicitly via channels:history; nothing to do

    return app
