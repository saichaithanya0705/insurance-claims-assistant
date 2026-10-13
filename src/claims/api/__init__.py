"""The HTTP service: the FastAPI app, accounts and sessions.

The app is in ``claims.api.main``. ``claims.api:app`` still resolves to it, so ``uvicorn claims.api:app`` keeps
working. The two names are looked up on first use and nothing else is: ``main`` builds the app, and opens the
databases, as soon as it is imported, and importing ``claims.api.auth`` must not do that.
"""

import importlib

_FROM_MAIN = ("app", "create_app")


def __getattr__(name):
    if name in _FROM_MAIN:
        return getattr(importlib.import_module("claims.api.main"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
