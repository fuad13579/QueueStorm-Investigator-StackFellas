"""Pydantic request/response schemas for the QueueStorm Investigator API.

These models intentionally use strict ``str`` enums (via ``StrEnum``/``Literal``)
so that malformed input is rejected with HTTP 422 by FastAPI's validation layer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums (strict, no fuzzy matching)
# ---------------------------------------------------------------------------


class Severity(str, StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(str, StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Environment(str, StrEnum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class IncidentCategory(str, StrEnum):
    INFRASTRUCTURE = "infrastructure"
    APPLICATION = "application"
    DATABASE = "database"
    NETWORK = "network"
    SECURITY = "security"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TicketPayload(BaseModel):
    """Raw support ticket data submitted for analysis."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticket_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=10_000)
    severity: Severity
    status: TicketStatus
    environment: Environment
    category: IncidentCategory
    affected_services: List[str] = Field(default_factory=list, max_length=50)
    reporter: Optional[str] = Field(default=None, max_length=120)


class AnalyzeTicketRequest(BaseModel):
    """Wrapper request for ``POST /analyze-ticket``."""

    model_config = ConfigDict(extra="forbid")

    ticket: TicketPayload


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    likely_root_causes: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class RecommendedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    rationale: str
    priority: Severity


class AnalyzeTicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    diagnosis: Diagnosis
    recommended_actions: List[RecommendedAction]
    environment: Environment
    severity: Severity
    model_version: str = "stub-0.1.0"


# ---------------------------------------------------------------------------
# Error envelope (consistent shape for 400/422/500 responses)
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    field: Optional[str] = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str = "queuestorm-investigator"
    version: str = "0.1.0"
