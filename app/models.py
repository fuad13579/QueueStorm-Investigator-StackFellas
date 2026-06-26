"""Pydantic v2 request/response models for the QueueStorm Investigator API.

These models are the single source of truth for the JSON contract described in
Section 5 (Request Schema) and Section 6 (Response Schema) of the problem
statement. Keeping them in one module lets the FastAPI layer validate input
and the investigator layer build output without duplicating enum lists.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums (must match Section 7 of the problem statement exactly)
# ---------------------------------------------------------------------------

CaseType = Literal[
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
]

EvidenceVerdict = Literal["consistent", "inconsistent", "insufficient_data"]
Severity = Literal["low", "medium", "high", "critical"]

Department = Literal[
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
]

TxnType = Literal[
    "transfer", "payment", "cash_in", "cash_out", "settlement", "refund"
]
TxnStatus = Literal["completed", "failed", "pending", "reversed"]

Channel = Literal[
    "in_app_chat", "call_center", "email", "merchant_portal", "field_agent"
]
UserType = Literal["customer", "merchant", "agent", "unknown"]
Language = Literal["en", "bn", "mixed"]


# ---------------------------------------------------------------------------
# Transaction history entry (Section 5.2)
# ---------------------------------------------------------------------------

class TransactionHistoryEntry(BaseModel):
    """One transaction in the customer's recent history snippet."""

    model_config = ConfigDict(extra="allow")

    transaction_id: str = Field(..., description="Unique transaction identifier.")
    timestamp: str = Field(..., description="ISO-8601 timestamp.")
    type: TxnType
    amount: float = Field(..., description="Amount in BDT.")
    counterparty: str = Field(
        ..., description="Recipient phone, merchant ID, or agent ID."
    )
    status: TxnStatus


# ---------------------------------------------------------------------------
# Request schema (Section 5.1)
# ---------------------------------------------------------------------------

class AnalyzeTicketRequest(BaseModel):
    """Body of ``POST /analyze-ticket``."""

    model_config = ConfigDict(extra="allow")

    ticket_id: str
    complaint: str = Field(..., min_length=1)
    language: Optional[Language] = "en"
    channel: Optional[Channel] = None
    user_type: Optional[UserType] = None
    campaign_context: Optional[str] = None
    transaction_history: List[TransactionHistoryEntry] = Field(
        default_factory=list
    )
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Response schema (Section 6.1)
# ---------------------------------------------------------------------------

class AnalyzeTicketResponse(BaseModel):
    """Body returned by ``POST /analyze-ticket``."""

    ticket_id: str
    relevant_transaction_id: Optional[str] = None
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)


__all__ = [
    "CaseType",
    "EvidenceVerdict",
    "Severity",
    "Department",
    "TxnType",
    "TxnStatus",
    "Channel",
    "UserType",
    "Language",
    "TransactionHistoryEntry",
    "AnalyzeTicketRequest",
    "AnalyzeTicketResponse",
]


# ---------------------------------------------------------------------------
# Error envelope and health models (used by app.main's exception handlers).
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Body returned by ``GET /health``."""

    status: str = "ok"


class ErrorDetail(BaseModel):
    """Inner ``error`` payload of an ``ErrorResponse``."""

    code: str
    message: str
    field: Optional[str] = None


class ErrorResponse(BaseModel):
    """Uniform error envelope returned for 4xx/5xx responses."""

    error: ErrorDetail


__all__ += ["HealthResponse", "ErrorDetail", "ErrorResponse"]
