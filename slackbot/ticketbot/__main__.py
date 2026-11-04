"""Entry points:

  python -m ticketbot                      serve (Socket Mode)
  python -m ticketbot --check-config       validate env, projects, agent.json, Slack and tracker reachability
  python -m ticketbot --dry-run thread.json "instruction" [--project NAME] [--tracker memory|real]
                                           run the agent on a saved thread; memory tracker by default
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__, agent
from .config import ConfigError, build_tracker, load_settings
from .context import Msg, ThreadContext, extract_links
from .trackers.base import Guarded, Item
from .trackers.memory import MemoryTracker


def check_config(settings) -> int:
    ok = True
    print(f"ticketbot {__version__}")
    for var in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "ANTHROPIC_API_KEY"):
        print(f"  {var:<20} {'set' if os.environ.get(var) else 'MISSING'}")
        ok &= bool(os.environ.get(var)) or var == "ANTHROPIC_API_KEY"
    print(f"  model                {os.environ.get('TICKETBOT_MODEL') or agent.DEFAULT_MODEL}")
    print(f"  default project      {settings.default_project or '(single project / channel map)'}")
    for p in settings.projects:
        print(f"- {p.name}: tracker={p.tracker_kind} channels={p.channels or '[]'} path={p.path}")
        try:
            print(f"    {build_tracker(p).ping()}")
        except Exception as e:
            ok = False
            print(f"    tracker FAILED: {e}")
    if os.environ.get("SLACK_BOT_TOKEN"):
        try:
            from slack_sdk import WebClient

            me = WebClient(token=os.environ["SLACK_BOT_TOKEN"]).auth_test()
            print(f"  slack                bot @{me['user']} in {me['team']}")
        except Exception as e:
            ok = False
            print(f"  slack                FAILED: {e}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  note: ANTHROPIC_API_KEY missing; the bot will start but every request will fail until it is set")
    print("OK" if ok else "PROBLEMS FOUND")
    return 0 if ok else 1


def load_thread(path: Path) -> tuple[ThreadContext, list[Item]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    msgs = [Msg(user=m["user"], ts=str(m.get("ts", "")), text=m["text"]) for m in data["messages"]]
    ctx = ThreadContext(
        channel_id=data.get("channel_id", "C000"),
        channel_name=data.get("channel", "eng"),
        thread_ts=data.get("thread_ts", "0"),
        permalink=data.get("permalink", "https://example.slack.com/archives/C000/p0"),
        requester=data.get("requester", msgs[0].user if msgs else "someone"),
        instruction="",
        messages=msgs,
        links=extract_links([m.text for m in msgs]),
    )
    seeded = [Item(**i) for i in data.get("items", [])]
    return ctx, seeded


def dry_run(settings, path: Path, instruction: str, project_name: str | None, use_real: bool) -> int:
    import anthropic

    ctx, seeded = load_thread(path)
    ctx.instruction = instruction
    if use_real:
        project = settings.by_name(project_name) if project_name else settings.resolve()
        tracker = Guarded(build_tracker(project))
        print(f"tracker: {tracker.ping()}")
    else:
        tracker = Guarded(MemoryTracker(seeded))
    print(ctx.render())
    print("-" * 60)
    res = agent.run(anthropic.Anthropic(), tracker, ctx.render())
    print(res.reply)
    print("-" * 60)
    print(f"actions: {res.actions}")
    print(f"usage: {res.usage}  cost~${res.cost_usd:.4f}  {res.seconds}s  stop={res.stop_reason}")
    if not use_real:
        for it in tracker.inner.items.values():
            print(json.dumps(it.full(), indent=2))
    return 0


def serve(settings) -> int:
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    from .app import build_app

    app = build_app(settings)
    names = ", ".join(p.name for p in settings.projects)
    logging.getLogger("ticketbot").info("serving projects: %s", names)
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ticketbot")
    ap.add_argument("--check-config", action="store_true")
    ap.add_argument("--dry-run", nargs=2, metavar=("THREAD_JSON", "INSTRUCTION"))
    ap.add_argument("--project", help="project name for --dry-run --tracker real")
    ap.add_argument("--tracker", choices=["memory", "real"], default="memory")
    ap.add_argument("--env", default=".env", help="dotenv file (default .env)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv(args.env)
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    if args.check_config:
        return check_config(settings)
    if args.dry_run:
        return dry_run(settings, Path(args.dry_run[0]), args.dry_run[1], args.project, args.tracker == "real")
    for var in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
        if not os.environ.get(var):
            print(f"{var} missing", file=sys.stderr)
            return 2
    return serve(settings)


if __name__ == "__main__":
    sys.exit(main())
