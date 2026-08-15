from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import local
from time import monotonic


@dataclass
class BuilderSearchControl:
    deadline: float | None = None
    cancel_event: object | None = None
    started_at: float = field(default_factory=monotonic)
    stop_reason: str = ""
    counters: dict[str, int] = field(default_factory=dict)
    caches: dict[str, dict] = field(default_factory=dict)

    def should_stop(self, deadline: float | None = None) -> bool:
        if self.stop_reason:
            return True
        if self.cancel_event is not None and bool(getattr(self.cancel_event, "is_set", lambda: False)()):
            self.stop_reason = "cancelled"
            return True
        effective_deadline = self.deadline
        if deadline is not None:
            effective_deadline = deadline if effective_deadline is None else min(effective_deadline, deadline)
        if effective_deadline is not None and monotonic() >= effective_deadline:
            self.stop_reason = "deadline"
            return True
        return False

    def count(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def metrics(self) -> dict[str, object]:
        return {
            "elapsed_ms": max(0, int(round((monotonic() - self.started_at) * 1000))),
            "stop_reason": self.stop_reason or "complete",
            **self.counters,
        }


_SEARCH_STATE = local()


@contextmanager
def builder_search_scope(*, deadline: float | None, cancel_event=None):
    previous = getattr(_SEARCH_STATE, "control", None)
    if previous is not None:
        yield previous
        return
    control = BuilderSearchControl(deadline=deadline, cancel_event=cancel_event)
    _SEARCH_STATE.control = control
    try:
        yield control
    finally:
        _SEARCH_STATE.control = previous


def current_builder_search_control() -> BuilderSearchControl | None:
    return getattr(_SEARCH_STATE, "control", None)


def builder_search_should_stop(deadline: float | None = None) -> bool:
    control = current_builder_search_control()
    if control is not None:
        return control.should_stop(deadline)
    return deadline is not None and monotonic() >= deadline


def count_builder_search_work(name: str, amount: int = 1) -> None:
    control = current_builder_search_control()
    if control is not None:
        control.count(name, amount)


def builder_search_cache(name: str) -> dict | None:
    control = current_builder_search_control()
    if control is None:
        return None
    return control.caches.setdefault(name, {})


def store_bounded_cache_entry(cache: dict, key, value, *, max_entries: int) -> None:
    if key not in cache and len(cache) >= max_entries:
        cache.pop(next(iter(cache)))
    cache[key] = value
