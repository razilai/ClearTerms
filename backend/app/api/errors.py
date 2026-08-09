"""Map service-layer domain exceptions to HTTP responses."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.exceptions import (
    DomainError,
    DuplicateEmailError,
    FileTooLargeError,
    InvalidCredentialsError,
    InvalidInputError,
    NotFoundError,
    NotOwnerError,
    QueueFullError,
    QueueTimeoutError,
    TooManyAttachmentsError,
    UnsupportedMediaTypeError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        match exc:
            case DuplicateEmailError():
                return JSONResponse(
                    status_code=409, content={"detail": "Email already registered"}
                )
            case InvalidCredentialsError():
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid email or password"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            case NotFoundError(resource=resource):
                return JSONResponse(
                    status_code=404, content={"detail": f"{resource} not found"}
                )
            case NotOwnerError():
                return JSONResponse(
                    status_code=403, content={"detail": "Not the owner"}
                )
            case FileTooLargeError(detail=detail):
                return JSONResponse(status_code=413, content={"detail": detail})
            case UnsupportedMediaTypeError(detail=detail):
                return JSONResponse(status_code=415, content={"detail": detail})
            case TooManyAttachmentsError(detail=detail):
                return JSONResponse(status_code=400, content={"detail": detail})
            case InvalidInputError(detail=detail):
                return JSONResponse(status_code=400, content={"detail": detail})
            case QueueFullError():
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Analysis queue is full, try again shortly"},
                    headers={"Retry-After": "30"},
                )
            case QueueTimeoutError():
                return JSONResponse(
                    status_code=504,
                    content={
                        "detail": "Analysis is taking longer than expected, try again shortly"
                    },
                )
            case _:
                raise exc
