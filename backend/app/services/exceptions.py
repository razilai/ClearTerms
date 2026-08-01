"""Domain exceptions raised by services; mapped to HTTP responses in app.api.errors.

Services must stay free of fastapi imports, so they signal failures with these
and the api layer translates them.
"""


class DomainError(Exception):
    """Base class for all service-layer errors."""


class DuplicateEmailError(DomainError):
    """Signup with an email that already has an account."""


class InvalidCredentialsError(DomainError):
    """Login with an unknown email or wrong password."""


class InvalidTokenError(DomainError):
    """Bearer token is malformed, tampered with, or expired."""


class NotFoundError(DomainError):
    """Requested resource does not exist."""

    def __init__(self, resource: str = "resource") -> None:
        super().__init__(resource)
        self.resource = resource


class NotOwnerError(DomainError):
    """Caller is not the owner of the resource they tried to modify."""
