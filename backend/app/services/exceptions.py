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


class InvalidInputError(DomainError):
    """Request was well-formed but semantically invalid (e.g. duplicate keys)."""

    def __init__(self, detail: str = "invalid input") -> None:
        super().__init__(detail)
        self.detail = detail


class FileTooLargeError(DomainError):
    """Uploaded file exceeds the size limit."""

    def __init__(self, detail: str = "file too large") -> None:
        super().__init__(detail)
        self.detail = detail


class UnsupportedMediaTypeError(DomainError):
    """Uploaded file's MIME type is not allowed."""

    def __init__(self, detail: str = "unsupported media type") -> None:
        super().__init__(detail)
        self.detail = detail


class TooManyAttachmentsError(DomainError):
    """Post or comment would exceed the attachment limit."""

    def __init__(self, detail: str = "too many attachments") -> None:
        super().__init__(detail)
        self.detail = detail


class QueueFullError(DomainError):
    """Analysis queue is at capacity; the caller should retry later."""


class QueueTimeoutError(DomainError):
    """Caller's wait for the analysis result expired.

    The job itself is NOT cancelled — it keeps running (queued or already
    in progress) and still populates the analysis cache, so a retry is
    likely to be a cache hit.
    """
