from ticketbot.context import Msg, SlackReader, ThreadContext, clean_text, extract_links, strip_bot_mention


def test_clean_text_rewrites_slack_markup():
    names = {"U1": "devang"}
    assert clean_text("hey <@U1> see <https://x.y/z|this> in <#C1|eng> &amp; <!here>", names) == "hey @devang see https://x.y/z in #eng &"


def test_strip_bot_mention():
    assert strip_bot_mention("<@UBOT> make a ticket", "UBOT") == "make a ticket"
    assert strip_bot_mention("<@UBOT>", "UBOT") == ""


def test_extract_links_only_interesting_hosts():
    links = extract_links(["see <https://notes.granola.ai/d/abc|notes> and <https://example.com/x>", "<https://github.com/o/r/pull/1>"])
    assert links == ["https://notes.granola.ai/d/abc", "https://github.com/o/r/pull/1"]


def test_render_contains_permalink_and_thread():
    ctx = ThreadContext("C1", "eng", "1.0", "https://s/p", "ishwar", "make a ticket", [Msg("devang", "1700000000.0", "revenue tile shows NaN")])
    text = ctx.render()
    assert "https://s/p" in text and "<thread>" in text and "revenue tile shows NaN" in text and "make a ticket" in text


class FakeSlack:
    def __init__(self):
        self.calls = []

    def users_info(self, user):
        return {"user": {"id": user, "profile": {"display_name": f"name-{user}"}}}

    def conversations_info(self, channel):
        return {"channel": {"name": "eng"}}

    def conversations_replies(self, channel, ts, limit, cursor=None):
        return {"messages": [
            {"user": "U1", "ts": "1.0", "text": "root <https://notes.granola.ai/d/1>"},
            {"user": "U2", "ts": "2.0", "text": "<@UBOT> make a ticket", "thread_ts": "1.0"},
            {"subtype": "channel_join", "user": "U3", "ts": "3.0", "text": "joined"},
        ], "response_metadata": {"next_cursor": ""}}

    def chat_getPermalink(self, channel, message_ts):
        return {"permalink": f"https://w.slack.com/archives/{channel}/p{message_ts}"}


def test_reader_builds_context():
    ctx = SlackReader(FakeSlack()).thread("C1", "1.0", "U2", "<@UBOT> make a ticket", "UBOT")
    assert ctx.requester == "name-U2" and ctx.channel_name == "eng"
    assert [m.text for m in ctx.messages] == ["root https://notes.granola.ai/d/1", "make a ticket"]
    assert ctx.links == ["https://notes.granola.ai/d/1"]
    assert ctx.instruction == "make a ticket"
