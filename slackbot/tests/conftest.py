import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TRELLO_CFG = {
    "boardId": "board1",
    "lists": {"ready": "Agent Ready", "inProgress": "In Progress", "inReview": "In Review", "done": "Done", "needsSpec": "Needs Spec"},
}
LINEAR_CFG = {
    "teamKey": "TL",
    "readyLabel": "agent-ready",
    "states": {"ready": "Todo", "inProgress": "In Progress", "inReview": "In Review", "done": "Done", "needsSpec": "Backlog"},
}


@pytest.fixture
def repo_with_agent(tmp_path):
    def make(name="demo", tracker="trello"):
        repo = tmp_path / name
        repo.mkdir()
        agent = {"project": name, "tracker": tracker, "baseBranch": "temp-prod", "slackChannel": "#eng-agent"}
        if tracker == "trello":
            agent["trello"] = TRELLO_CFG
        else:
            agent["linear"] = LINEAR_CFG
        (repo / "agent.json").write_text(json.dumps(agent), encoding="utf-8")
        return repo

    return make


@pytest.fixture
def projects_file(tmp_path):
    def make(projects, default=None):
        p = tmp_path / "projects.json"
        body = {"projects": projects}
        if default:
            body["defaultProject"] = default
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    return make
