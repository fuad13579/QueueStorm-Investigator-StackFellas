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
#
# Each ``Literal[...]`` defines a closed set of allowed string values. The
# investigator layer (``app/investigator.py``) and the safety layer
# (``app/safety.py``) only ever emit these strings, and the FastAPI router
# rejects any request/response field that uses a value outside the set
# with a 422 ``validation_error``.
#
# Example (request body for a wrong-transfer ticket):
#     {
#         "ticket_id": "TKT-001",
#         "complaint": "I sent 1000 to the wrong number.",
#         "language": "en",
#         "case_type": "wrong_transfer"        # <- matches one of the literals
#     }

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
#
# One row of the customer's recent ledger snippet that accompanies the
# ticket. The investigator uses these entries to match the complaint to
# a specific transaction (see ``app.investigator.match_transaction``).
#
# Example (a successful 2000 BDT transfer to a phone number):
#     {
#         "transaction_id": "TXN-9701",
#         "timestamp": "2026-06-26T09:14:22Z",
#         "type": "transfer",
#         "amount": 2000.0,
#         "counterparty": "+8801712345678",
#         "status": "completed"
#     }

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
#
# The body of ``POST /analyze-ticket``. Only ``ticket_id`` and
# ``complaint`` are required; everything else is best-effort context that
# the investigator uses to enrich its analysis.
#
# Example (minimal valid request):
#     {
#         "ticket_id": "TKT-042",
#         "complaint": "My payment failed but my balance was deducted."
#     }
#
# Example (full request with history):
#     {
#         "ticket_id": "TKT-042",
#         "complaint": "Payment failed but balance deducted.",
#         "language": "en",
#         "channel": "in_app_chat",
#         "user_type": "customer",
#         "transaction_history": [
#             {"transaction_id": "TXN-1", "timestamp": "2026-06-26T08:00:00Z",
#              "type": "payment", "amount": 1500.0, "counterparty": "M-77",
#              "status": "failed"}
#         ]
#     }

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
#
# The structured diagnosis produced by the investigator. The
# ``customer_reply`` field is the only customer-facing string and is
# guaranteed (by ``app/safety.py``) to never ask for credentials, never
# confirm a refund, and never point at a suspicious third party.
#
# Example (typical payment_failed diagnosis):
#     {
#         "ticket_id": "TKT-042",
#         "relevant_transaction_id": "TXN-1",
#         "evidence_verdict": "consistent",
#         "case_type": "payment_failed",
#         "severity": "high",
#         "department": "payments_ops",
#         "agent_summary": "Ticket TKT-042: customer reports a 'payment_failed'...",
#         "recommended_next_action": "Confirm whether the balance was deducted...",
#         "customer_reply": "Dear customer, ... For your security, we will never...",
#         "human_review_required": true,
#         "confidence": 0.90,
#         "reason_codes": ["payment_failed", "transaction_match",
#                          "tx_status_failed", "verdict_consistent"]
#     }

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
#
# ``HealthResponse`` powers the liveness probe at ``GET /health`` (used by
# Render to decide whether the container is healthy).
#
# Example:
#     GET /health   ->  {"status": "ok"}
#
# ``ErrorResponse`` is the uniform 4xx/5xx envelope. ``app.main`` wraps
# every exception through this shape so the client always sees the same
# JSON structure regardless of which handler fired.
#
# Example (validation failure on POST /analyze-ticket):
#     {
#         "error": {
#             "code": "validation_error",
#             "message": "complaint: field required",
#             "field": "complaint"
#         }
#     }
#
# Example (HTTPException raised inside the handler):
#     {
#         "error": {
#             "code": "investigator_error",
#             "message": "Investigator pipeline failed."
#         }
#     }

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
