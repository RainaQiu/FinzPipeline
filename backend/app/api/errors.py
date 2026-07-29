"""Consistent, correlation-aware API error responses."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.ingestion import IngestionError
from app.services.ledger_bridge import LedgerBridgeError


def _correlation_id(request: Request) -> str:
    return request.headers.get("x-correlation-id") or uuid4().hex


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: object = None,
) -> JSONResponse:
    correlation_id = _correlation_id(request)
    return JSONResponse(
        status_code=status_code,
        headers={"x-correlation-id": correlation_id},
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "correlation_id": correlation_id,
                "details": details if details is not None else {},
            }
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LedgerBridgeError)
    async def ledger_bridge_error(
        request: Request, error: LedgerBridgeError
    ) -> JSONResponse:
        return _response(
            request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
        )

    @app.exception_handler(IngestionError)
    async def ingestion_error(request: Request, error: IngestionError) -> JSONResponse:
        return _response(
            request,
            status_code=422,
            code="invalid_ingestion",
            message=str(error),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": list(item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return _response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=details,
        )
