from openai import OpenAI

from ..config import settings
from ..schema import ControllerRequest, COMMAND_STATUSES
from ..skills import registry
from .base import Brain

SYSTEM_PROMPT_VERSION = "v0-dev"

SYSTEM_PROMPT = """You are the tactical decision module of an NPC teammate in a \
cooperative game. Each turn you receive a spatial scene description, a short \
context digest, and possibly a player command.

Choose exactly one skill from the AVAILABLE SKILLS menu for this turn.

Rules:
- Prefer decisions that help the shared objective and keep both of you alive.
- If a player command is present and sound, follow it (command_status "following").
- If it is partly feasible, adapt it and say how (command_status "adapting").
- If it is unsound or impossible, decline with a short reason (command_status "deferring").
- If a command was already satisfied or is now irrelevant, release it (command_status "releasing").
- If there is no command, command_status is "none".
- "target" is the id of the entity or cover the skill applies to (e.g. "E2", "C7"), or "" if none.
- "ack" is one short in-character line (under 12 words).
- "proposal" is almost always ""; only use it for a brief suggestion to the player.

Respond with a single JSON object and nothing else."""


def build_user_message(req: ControllerRequest) -> str:
    """Compose the model's view of the world.

    Mirrors the canonical serialized format: SSG block, digest block,
    command line, then the menu of currently-feasible skills.
    Fixed structure, fixed labels — the policy conditions on tokens,
    so prompt phrasing drift is unmeasured noise (same rule as digest
    templates). Change this only deliberately, and version it.
    """
    parts = [req.ssg.strip()]
    if req.digest.strip():
        parts.append(req.digest.strip())
    if req.command is not None:
        parts.append(f'command: "{req.command.text}" ({req.command.age_s:.0f}s ago)')
    else:
        parts.append("command: none")

    menu = "\n".join(
        f"- {s} — {registry.describe(s)}"
        for s in req.feasible_skills
    )
    parts.append(f"AVAILABLE SKILLS this turn:\n{menu}")
    return "\n\n".join(parts)


def build_decision_schema(feasible_skills: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "enum": feasible_skills},
            "target": {"type": "string", "maxLength": 16},
            "ack": {"type": "string", "maxLength": 80},
            "command_status": {"type": "string", "enum": COMMAND_STATUSES},
            "proposal": {"type": "string", "maxLength": 120},
        },
        "required": ["skill", "target", "ack", "command_status", "proposal"],
        "additionalProperties": False,
    }


class ModelBrain(Brain):
    name = "model"

    def __init__(self,
                 base_url: str | None = None,
                 model: str | None = None,
                 temperature: float | None = None):
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_s,
        )

    def decide(self, req: ControllerRequest) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(req)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "decision",
                    "schema": build_decision_schema(req.feasible_skills),
                    "strict": True,
                },
            },
            temperature=self.temperature,
            max_tokens=settings.llm_max_tokens,
        )
        return resp.choices[0].message.content or ""
