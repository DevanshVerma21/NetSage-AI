"""The HTTP layer.

Routers are thin: they parse, call a service, and translate a
:class:`~backend.app.services.errors.ServiceError` into a status code. Every decision about
what is permitted lives in the services, where it is tested without HTTP.
"""

from __future__ import annotations

from backend.app.api.router import api_router

__all__ = ["api_router"]
