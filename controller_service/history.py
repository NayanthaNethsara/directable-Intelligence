"""What the companion has recently done, per session.

The SSG describes the world, not the companion's own choices. Without this
a quiet tick looks identical to the previous one, so a small model re-picks
the same skill forever — the wood-gathering loop. Kept service-side rather
than in the request so `schema.py`, the contract with Unity, stays untouched.

In memory and bounded: a run's history is disposable, the JSONL decision log
is the durable record.
"""

import threading
from collections import OrderedDict, deque

DEPTH = 8                       # decisions remembered per session
MAX_SESSIONS = 64               # oldest session evicted beyond this


class DecisionHistory:
    def __init__(self, depth: int = DEPTH, max_sessions: int = MAX_SESSIONS):
        self._depth = depth
        self._max_sessions = max_sessions
        self._by_session: OrderedDict[str, deque[str]] = OrderedDict()
        self._lock = threading.Lock()        # /decide runs in FastAPI's threadpool

    def record(self, session_id: str, skill: str) -> None:
        with self._lock:
            skills = self._by_session.get(session_id)
            if skills is None:
                skills = deque(maxlen=self._depth)
                self._by_session[session_id] = skills
            skills.append(skill)
            self._by_session.move_to_end(session_id)
            while len(self._by_session) > self._max_sessions:
                self._by_session.popitem(last=False)

    def recent(self, session_id: str) -> list[str]:
        """Most recent decision first."""
        with self._lock:
            return list(reversed(self._by_session.get(session_id, ())))

    def streak(self, session_id: str) -> tuple[str, int]:
        """The skill currently being repeated and how many turns in a row."""
        recent = self.recent(session_id)
        if not recent:
            return "", 0
        skill = recent[0]
        run = 0
        for chosen in recent:
            if chosen != skill:
                break
            run += 1
        return skill, run


history = DecisionHistory()
