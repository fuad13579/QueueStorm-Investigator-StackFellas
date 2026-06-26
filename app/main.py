"""FastAPI entry point for the QueueStorm Investigator service."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.investigator import investigate
from app.models import (
    AnalyzeTicketRequest,
    AnalyzeTicketResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
)

load_dotenv()

logger = logging.getLogger("queuestorm.investigator")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())

app = FastAPI(
    title="QueueStorm Investigator",
    version="0.1.0",
    description="Analyzes support tickets and recommends remediation actions.",
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse()


# ---------------------------------------------------------------------------
# Analyze ticket
# ---------------------------------------------------------------------------


@app.post(
    "/analyze-ticket",
    response_model=AnalyzeTicketResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Malformed business input"},
        422: {"model": ErrorResponse, "description": "Schema validation failure"},
        500: {"model": ErrorResponse, "description": "Internal investigator failure"},
    },
    tags=["investigator"],
)
def analyze_ticket(req: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    """Analyze a single support ticket and return a placeholder diagnosis."""
    try:
        return investigate(req)
    except ValueError as exc:
        # Business-rule violations (bad dates, conflicting fields, etc.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "bad_request", "message": str(exc)},
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("investigator failure for ticket=%s", req.ticket.ticket_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "investigator_error",
                "message": "Investigator pipeline failed.",
            },
        ) from exc


# ---------------------------------------------------------------------------
# Error handlers — produce the consistent ErrorResponse envelope.
# ---------------------------------------------------------------------------


def _envelope(code: str, message: str, field: str | None = None) -> Dict[str, Any]:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, field=field))
    return body.model_dump(mode="json")


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", []))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_envelope(
            code="validation_error",
            message=first.get("msg", "Invalid request payload."),
            field=loc or None,
        ),
    )


@app.exception_handler(HTTPException)
async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        content = _envelope(
            code=str(detail.get("code", "http_error")),
            message=str(detail.get("message", exc.detail)),
        )
    else:
        content = _envelope(code="http_error", message=str(detail))
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            code="internal_error",
            message="An unexpected error occurred.",
        ),
    )
