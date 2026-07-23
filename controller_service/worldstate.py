"""Facts derived from the SSG, so the model doesn't have to derive them.

The SSG is written for a reader that can do arithmetic: it lists what you
carry and what each blueprint still needs, and leaves "so deposit instead of
gathering" implicit. A 0.6B policy does not close that gap — it latches onto
the most obvious skill and re-picks it every tick. The controller closes it
here, once and deterministically, and hands the model explicit facts.

Parsing is deliberately forgiving. The SSG uses fixed templates (the
`SsgSection` implementations in the Unity client), but an unrecognised line
must never cost the game a decision: anything that doesn't match is dropped
and the model still has the raw SSG.
"""

import re
from dataclasses import dataclass, field

CLOSE_M = 15                                # matches the Unity sections' closeDistance


@dataclass
class Threat:
    id: str
    kind: str
    dist_m: int
    threatening: bool


@dataclass
class Deposit:
    id: str
    kind: str                               # "wood" | "stone"
    dist_m: int


@dataclass
class Blueprint:
    id: str
    dist_m: int
    remaining: dict[str, int]               # resource -> units still required


@dataclass
class DamagedWall:
    id: str
    dist_m: int
    repair_item: str


@dataclass
class Cover:
    id: str
    dist_m: int
    blocks: str                             # contact id this wall shields from


@dataclass
class WorldState:
    """Everything a base-upkeep or combat decision turns on, as numbers."""

    carrying: dict[str, int] = field(default_factory=dict)
    player_dist_m: int | None = None
    player_condition: str = ""
    threats: list[Threat] = field(default_factory=list)
    deposits: list[Deposit] = field(default_factory=list)
    blueprints: list[Blueprint] = field(default_factory=list)
    walls: list[DamagedWall] = field(default_factory=list)
    covers: list[Cover] = field(default_factory=list)
    far_counts: dict[str, int] = field(default_factory=dict)
    far_nearest: dict[str, tuple[str, int]] = field(default_factory=dict)   # id, metres

    def carried(self, resource: str) -> int:
        return self.carrying.get(resource, 0)

    @property
    def nearest_threat(self) -> Threat | None:
        return min(self.threats, key=lambda t: t.dist_m, default=None)

    def nearest_deposit(self, kind: str) -> Deposit | None:
        return min((d for d in self.deposits if d.kind == kind),
                   key=lambda d: d.dist_m, default=None)

    def needed(self) -> dict[str, int]:
        """Units still required by every blueprint in sight, per resource."""
        total: dict[str, int] = {}
        for bp in self.blueprints:
            for resource, amount in bp.remaining.items():
                total[resource] = total.get(resource, 0) + amount
        return total

    def depositable(self) -> list[tuple[str, str]]:
        """(blueprint id, resource) pairs you could feed right now."""
        return [
            (bp.id, resource)
            for bp in self.blueprints
            for resource, amount in bp.remaining.items()
            if amount > 0 and self.carried(resource) > 0
        ]

    def missing(self) -> list[str]:
        """Resources a blueprint in sight needs and you carry none of."""
        return [r for r, amount in self.needed().items() if amount > 0 and self.carried(r) == 0]

    def surplus(self) -> list[str]:
        """Resources you carry more of than everything in sight can absorb."""
        needed = self.needed()
        return [r for r, held in self.carrying.items() if held > 0 and held >= needed.get(r, 0)]

    def repairable(self) -> list[DamagedWall]:
        return [w for w in self.walls if self.carried(w.repair_item) > 0]

    def ids_by_kind(self) -> dict[str, set[str]]:
        """Which ids a skill of each kind may legally target this turn."""
        kinds: dict[str, set[str]] = {
            "wood": set(), "stone": set(), "blueprint": set(),
            "wall": set(), "threat": set(), "cover": set(),
        }
        for deposit in self.deposits:
            kinds.setdefault(deposit.kind, set()).add(deposit.id)
        kinds["blueprint"].update(bp.id for bp in self.blueprints)
        kinds["wall"].update(wall.id for wall in self.walls)
        kinds["threat"].update(threat.id for threat in self.threats)
        kinds["cover"].update(cover.id for cover in self.covers)

        # The "farther ..." summary lines name one id without its details.
        far_kinds = {"wood": "wood", "stone": "stone",
                     "blueprints": "blueprint", "damaged walls": "wall"}
        for what, kind in far_kinds.items():
            if (far := self.far_nearest.get(what)):
                kinds[kind].add(far[0])

        # Pre-split logs pooled every deposit into one "farther deposits" line,
        # where the kind is genuinely unrecoverable — count it as either.
        if (far := self.far_nearest.get("deposits")):
            kinds["wood"].add(far[0])
            kinds["stone"].add(far[0])
        return kinds


_SELF = re.compile(r"^self:.*?\bcarrying\s+(?P<items>.+)$", re.I)
_ITEM = re.compile(r"([a-z]+)\s+(\d+)", re.I)
_PLAYER = re.compile(r"^player:\s*(?P<rest>.+)$", re.I)
_DEPOSIT = re.compile(r"^(?P<kind>wood|stone)\s+(?P<id>[A-Z]+\d+):", re.I)
_BLUEPRINT = re.compile(r"^blueprint\s+(?P<id>[A-Z]+\d+):.*\[(?P<progress>[^\]]*)\]", re.I)
_PROGRESS = re.compile(r"([A-Za-z]+)\s+(\d+)\s*/\s*(\d+)")
_WALL = re.compile(r"^wall\s+(?P<id>[A-Z]+\d+):.*?\bcosts\s+(?P<item>[A-Za-z]+)", re.I)
_FARTHER = re.compile(
    r"^farther\s+(?P<what>wood|stone|deposits|blueprints|damaged walls)\s*\([^)]*\):\s*"
    r"(?P<count>\d+)\s+total(?:.*?nearest\s+(?P<nearest>[A-Z]+\d+):\s*(?P<range>[^)]*))?", re.I)
_COVER = re.compile(r"^cover\s+(?P<id>[A-Z]+\d+):.*?\bblocks\s+(?P<blocks>[A-Z]+\d+)", re.I)
_CONTACT = re.compile(r"^(?P<kind>[a-z]+)\s+(?P<id>[A-Z]+\d+):\s*(?P<rest>.+)$")
_DIST = re.compile(r"(\d+)\s*m\b")


def _dist_m(text: str) -> int:
    m = _DIST.search(text)
    return int(m.group(1)) if m else 0


def parse_ssg(ssg: str) -> WorldState:
    state = WorldState()
    for raw in ssg.splitlines():
        line = raw.strip()
        if not line:
            continue

        if (m := _SELF.match(line)):
            state.carrying = {
                name.lower(): int(count) for name, count in _ITEM.findall(m.group("items"))
            }
        elif (m := _PLAYER.match(line)):
            rest = m.group("rest")
            state.player_dist_m = _dist_m(rest)
            parts = [p.strip() for p in rest.split(",")]
            state.player_condition = parts[1] if len(parts) > 1 else ""
        elif (m := _DEPOSIT.match(line)):
            state.deposits.append(
                Deposit(m.group("id"), m.group("kind").lower(), _dist_m(line)))
        elif (m := _BLUEPRINT.match(line)):
            remaining = {
                name.lower(): max(int(need) - int(have), 0)
                for name, have, need in _PROGRESS.findall(m.group("progress"))
            }
            state.blueprints.append(Blueprint(m.group("id"), _dist_m(line), remaining))
        elif (m := _WALL.match(line)):
            state.walls.append(
                DamagedWall(m.group("id"), _dist_m(line), m.group("item").lower()))
        elif (m := _FARTHER.match(line)):
            what = m.group("what").lower()
            state.far_counts[what] = int(m.group("count"))
            if m.group("nearest"):
                state.far_nearest[what] = (m.group("nearest"), _dist_m(m.group("range") or ""))
        elif (m := _COVER.match(line)):
            # Must precede the contact branch: "cover C1: ..." has the shape of
            # a contact line, and cover read as an enemy is a dangerous mistake.
            state.covers.append(Cover(m.group("id"), _dist_m(line), m.group("blocks")))
        elif (m := _CONTACT.match(line)):
            rest = m.group("rest")
            if "last seen" in rest:             # a memory, not a contact you can act on
                continue
            state.threats.append(Threat(
                id=m.group("id"),
                kind=m.group("kind"),
                dist_m=_dist_m(rest),
                threatening="threatening" in rest,
            ))
    return state


def _carrying_line(state: WorldState) -> str:
    held = [f"{r} {n}" for r, n in state.carrying.items() if n > 0]
    if not held:
        return "carrying: nothing — you cannot build or repair until you gather something"
    return "carrying: " + ", ".join(held)


def _threat_line(state: WorldState) -> str:
    threat = state.nearest_threat
    if threat is None:
        # Stated flatly on purpose: naming the wrong action here, even to warn
        # against it, is what a small model latches onto.
        return "threats: none in sight"
    urgency = "THREATENING you now" if threat.threatening else "not threatening yet"
    return f"threats: nearest {threat.kind} {threat.id} at {threat.dist_m}m, {urgency}"


def _blueprint_lines(state: WorldState) -> list[str]:
    far = state.far_counts.get("blueprints", 0)
    if not state.blueprints:
        return [f"blueprints: none in sight ({far} farther away)" if far
                else "blueprints: none"]

    nearest = min(state.blueprints, key=lambda b: b.dist_m)
    needs = ", ".join(f"{r} {n}" for r, n in nearest.remaining.items() if n > 0) or "nothing"
    lines = [f"blueprints: {len(state.blueprints)} in sight"
             + (f" (+{far} farther)" if far else "")
             + f"; nearest {nearest.id} at {nearest.dist_m}m still needs {needs}"]

    depositable = state.depositable()
    if depositable:
        pairs = ", ".join(f"{resource} into {bp}" for bp, resource in depositable[:3])
        lines.append(f"you CAN deposit right now: {pairs}")

    for resource in state.missing():
        lines.append(f"MISSING {resource}: blueprints need it, you carry 0 — "
                     f"{resource} at {_where_to_get(state, resource)}")
    return lines


def _surplus_lines(state: WorldState) -> list[str]:
    needed = state.needed()
    lines = []
    for resource in state.surplus():
        if not state.blueprints and not state.walls:
            continue
        lines.append(
            f"ENOUGH {resource}: you carry {state.carried(resource)}, everything in sight "
            f"needs {needed.get(resource, 0)} — gathering more {resource} achieves nothing "
            f"until you spend it")
    return lines


def _wall_lines(state: WorldState) -> list[str]:
    far = state.far_counts.get("damaged walls", 0)
    if not state.walls:
        return [f"damaged walls: none in sight ({far} farther away)"] if far else []

    nearest = min(state.walls, key=lambda w: w.dist_m)
    line = (f"damaged walls: {len(state.walls)} in sight"
            + (f" (+{far} farther)" if far else "")
            + f"; nearest {nearest.id} at {nearest.dist_m}m, repaired with {nearest.repair_item}")
    if state.repairable():
        line += f" (you carry {nearest.repair_item})"
    return [line]


def _where_to_get(state: WorldState, resource: str) -> str:
    """Where a resource comes from, near or far. "none close" is not "none
    reachable" — the gather skills walk to the nearest deposit themselves, so
    distance is a delay, not a blocker, and a summary line with no id gives the
    model nothing concrete to act on."""
    close = state.nearest_deposit(resource)
    if close:
        return f"{close.id} at {close.dist_m}m"

    far = state.far_nearest.get(resource)
    if far:
        return f"{far[0]}, {far[1]}m away — a walk, not a blocker"

    pooled = state.far_counts.get("deposits", 0)
    if pooled:
        return f"none within {CLOSE_M}m, {pooled} deposits farther out"
    return "none known"


def _deposit_line(state: WorldState) -> str:
    return "deposits: " + "; ".join(
        f"{resource} {_where_to_get(state, resource)}" for resource in ("wood", "stone"))


def _cover_line(state: WorldState) -> list[str]:
    if not state.covers:
        return []

    nearest = min(state.covers, key=lambda c: c.dist_m)
    return [f"cover: {len(state.covers)} usable; nearest {nearest.id} at "
            f"{nearest.dist_m}m, shields you from {nearest.blocks}"]


def _nothing_to_spend_line(state: WorldState) -> list[str]:
    """The empty-pack case: without this a quiet opening tick reads as 'no
    build, no repair, no close deposit' and the model settles for Hold."""
    if state.carrying or state.depositable() or state.repairable():
        return []
    if not state.deposits and not state.far_counts.get("deposits"):
        return []
    return ["NOTHING TO SPEND: your pack is empty — gather from the nearest deposit, "
            "there is nothing else worth doing this turn"]


def situation_lines(state: WorldState) -> list[str]:
    """The SITUATION block: one short fact per line, no arithmetic left over."""
    lines = [_carrying_line(state), _threat_line(state)]
    lines += _cover_line(state)
    if state.player_dist_m is not None:
        lines.append(f"player: {state.player_dist_m}m away, {state.player_condition}")
    lines += _blueprint_lines(state)
    lines += _wall_lines(state)
    lines.append(_deposit_line(state))
    lines += _surplus_lines(state)
    lines += _nothing_to_spend_line(state)
    return lines
