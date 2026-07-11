import json
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from .config import settings
from .schema import (
    ControllerRequest, ControllerResponse, Decision,
    ALWAYS_FEASIBLE_SKILL, COMMAND_STATUSES,
)
from .brains.base import Brain
from .brains.heuristic import HeuristicBrain

app = FastAPI(title="coplayer-controller-service")

BRAINS: dict[str, Brain] = {"heuristic": HeuristicBrain()}
try:
    from .brains.model import ModelBrain
    BRAINS["model"] = ModelBrain()
except Exception as e:                                    # missing dep, bad env, etc.
    print(f"[startup] model brain unavailable ({e}); heuristic only")

DEFAULT_BRAIN = settings.default_brain

LOG_DIR = settings.log_dir
LOG_DIR.mkdir(parents=True, exist_ok=True)
RUN_ID = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
LOG_PATH = LOG_DIR / f"decisions-{RUN_ID}.jsonl"


def log_decision(req: ControllerRequest, resp: ControllerResponse) -> None:
    record = {
        "ts": time.time(),
        "session_id": req.session_id,
        "tick": req.tick,
        "ssg": req.ssg,
        "digest": req.digest,
        "command": req.command.model_dump() if req.command else None,
        "feasible_skills": req.feasible_skills,
        "decision": resp.decision.model_dump(),
        "brain": resp.brain,
        "model_name": resp.model_name,
        "latency_ms": resp.latency_ms,
        "repaired": resp.repaired,
        "raw_output": resp.raw_output,
        "prompt_version": _prompt_version(),
        # "reward": joined later, offline, by the episode post-processor
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _prompt_version() -> str:
    try:
        from .brains.model import SYSTEM_PROMPT_VERSION
        return SYSTEM_PROMPT_VERSION
    except Exception:
        return "n/a"


# ---------------------------------------------------------------------------
# Validate & repair. Applied uniformly to every brain's raw output.
#
# Repair philosophy: NEVER crash the game loop over a bad decision. The
# executor's contract is "on any failure, hold". So the worst possible model
# output degrades to a safe, feasible, honest decision — and the `repaired`
# flag makes the failure visible in metrics instead of invisible in a crash.
# ---------------------------------------------------------------------------
def validate_or_repair(raw: str, req: ControllerRequest) -> tuple[Decision, bool]:
    fallback = Decision(
        skill=ALWAYS_FEASIBLE_SKILL,
        target="",
        ack="Holding position.",
        # A pending command we failed to process is NOT consumed: 'deferring'
        # retains it (schema rule), so the next tick gets another chance.
        command_status="deferring" if req.command else "none",
        proposal="",
    )
    try:
        data = json.loads(raw)
        d = Decision(**data)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return fallback, True

    repaired = False
    if d.skill not in req.feasible_skills:      # belt-and-braces; grammar should prevent this
        d.skill = ALWAYS_FEASIBLE_SKILL
        repaired = True
    if d.command_status not in COMMAND_STATUSES:
        d.command_status = fallback.command_status
        repaired = True
    if req.command is None and d.command_status != "none":
        d.command_status = "none"               # can't have a status about a command that isn't there
        repaired = True
    return d, repaired


# ---------------------------------------------------------------------------
# The endpoint.
# ---------------------------------------------------------------------------
@app.post("/decide", response_model=ControllerResponse)
def decide(req: ControllerRequest, brain: str = DEFAULT_BRAIN) -> ControllerResponse:
    if brain not in BRAINS:
        raise HTTPException(404, f"unknown brain '{brain}'; available: {list(BRAINS)}")
    b = BRAINS[brain]

    t0 = time.perf_counter()
    try:
        raw = b.decide(req)
    except Exception as e:
        # Brain is down/unreachable: same philosophy — return a safe Hold,
        # flag it, keep the game alive. Unity additionally has its own
        # timeout + hold-last-skill path for when even the transport dies.
        raw = f"<brain error: {e}>"
    latency_ms = (time.perf_counter() - t0) * 1000.0

    decision, repaired = validate_or_repair(raw, req)

    resp = ControllerResponse(
        decision=decision,
        brain=b.name,
        model_name=getattr(b, "model", ""),
        latency_ms=round(latency_ms, 2),
        repaired=repaired,
        raw_output=raw,
    )
    log_decision(req, resp)
    return resp


@app.get("/health")
def health() -> dict:
    return {"ok": True, "brains": list(BRAINS), "log": str(LOG_PATH)}
