import json

from ..schema import ControllerRequest, ALWAYS_FEASIBLE_SKILL
from .base import Brain


class HeuristicBrain(Brain):
    name = "heuristic"

    def decide(self, req: ControllerRequest) -> str:
        skills = req.feasible_skills
        ssg = req.ssg.lower()

        threatened = "threatening" in ssg or "los to you: yes" in ssg
        has_cover = "cover c" in ssg

        # Priority ladder. Intentionally simple and readable.
        if threatened and has_cover and "TakeCover" in skills:
            skill, ack = "TakeCover", "Taking cover."
        elif threatened and "Engage" in skills:
            skill, ack = "Engage", "Engaging."
        elif "contested" in ssg and "Advance" in skills:
            skill, ack = "Advance", "Pushing up."
        elif "Support" in skills and "player" in ssg:
            skill, ack = "Support", "Sticking with you."
        else:
            skill, ack = ALWAYS_FEASIBLE_SKILL, "Holding position."

        command_status = "none"
        if req.command is not None:
            command_status = "following" if skill != ALWAYS_FEASIBLE_SKILL else "deferring"

        return json.dumps({
            "skill": skill,
            "target": "",
            "ack": ack,
            "command_status": command_status,
            "proposal": "",
        })
