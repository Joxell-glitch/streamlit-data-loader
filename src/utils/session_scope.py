from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Callable, Iterator

@contextmanager
def session_scope(factory: Callable[[], Any]) -> Iterator[Any]:
    obj = factory()
    # alcuni test passano una funzione come "session": dereferenzia una volta
    if callable(obj) and not hasattr(obj, "execute"):
        obj = obj()

    if hasattr(obj, "__enter__") and hasattr(obj, "__exit__"):
        with obj as session:
            yield session
        return

    session = obj
    try:
        yield session
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
