from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator


def _looks_like_session(obj: Any) -> bool:
    # Heuristic: SQLAlchemy Session (or test doubles) usually have these.
    for attr in ("execute", "add", "commit"):
        if hasattr(obj, attr):
            return True
    return False


@contextmanager
def session_scope(factory: Callable[[], Any]) -> Iterator[Any]:
    """
    Normalize db session factories used across runtime and tests.

    Supports:
    - factory() -> context manager session
    - factory() -> session object
    - factory() -> callable that returns session (some tests)
    - factory() -> callable -> callable -> session (rare but safe)
    """
    obj: Any = factory()

    # Unwrap callable results up to 2 levels, but never unwrap if it already
    # looks like a session or a context manager.
    for _ in range(2):
        if hasattr(obj, "__enter__") and hasattr(obj, "__exit__"):
            break
        if _looks_like_session(obj):
            break
        if callable(obj):
            obj = obj()
            continue
        break

    if hasattr(obj, "__enter__") and hasattr(obj, "__exit__"):
        with obj as s:
            yield s
        return

    s = obj
    try:
        yield s
    finally:
        close = getattr(s, "close", None)
        if callable(close):
            close()
