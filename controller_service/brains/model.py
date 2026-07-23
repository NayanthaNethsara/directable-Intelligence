from openai import OpenAI

from ..config import settings
from ..history import history
from ..schema import ControllerRequest, COMMAND_STATUSES
from ..skills import registry
from ..worldstate import parse_ssg, situation_lines
from .base import Brain

SYSTEM_PROMPT_VERSION = "v2-grounded"

REPEAT_WARNING_AFTER = 3        # turns of the same skill before the prompt calls it out

SYSTEM_PROMPT = """You are the decision module of an NPC teammate in a cooperative \
survival game.

Each turn you receive:
- SSG: what you sense right now. Only what exists is listed, so a category can be \
absent some turns.
- SITUATION: facts already worked out from the SSG — what you carry, what is \
missing, what you have been doing. Trust it and never redo its arithmetic.
- digest: recent events.
- command: what the player asked for, or "none".
- AVAILABLE SKILLS: the only skills you may pick this turn, each with the \
conditions that make it right (USE IF) or wrong (SKIP IF).

Choose exactly ONE skill from AVAILABLE SKILLS. The skill you choose keeps \
running until you replace it on a later turn, so choose what matters most now — \
not whatever you are already doing.

Work down this ladder and take the FIRST line that applies:
1. SITUATION says a threat is threatening or close -> a combat or cover skill.
2. SITUATION shows PLAYER ASKED and what they asked is sound -> do that, and \
say so with command_status. An order outranks your own upkeep plans.
3. SITUATION says you CAN deposit what you carry -> the build or repair skill. \
Carried resources are worth nothing until they are spent.
4. SITUATION names a MISSING resource -> gather that exact resource, no other.
5. SITUATION says NOTHING TO SPEND -> gather from the nearest deposit, however \
far it is. A full pack is progress; standing still is not.
6. Nothing above applies -> stay useful near the player, or Hold.

Hard rules:
- Never gather a resource SITUATION marks ENOUGH. Collecting more of it changes \
nothing.
- If SITUATION says you have repeated a skill for several turns and the world has \
not changed, that skill is not paying off — move to the next line of the ladder.
- Only skills in AVAILABLE SKILLS exist this turn. Anything else is impossible.

Command status: "following" if you do what was asked, "adapting" if you do a \
feasible version of it, "deferring" if it is unsound or impossible, "releasing" \
if it is already satisfied or irrelevant, "none" if there is no command.

Fields:
- "target": the id of the entity, cover point, deposit, blueprint or wall the \
skill applies to, copied exactly from the SSG (e.g. "Z1", "C7", "W1", "T3", \
"B1", "D2"). Leave it "" to let the skill pick the nearest one itself.
- "ack": one short in-character line, under 12 words.
- "proposal": almost always ""; only a brief suggestion to the player.

Respond with a single JSON object and nothing else."""


def build_situation(req: ControllerRequest) -> str:
    """The SITUATION block: derived world facts plus the companion's own streak.

    Both halves exist because the model cannot supply them. It does not do
    reliable arithmetic over the SSG, and the SSG never mentions what the
    companion itself decided last turn.
    """
    lines = situation_lines(parse_ssg(req.ssg))
    if req.command is not None:
        # The ladder's rungs are read off this block, so a rung that lives only
        # in the command line below it loses to the loud resource markers here.
        lines.insert(0, f'PLAYER ASKED: "{req.command.text}" ({req.command.age_s:.0f}s ago)')

    # The streak is deliberately reported WITHOUT naming the skill. Naming it —
    # even to warn against it — is what a small model latches onto: measured on
    # the logged wood-loop episode, "last turn you chose GatherWood" alone flips
    # a correct Build back to GatherWood. Say that repeating failed, not what.
    _, run = history.streak(req.session_id)
    if run >= REPEAT_WARNING_AFTER:
        lines.append(f"REPEATING: you have made the same choice {run} turns running and "
                     f"nothing above has changed — that choice is not working, take another")
    return "SITUATION (already worked out for you — do not recompute):\n" + "\n".join(lines)


def build_user_message(req: ControllerRequest) -> str:
    """Compose the model's view of the world.

    Fixed structure, fixed labels — the policy conditions on tokens, so prompt
    phrasing drift is unmeasured noise (same rule as digest templates). Change
    this only deliberately, and version it.
    """
    parts = [req.ssg.strip()]
    if req.digest.strip():
        parts.append(req.digest.strip())
    parts.append(build_situation(req))
    if req.command is not None:
        parts.append(f'command: "{req.command.text}" ({req.command.age_s:.0f}s ago)')
    else:
        parts.append("command: none")

    parts.append(f"AVAILABLE SKILLS this turn:\n{registry.menu(req.feasible_skills)}")
    return "\n\n".join(parts)


def build_decision_schema(req: ControllerRequest) -> dict:
    # With no command pending, "none" is the only truthful status — so make it
    # the only *reachable* one. Constraining the grammar beats repairing after
    # the fact: a small model reaches for "following" on every turn otherwise.
    statuses = COMMAND_STATUSES if req.command else ["none"]
    return {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "enum": req.feasible_skills},
            "target": {"type": "string", "maxLength": 16},
            "ack": {"type": "string", "maxLength": 80},
            "command_status": {"type": "string", "enum": statuses},
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
                    "schema": build_decision_schema(req),
                    "strict": True,
                },
            },
            temperature=self.temperature,
            max_tokens=settings.llm_max_tokens,
        )
        return resp.choices[0].message.content or ""
