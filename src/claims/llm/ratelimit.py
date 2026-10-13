"""A shared budget of model requests per minute, so optional model work can never starve the model work every run needs.

The model provider limits how many requests a key may make a minute (NVIDIA NIM answered HTTP 429 to nearly every call, the brief's
own included, when a stream of investigations went over it). The gate keeps one sliding one-minute window per provider endpoint.
Essential calls (the brief's classification, findings and recommendations, the intake reader, the judge) wait for a free slot.
Optional calls (an agent's follow-up searches) are allowed only while a reserve of slots is left for the essential ones, and
otherwise are skipped, so the agent keeps its standard result and the brief is never delayed by them.

The provider's real limit is not published and changes (about 15 requests a minute on 12 October, against the 25 a minute the
application had been making), so the budget adapts: a 429 halves it, down to a floor, and a run of successes raises it again towards
the configured ceiling. A key throttled harder than expected slows investigations down instead of failing them.
"""

import threading
import time
from collections import deque

FLOOR = 6  # the budget never falls below this many requests a minute (or the ceiling, if that is lower)
RAISE_AFTER = 8  # successes in a row before the budget is raised by one


class RateGate:
    def __init__(self, per_minute: int, reserve: int, clock=time.monotonic, sleep=time.sleep):
        self.ceiling, self._reserve = per_minute, reserve
        self.limit = per_minute
        self._clock, self._sleep = clock, sleep
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._streak, self._last_throttle = 0, None

    @property
    def reserve(self) -> int:
        return min(self._reserve, max(self.limit - 1, 0))

    def _trim(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] >= 60:
            self._stamps.popleft()

    def free(self) -> int:
        with self._lock:
            self._trim(self._clock())
            return self.limit - len(self._stamps)

    def throttled(self) -> None:
        """The provider answered 429: halve the budget (at most once every few seconds, so one burst counts once)."""
        with self._lock:
            now = self._clock()
            self._streak = 0
            if self._last_throttle is None or now - self._last_throttle > 5:
                self.limit = max(min(FLOOR, self.ceiling), self.limit // 2)
                self._last_throttle = now

    def succeeded(self) -> None:
        with self._lock:
            self._streak += 1
            if self._streak >= RAISE_AFTER and self.limit < self.ceiling:
                self.limit += 1
                self._streak = 0

    def acquire(self, *, optional: bool = False, max_wait: float = 20.0) -> bool:
        """Take a slot. An optional call gets one only while more than the reserve is free, else False at once. An essential call
        waits up to ``max_wait`` seconds for one, and goes ahead anyway when the wait would be longer (the provider then decides)."""
        started = self._clock()
        while True:
            with self._lock:
                now = self._clock()
                self._trim(now)
                free = self.limit - len(self._stamps)
                if optional:
                    if free > self.reserve:
                        self._stamps.append(now)
                        return True
                    return False
                if free > 0:
                    self._stamps.append(now)
                    return True
                wait = 60 - (now - self._stamps[0])
            if now - started + wait > max_wait:
                with self._lock:
                    self._stamps.append(now)
                return True
            self._sleep(max(wait, 0.05))


_gates: dict[str, RateGate] = {}
_gates_lock = threading.Lock()


def gate_for(settings) -> RateGate | None:
    """The gate for this provider endpoint, shared by every client in the process; None when the budget is switched off (0)."""
    if settings.llm_requests_per_minute <= 0:
        return None
    key = f"{settings.llm_base_url}|{settings.llm_requests_per_minute}|{settings.llm_optional_reserve}"
    with _gates_lock:
        if key not in _gates:
            _gates[key] = RateGate(settings.llm_requests_per_minute, settings.llm_optional_reserve)
        return _gates[key]
