import pytest

from ticketbot.config import ConfigError, load_settings


def test_channel_resolution_by_name_and_id(repo_with_agent, projects_file):
    a, b = repo_with_agent("a"), repo_with_agent("b", "linear")
    s = load_settings(projects_file([
        {"name": "a", "path": str(a), "channels": ["#eng-a", "C111"]},
        {"name": "b", "path": str(b), "channels": ["#eng-b"]},
    ]))
    assert s.resolve(channel_name="eng-a").name == "a"
    assert s.resolve(channel_id="C111").name == "a"
    assert s.resolve(channel_name="#eng-b").tracker_kind == "linear"
    with pytest.raises(ConfigError):
        s.resolve(channel_name="random")


def test_default_project_and_single_project(repo_with_agent, projects_file):
    a, b = repo_with_agent("a"), repo_with_agent("b")
    s = load_settings(projects_file([{"name": "a", "path": str(a)}, {"name": "b", "path": str(b)}], default="b"))
    assert s.resolve(channel_name="whatever").name == "b"
    single = load_settings(projects_file([{"name": "a", "path": str(a)}]))
    assert single.resolve(channel_name="anything").name == "a"


def test_disabled_projects_skipped_and_agent_json_validated(repo_with_agent, projects_file, tmp_path):
    a = repo_with_agent("a")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "agent.json").write_text('{"tracker": "trello", "trello": {}}', encoding="utf-8")
    s = load_settings(projects_file([{"name": "a", "path": str(a)}, {"name": "bad", "path": str(bad), "enabled": False}]))
    assert [p.name for p in s.projects] == ["a"]
    with pytest.raises(ConfigError, match="boardId"):
        load_settings(projects_file([{"name": "bad", "path": str(bad)}]))
