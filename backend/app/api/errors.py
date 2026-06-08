from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


STATUS_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}


def error_code_for_status(status_code: int) -> str:
    if status_code in STATUS_ERROR_CODES:
        return STATUS_ERROR_CODES[status_code]
    if status_code >= 500:
        return "internal_server_error"
    return "http_error"


def status_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP error"


def error_payload(status_code: int, detail: Any = None, *, code: str | None = None, message: str | None = None, details: Any = None) -> dict[str, Any]:
    if isinstance(detail, dict) and {"code", "message"}.issubset(detail):
        return {
            "code": str(detail["code"]),
            "message": str(detail["message"]),
            "details": detail.get("details"),
        }
    return {
        "code": code or error_code_for_status(status_code),
        "message": message or (detail if isinstance(detail, str) else status_message(status_code)),
        "details": details if details is not None else (None if isinstance(detail, str) else detail),
    }


async def http_exception_handler(_request: Request, exc: HTTPException | StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(error_payload(exc.status_code, exc.detail)), headers=exc.headers)


async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(error_payload(422, code="validation_error", message="Request validation failed", details=exc.errors())),
    )


async def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_payload(500, message="Internal server error"),
    )


def add_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
