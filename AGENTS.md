# Agent Guide — Directable Intelligence

FastAPI controller service for a Unity co-op companion. A Unity game POSTs a
serialized spatial scene graph (SSG) once per controller tick; the service
returns one structured decision. See [README.md](README.md) for setup and run
instructions — do not duplicate them here.

## Architecture

```
controller_service/
  main.py        # FastAPI app: /decide, /skills, /health, validate-or-repair, JSONL logging
  schema.py      # external contract (request/response models) — Unity depends on this
  config.py      # pydantic-settings; the ONLY place env/config enters the process
  skills.py      # SkillDef + SkillRegistry, loaded from skills.json at import
  skills.json    # THE skill catalog: description, when/avoid, target kinds, triggers
  worldstate.py  # SSG text -> facts (carrying, missing, depositable, threats)
  history.py     # per-session ring of recent decisions; feeds the repeat warning
  brains/
    base.py      # Brain interface: decide(req) -> raw JSON string
    heuristic.py # generic priority walk over the catalog's triggers, zero deps
    model.py     # local LLM via OpenAI-compatible API, json_schema output
fixtures/        # sample /decide payloads; one file per scenario
tests/           # pytest, run through the FastAPI app with fixture payloads
scripts/         # llm-server.sh (llama.cpp launcher)
models/, logs/   # gitignored (GGUF weights, decision JSONL)
```

## Grounding the model brain

A 0.6B policy does not do arithmetic over the SSG and cannot see its own past
decisions, so left alone it latches onto one skill and repeats it forever. Two
things prevent that, and changes to either need a prompt-version bump:

- **SITUATION block** (`worldstate.py`): the SSG parsed into explicit facts —
  what you carry, what a blueprint still needs, which resource is MISSING,
  which you have ENOUGH of, whether you CAN deposit right now. The system
  prompt's ladder keys off those words, so the block's wording and the
  prompt's are one unit.
- **Repeat warning** (`history.py`): the streak of identical decisions for the
  session, stated in the prompt once it passes `REPEAT_WARNING_AFTER`.

Wording here is load-bearing, not cosmetic — measure a change by replaying a
logged episode through the brain before keeping it, at `LLM_TEMPERATURE=0` so
you are not reading sampling noise.

**Never name an action you do not want taken.** Measured twice on the logged
wood-loop episode: "threats: none in sight — standing alert is wasted" made the
companion Hold *more*, and "last turn you chose GatherWood" alone flipped a
correct Build back to GatherWood. That is why the repeat warning reports the
length of a streak and never the skill in it. State facts; name only the wanted
action.

## Invariants — never break these

- **The game loop must never crash on a bad decision.** Every brain's raw
  output goes through `validate_or_repair` in `main.py`; the worst output
  degrades to a safe `Hold`, flagged with `repaired: true`. Any new brain or
  endpoint change must preserve this path.
- **`Hold` is always feasible.** `ControllerRequest` rejects payloads without
  it; repairs fall back to it.
- **`schema.py` is a contract with Unity.** Changing field names, enums, or
  defaults breaks the game client — treat any change there as breaking and
  call it out.
- **Config only via `settings`** (`config.py`). Never read `os.environ`
  directly.
- **Every decision is logged to JSONL** with latency, repair flag, and raw
  output. New response fields should be added to `log_decision` too.

## Adding a skill

All skill knowledge on the service side lives in `controller_service/skills.json`
(loaded and validated by `skills.py`). Never hardcode skill names, descriptions,
or acks anywhere else.

1. Add an entry to `skills.json`: `name`, `description` (what it does), `when`
   and `avoid` (the preconditions the LLM picks by — write them against the
   SITUATION vocabulary), `ack` (default in-character line), and
   `target_kinds` if the skill only accepts certain objects ("wood", "stone",
   "blueprint", "wall", "threat"); a target of the wrong kind is repaired away
   instead of reaching Unity. `priority` orders the model's menu — urgent
   skills first, idle ones last — and doubles as the heuristic ladder order.
   Optionally add `triggers` if the heuristic brain should be able to pick it:
   groups of SSG substrings — every group must match, a group matches if ANY
   of its entries appears in the lowercased SSG. No triggers = model-only.
2. Implement a `SkillWorker` in the Unity repo
   (`Assets/Scripts/DirectableAI/Skills/Workers/`) with the same `SkillName`,
   and register it in `SkillExecutor.BuildRegistry`. Unity decides feasibility
   per tick; the service only ever picks from the menu Unity sends. A skill in
   this catalog with no worker behind it can never be chosen — do not leave
   entries advertising behaviour the game does not have.
3. Check `GET /skills` to confirm the catalog the service loaded.

## Adding a brain

1. Subclass `Brain` in `controller_service/brains/`, set `name`, implement
   `decide(req) -> str` returning a raw JSON string matching `Decision`.
2. Register it in `BRAINS` in `main.py`. Optional dependencies (LLM client,
   env) must fail soft at import — follow the `ModelBrain` try/except pattern
   so the service still starts with the heuristic brain.
3. Do not validate inside the brain; `validate_or_repair` handles that
   uniformly.
4. Add a fixture in `fixtures/` if the brain exercises a new scenario.

## Code style

- Python 3.11+, Pydantic v2, type hints on all public functions and fields.
- Self-explanatory code first: clear names, small functions, one
  responsibility per module. Comments only where the code cannot speak —
  invariants, non-obvious "why" (see the repair philosophy block in
  `main.py` for the house style). No narration comments.
- Docstrings on models/classes explain intent and constraints, not mechanics.
- Match the existing formatting: 4-space indent, section-divider comments
  (`# ---`) only for major blocks in `main.py`-sized files.

## Workflow

- Env managed by `uv`; use `make setup`, run via `make api` / `make llm`.
- Verify changes with `make health` and `make test-fixture`
  (`BRAIN=heuristic` needs no LLM running; use it for quick checks).
- Tests use `pytest` + `httpx` (dev group). Prefer testing through the
  FastAPI app with fixture payloads.
- Never commit anything under `models/` or `logs/`.

## Commits

- Short, imperative, single-line messages (e.g. `Add retry to model brain`).
- No co-author trailers, no generated-with footers.

## Related repo

The Unity client lives at
`/Users/nayanthanethsara/Documents/Github/directable-Intelligence-unity`
(`../directable-Intelligence-unity`) and has its own `AGENTS.md` covering C#
style, the game systems and the Unity MCP workflow — read it before working
there. Inside it, `Assets/UnityTechnologies` is third-party and read-only —
never delete or modify files there.
