"""Skill catalog: the single source of truth for what each skill *is*.

Skills are declared in `skills.json` (path via `settings.skills_file`) and
loaded into a validated registry at import. Everything that needs skill
knowledge — the model brain's prompt menu, the heuristic ladder, repair
fallback acks — reads from this registry. Adding a skill to the service is
a JSON edit; the Unity side pairs it with a `SkillWorker` that executes it.
"""

import json
from pathlib import Path

from pydantic import BaseModel

from .config import settings
from .schema import ALWAYS_FEASIBLE_SKILL


class SkillDef(BaseModel):
    """One skill as the controller service understands it.

    `description` says what the skill does; `when`/`avoid` say when it is the
    right or wrong call. A small model picks by pattern-matching its menu, so
    the preconditions have to be written down next to the skill — a name and
    a verb phrase alone leave it guessing, and it guesses the same way every
    turn.

    `triggers` drives the heuristic brain: a list of groups where EVERY
    group must match, and a group matches if ANY of its substrings occurs
    in the lowercased SSG. Skills without triggers are model-only — the
    heuristic never proposes them.
    """
    name: str
    description: str
    when: str = ""
    avoid: str = ""
    ack: str = ""
    priority: int = 0                       # heuristic order: higher is tried first
    triggers: list[list[str]] | None = None
    # Which kinds of SSG object this skill can act on ("wood", "stone",
    # "blueprint", "wall", "threat"). Empty means any id goes — used to reject
    # a target the skill could never resolve, like Build aimed at a deposit.
    target_kinds: list[str] = []

    def matches(self, ssg_lower: str) -> bool:
        if self.triggers is None:
            return False
        return all(any(t in ssg_lower for t in group) for group in self.triggers)


class SkillRegistry:
    def __init__(self, skills: list[SkillDef]):
        self._by_name = {s.name: s for s in skills}
        if len(self._by_name) != len(skills):
            raise ValueError("duplicate skill names in catalog")
        if ALWAYS_FEASIBLE_SKILL not in self._by_name:
            raise ValueError(f"catalog must define '{ALWAYS_FEASIBLE_SKILL}'")

    @property
    def hold(self) -> SkillDef:
        return self._by_name[ALWAYS_FEASIBLE_SKILL]

    def get(self, name: str) -> SkillDef | None:
        return self._by_name.get(name)

    def describe(self, name: str) -> str:
        s = self._by_name.get(name)
        return s.description if s else "no description"

    def menu_line(self, name: str) -> str:
        """One skill as the model sees it in its menu: what it does, and the
        preconditions that make it right or wrong."""
        s = self._by_name.get(name)
        if s is None:
            return f"- {name}"
        line = f"- {name} — {s.description}."
        if s.when:
            line += f" USE IF: {s.when}."
        if s.avoid:
            line += f" SKIP IF: {s.avoid}."
        if s.target_kinds:
            line += f" TARGET: a {' or '.join(s.target_kinds)} id, or \"\"."
        return line

    def menu(self, names: list[str]) -> str:
        """The feasible menu, most important skill first. Ordering is catalog
        priority, not request order: position is a strong cue for a small
        model, so the urgent skills must not sit below the idle ones."""
        ordered = sorted(names, key=lambda n: -(p.priority if (p := self._by_name.get(n)) else 0))
        return "\n".join(self.menu_line(n) for n in ordered)

    def all(self) -> list[SkillDef]:
        return list(self._by_name.values())

    def by_priority(self) -> list[SkillDef]:
        return sorted(self._by_name.values(), key=lambda s: s.priority, reverse=True)

    @classmethod
    def load(cls, path: Path) -> "SkillRegistry":
        data = json.loads(path.read_text())
        return cls([SkillDef(**s) for s in data["skills"]])


registry = SkillRegistry.load(settings.skills_file)
