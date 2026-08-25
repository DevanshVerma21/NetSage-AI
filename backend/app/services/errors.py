"""Service-layer errors, each carrying the HTTP status the API should return.

Keeping the status on the error lets the routers stay thin (they translate, they do not
decide) while the *rules* about what is and is not allowed live in the services, where the
tests exercise them directly without going through HTTP.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class. ``status_code`` is what the API layer returns."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    status_code = 404


class ConflictError(ServiceError):
    """The request is well-formed but not allowed in the current state.

    Used for every human-review gate violation: applying a fix with no review, applying a
    rejected diagnosis, reviewing the same diagnosis twice, applying twice.
    """

    status_code = 409


class ValidationError(ServiceError):
    """The request is missing something this verdict requires."""

    status_code = 422
