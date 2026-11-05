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


class FakeSlackNoThread(FakeSlack):
    """Mention posted top-level in the channel: replies returns only the mention itself."""

    def conversations_replies(self, channel, ts, limit, cursor=None):
        return {"messages": [{"user": "U2", "ts": "9.0", "text": "<@UBOT> make a ticket"}], "response_metadata": {"next_cursor": ""}}

    def conversations_history(self, channel, latest, inclusive, limit):
        assert latest == "9.0" and not inclusive
        return {"messages": [  # newest first, like Slack; the mention itself is excluded (inclusive=False)
            {"user": "U1", "ts": "8.0", "text": "they want it to show 0"},
            {"user": "U1", "ts": "7.0", "text": "revenue tile shows NaN <https://notes.granola.ai/d/2>"},
            {"user": "U3", "ts": "6.0", "text": "a reply in some other thread", "thread_ts": "5.0"},
        ]}


def test_reader_falls_back_to_recent_channel_messages():
    ctx = SlackReader(FakeSlackNoThread()).thread("C1", "9.0", "U2", "<@UBOT> make a ticket", "UBOT")
    assert ctx.scope == "recent"
    assert [m.text for m in ctx.messages] == ["revenue tile shows NaN https://notes.granola.ai/d/2", "they want it to show 0", "make a ticket"]
    assert ctx.links == ["https://notes.granola.ai/d/2"]
    assert "Recent channel messages" in ctx.render()


def test_reader_keeps_thread_scope_when_thread_exists():
    assert SlackReader(FakeSlack()).thread("C1", "1.0", "U2", "x", "UBOT").scope == "thread"


class FakeSlackBotOnlyThread(FakeSlack):
    """Thread exists but holds only mentions of the bot and the bot's own replies."""

    def conversations_replies(self, channel, ts, limit, cursor=None):
        return {"messages": [
            {"user": "U2", "ts": "9.0", "thread_ts": "9.0", "text": "<@UBOT> make a ticket"},
            {"user": "UBOT", "ts": "9.5", "thread_ts": "9.0", "text": "I haven't created anything yet."},
            {"user": "U2", "ts": "9.7", "thread_ts": "9.0", "text": "<@UBOT> make a ticket"},
        ], "response_metadata": {"next_cursor": ""}}

    def conversations_history(self, channel, latest, inclusive, limit):
        assert latest == "9.0" and not inclusive
        return {"messages": [{"user": "U1", "ts": "8.0", "text": "they want it to show 0"},
                             {"user": "U1", "ts": "7.0", "text": "revenue tile shows NaN"}]}


def test_reader_falls_back_when_thread_has_only_bot_traffic():
    ctx = SlackReader(FakeSlackBotOnlyThread()).thread("C1", "9.0", "U2", "<@UBOT> make a ticket", "UBOT")
    assert ctx.scope == "recent"
    assert [m.text for m in ctx.messages][:3] == ["revenue tile shows NaN", "they want it to show 0", "make a ticket"]


def test_reader_earlier_walks_back_and_reports_oldest_ts():
    class Fake(FakeSlack):
        def conversations_history(self, channel, latest, inclusive, limit):
            assert latest == "7.0" and not inclusive and limit == 20
            return {"messages": [{"user": "U1", "ts": "6.0", "text": "<@UBOT> hi"}, {"user": "U1", "ts": "5.0", "text": "older topic"},
                                 {"subtype": "channel_join", "user": "U9", "ts": "4.0", "text": "joined"}]}
    msgs, oldest = SlackReader(Fake()).earlier("C1", "7.0", 20, "UBOT")
    assert [m.text for m in msgs] == ["older topic", "hi"] and oldest == "4.0"
