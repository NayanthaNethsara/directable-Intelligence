import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from controller_service.brains.model import build_user_message
from controller_service.history import history
from controller_service.main import app
from controller_service.schema import ControllerRequest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def client():
    return TestClient(app)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_heuristic_builds_instead_of_gathering_more_wood(client):
    payload = load("06_carrying_wood_blueprints_waiting.json")
    body = client.post("/decide?brain=heuristic", json=payload).json()
    assert body["decision"]["skill"] == "Build"
    assert body["repaired"] is False


def test_hallucinated_target_is_dropped_not_executed(client):
    payload = load("06_carrying_wood_blueprints_waiting.json") | {
        "session_id": "target-repair",
        "feasible_skills": ["Hold"],
    }
    # Raw output is the brain's; simulate by checking the repair path directly.
    from controller_service.main import validate_or_repair

    req = ControllerRequest(**payload)

    def repair(skill: str, target: str):
        return validate_or_repair(
            json.dumps({"skill": skill, "target": target, "ack": "ok",
                        "command_status": "none", "proposal": ""}), req)

    decision, repaired = repair("Hold", "B99")          # invented id
    assert decision.target == "" and repaired

    decision, repaired = repair("Hold", "B2")           # real id, unconstrained skill
    assert decision.target == "B2" and not repaired


def test_target_of_the_wrong_kind_is_dropped():
    payload = load("06_carrying_wood_blueprints_waiting.json")
    req = ControllerRequest(**payload)
    from controller_service.main import validate_or_repair

    def repair(skill: str, target: str):
        return validate_or_repair(
            json.dumps({"skill": skill, "target": target, "ack": "ok",
                        "command_status": "none", "proposal": ""}), req)

    # T1 is a stone deposit; Build can only resolve blueprint ids.
    decision, repaired = repair("Build", "T1")
    assert decision.target == "" and repaired

    decision, repaired = repair("Build", "B2")
    assert decision.target == "B2" and not repaired

    decision, repaired = repair("GatherWood", "W1")
    assert decision.target == "W1" and not repaired


def test_prompt_carries_situation_and_streak():
    payload = load("06_carrying_wood_blueprints_waiting.json") | {"session_id": "streak"}
    req = ControllerRequest(**payload)

    for _ in range(4):
        history.record("streak", "GatherWood")

    message = build_user_message(req)
    assert "SITUATION" in message
    assert "MISSING stone" in message
    assert "REPEATING: you have made the same choice 4 turns running" in message
    # Naming the repeated skill is what makes a small model repeat it again.
    assert "GatherWood" not in message.split("AVAILABLE SKILLS")[0]
    # The menu must carry preconditions, not just names.
    assert "USE IF:" in message and "SKIP IF:" in message
