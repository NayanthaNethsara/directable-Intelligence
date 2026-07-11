from typing import Optional
from pydantic import BaseModel, Field, field_validator

ALWAYS_FEASIBLE_SKILL = "Hold"

COMMAND_STATUSES = ["none", "following", "adapting", "releasing", "deferring"]


class CommandState(BaseModel):
    """A pending player command, if any.

    `age_s` matters: the SSG example renders it ('7s ago') and stale-command
    lifecycle handling is one of the RQ1 generalisation cells, so the
    controller must see command age from day one.
    """
    text: str
    age_s: float = 0.0


class ControllerRequest(BaseModel):
    """One controller-tick request. Everything the SLM is allowed to know.

    Note what is NOT here: raw positions, health floats, engine state.
    The SSG compiler (Unity, symbolic) has already done the trigonometry
    and serialised predicates. The model reasons over text only.
    """
    session_id: str
    tick: int
    ssg: str                      # serialized spatial scene graph (fixed templates)
    digest: str = ""              # 2-5 rendered digest lines ("recent: ...", "mood: ...")
    command: Optional[CommandState] = None
    feasible_skills: list[str] = Field(min_length=1)

    @field_validator("feasible_skills")
    @classmethod
    def hold_must_be_present(cls, v: list[str]) -> list[str]:
        # Fail loudly at the boundary if the game violates the invariant,
        # rather than mysteriously later in the repair path.
        if ALWAYS_FEASIBLE_SKILL not in v:
            raise ValueError(f"'{ALWAYS_FEASIBLE_SKILL}' must always be feasible")
        return v


class Decision(BaseModel):
    """The canonical decision schema (verbatim from the proposal)."""
    skill: str
    target: str = ""
    ack: str = ""
    command_status: str = "none"
    proposal: str = ""


class ControllerResponse(BaseModel):
    """Decision plus service metadata.

    `latency_ms` is not decoration: per-decision inference delay is a
    pre-registered system metric (the 'cost of the language-model
    controller'), so it is measured at the source and logged with every
    decision. `repaired` tells you how often the model produced garbage —
    a free reliability metric from day one.
    """
    decision: Decision
    brain: str                    # "heuristic" | "model"
    model_name: str = ""
    latency_ms: float
    repaired: bool = False
    raw_output: str = ""          # what the model actually emitted, pre-repair
