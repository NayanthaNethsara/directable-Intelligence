import json

from ..schema import ControllerRequest, ALWAYS_FEASIBLE_SKILL
from ..skills import registry
from .base import Brain


class HeuristicBrain(Brain):
    """Deterministic baseline: walk the catalog by priority and take the first
    feasible skill whose triggers match the SSG. All skill knowledge lives in
    skills.json; this class is only the walk."""

    name = "heuristic"

    def decide(self, req: ControllerRequest) -> str:
        ssg = req.ssg.lower()

        chosen = registry.hold
        for skill in registry.by_priority():
            if skill.name in req.feasible_skills and skill.matches(ssg):
                chosen = skill
                break

        command_status = "none"
        if req.command is not None:
            command_status = "following" if chosen.name != ALWAYS_FEASIBLE_SKILL else "deferring"

        return json.dumps({
            "skill": chosen.name,
            "target": "",
            "ack": chosen.ack,
            "command_status": command_status,
            "proposal": "",
        })
