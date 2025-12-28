from contextlib import contextmanager


@contextmanager
def session_scope(factory):
    obj = factory()
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
