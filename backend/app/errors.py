"""Error replies in the shape agreed in the API contract.

Every error the API returns looks like:
    { "error": "conflict", "message": "This room is already booked for that time." }
plus extra fields when needed (for example the conflict pop-up details).

Code anywhere in the backend can simply `raise ApiError(...)`; the handlers
below turn it into that JSON reply.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, error: str, message: str, **extra: Any):
        self.status = status
        self.error = error
        self.message = message
        self.extra = extra


# Shortcuts for the error codes in the contract.
def invalid_input(message: str) -> ApiError:
    return ApiError(400, "invalid_input", message)


def reason_required() -> ApiError:
    return ApiError(400, "reason_required", "A reason is required for this change.")


def not_logged_in(message: str = "Please log in.") -> ApiError:
    return ApiError(401, "not_logged_in", message)


def forbidden(message: str = "You are not allowed to do this.") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


# Map plain HTTP status codes to contract error codes, for errors raised by
# FastAPI itself (e.g. an address that does not exist).
_STATUS_TO_CODE = {
    400: "invalid_input",
    401: "not_logged_in",
    403: "forbidden",
    404: "not_found",
    405: "invalid_input",
    409: "conflict",
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        body = {"error": exc.error, "message": exc.message, **exc.extra}
        return JSONResponse(status_code=exc.status, content=body)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default here is status 422 with a long list. The contract
        # says 400 invalid_input, so we turn the first problem into a
        # readable message, e.g. "start: Field required".
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(p) for p in first.get("loc", []) if p not in ("body", "query"))
        message = first.get("msg", "Invalid input.")
        if location:
            message = f"{location}: {message}"
        return JSONResponse(
            status_code=400, content={"error": "invalid_input", "message": message}
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            status_code=exc.status_code, content={"error": code, "message": message}
        )
