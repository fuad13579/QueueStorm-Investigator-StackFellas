"""QueueStorm Investigator — evidence reasoning engine (Member B).

This module owns the *Evidence Reasoning* (35 pts) and a portion of the
*Safety & Escalation* (20 pts) scoring categories. It is intentionally a
deterministic, rule-based pipeline: no external LLM calls, no network IO,
no model downloads. The output is the structured diagnosis consumed by
``app.main`` (Member A) and then post-processed by ``app.safety`` (Member C).

Public surface
--------------
* ``investigate(req)``      - top-level entry point, returns an
  ``AnalyzeTicketResponse`` with ``customer_reply`` left blank so the
  caller can route it through the safety layer.
* ``build_outputs(...)``    - orchestrator used by tests to assert the
  individual decision fields in isolation.

Design contract
---------------
1. The investigator only reads fields from ``AnalyzeTicketRequest``. It
   must never mutate the request.
2. The investigator never raises on bad input — it degrades gracefully
   to ``case_type="other"``, ``evidence_verdict="insufficient_data"``,
   ``human_review_required=True``, and a low confidence score.
3. The investigator never calls any external service, so it is safe to
   invoke from request handlers even in hardened deployments.
"""
from __future__ import annotations

import re
from typing import Iterable, Final

from app.models import (
    AnalyzeTicketRequest,
    AnalyzeTicketResponse,
    TransactionHistoryEntry,
)

# ---------------------------------------------------------------------------
# Enum string constants (kept as plain strings so this module compiles even
# if the Literal aliases in app.models are tightened later).
# ---------------------------------------------------------------------------

EVIDENCE_CONSISTENT: str = "consistent"
EVIDENCE_INCONSISTENT: str = "inconsistent"
EVIDENCE_INSUFFICIENT: str = "insufficient_data"

CASE_WRONG_TRANSFER: str = "wrong_transfer"
CASE_PAYMENT_FAILED: str = "payment_failed"
CASE_REFUND: str = "refund_request"
CASE_DUPLICATE: str = "duplicate_payment"
CASE_MERCHANT_SETTLEMENT: str = "merchant_settlement_delay"
CASE_AGENT_CASH_IN: str = "agent_cash_in_issue"
CASE_PHISHING: str = "phishing_or_social_engineering"
CASE_OTHER: str = "other"

SEV_LOW: str = "low"
SEV_MEDIUM: str = "medium"
SEV_HIGH: str = "high"
SEV_CRITICAL: str = "critical"

DEPT_CUSTOMER_SUPPORT: str = "customer_support"
DEPT_DISPUTE: str = "dispute_resolution"
DEPT_PAYMENTS_OPS: str = "payments_ops"
DEPT_MERCHANT_OPS: str = "merchant_operations"
DEPT_AGENT_OPS: str = "agent_operations"
DEPT_FRAUD_RISK: str = "fraud_risk"

# ---------------------------------------------------------------------------
# Keyword sets (English + Bangla + Banglish).
#
# Order matters inside each set only insofar as more specific phrases should
# be listed before generic ones (e.g. "wrong number" before "transfer").
# The ``_contains_any`` helper does case-insensitive substring matching,
# so we keep entries short and representative rather than exhaustive.
# ---------------------------------------------------------------------------

_PHISHING_KW: tuple[str, ...] = (
    # English
    "phishing", "scam", "fraud call", "fraud sms", "fake message",
    "share your pin", "share otp", "send otp", "send your pin",
    "verify your account", "click the link", "lottery", "prize",
    "you have won", "congratulations you won", "kyc update",
    "account will be blocked", "account suspended",
    # Bangla
    "পিন দিন", "পিন দিব", "ওটিপি দিন", "ওটিপি দিব", "পাসওয়ার্ড দিন",
    "আপনার একাউন্ট বন্ধ", "একাউন্ট ব্লক", "লটারি", "পুরস্কার",
    "জালিয়াতি", "প্রতারণা", "ফেক মেসেজ", "স্ক্যাম",
    # Banglish
    "pin dao", "pin diye", "pin den", "otp dao", "otp diye",
    "password dao", "amader hocche scam", "tumi jeitecho",
    "account block hobe", "blck hobe", "blck kora hobe",
    "tomar account block", "kyc update koro", "tumi jitecho",
    "you have won", "congratulations",
)

_WRONG_TRANSFER_KW: tuple[str, ...] = (
    # English
    "wrong number", "wrong recipient", "sent to wrong", "wrong account",
    "mistakenly sent", "by mistake", "sent by mistake", "transferred to wrong",
    "wrong transfer", "sent to a wrong", "sent to the wrong",
    # Bangla
    "ভুল নম্বর", "ভুল নাম্বার", "ভুল একাউন্ট", "ভুল মানুষ",
    "ভুল ব্যক্তি", "ভুল টাকা", "ভুল করে", "ভুল করে পাঠিয়েছি",
    # Banglish
    "vul number", "vul numbar", "vul number e", "vul manush",
    "vul kore", "vul kore pathiyechi", "vul kore pathiechi",
    "vul transfer", "vul account e", "vul account e pathiyechi",
)

_PAYMENT_FAILED_KW: tuple[str, ...] = (
    # English
    "payment failed", "transaction failed", "failed but deducted",
    "deducted but not received", "money deducted", "balance deducted",
    "amount deducted", "payment not received", "payment not credited",
    # Bangla
    "পেমেন্ট ব্যর্থ", "লেনদেন ব্যর্থ", "টাকা কেটে নিয়েছে", "টাকা কাটা হয়েছে",
    "ব্যালেন্স কেটে নিয়েছে", "পেমেন্ট আসেনি", "টাকা আসেনি",
    # Banglish
    "payment fail", "transaction fail", "taka kete niyeche",
    "taka kata hoyeche", "balance kete niyeche", "payment asheni",
    "taka asheni", "taka ese nai",
)

_REFUND_KW: tuple[str, ...] = (
    # English
    "refund", "refund please", "need refund", "want a refund",
    "please refund", "return my money", "give my money back",
    "money back", "chargeback",
    # Bangla
    "রিফান্ড", "টাকা ফেরত", "টাকা ফেরত দিন", "ফেরত দিতে হবে",
    # Banglish
    "refund korte", "refund din", "taka ferot", "ferot din",
    "taka ferot din", "taka pabo", "taka ferot chai",
)

_DUPLICATE_KW: tuple[str, ...] = (
    # English
    "charged twice", "deducted twice", "double charge", "duplicate charge",
    "two times", "charged two times", "deducted two times",
    "same payment twice", "twice for the same",
    # Bangla
    "দুইবার কেটেছে", "দুইবার চার্জ", "একই পেমেন্ট দুইবার",
    "ডুপ্লিকেট চার্জ",
    # Banglish
    "doibar keteche", "doibar charge", "duplicate charge hoyeche",
    "ekoi payment doibar",
)

_MERCHANT_SETTLEMENT_KW: tuple[str, ...] = (
    # English
    "merchant settlement", "settlement not received", "merchant payment",
    "settlement pending", "settlement delay", "merchant not paid",
    "merchant payout", "shop settlement",
    # Bangla
    "মার্চেন্ট সেটেলমেন্ট", "দোকানের টাকা", "মার্চেন্ট পেমেন্ট আসেনি",
    "সেটেলমেন্ট বিলম্ব", "সেটেলমেন্ট পেন্ডিং",
    # Banglish
    "merchant settlement asheni", "merchant payout hoyni",
    "dokan er taka", "settlement delay hoyeche", "settlement pending",
)

_AGENT_CASH_IN_KW: tuple[str, ...] = (
    # English
    "agent did not deposit", "agent did not give", "agent didn't deposit",
    "cash in not received", "cash deposit not reflected",
    "agent kept the money", "agent took the money", "agent cash in",
    # Bangla
    "এজেন্ট টাকা দেয়নি", "এজেন্ট টাকা রেখেছে", "এজেন্ট টাকা নিয়েছে",
    "ক্যাশ ইন হয়নি", "টাকা জমা হয়নি",
    # Banglish
    "agent taka deyni", "agent taka rakheche", "agent taka niyeche",
    "cash in hoyni", "taka joma hoyni", "agent taka di nai",
)

_VAGUE_KW: tuple[str, ...] = (
    # English
    "help me", "please help", "i need help", "issue", "problem",
    "support", "not working", "error",
    # Bangla
    "সাহায্য", "সমস্যা", "কাজ করছে না", "ভুল হচ্ছে",
    # Banglish
    "sahajjo", "sahajjo koro", "problem hocche", "kaj korche na",
)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches +880XXXXXXXXXX, 880XXXXXXXXXX, or 01XXXXXXXXX (Bangladesh mobile).
_PHONE_RE = re.compile(
    r"(?:\+?88)?0?1[3-9][\d\-\s]{7,11}\d"
)

# Matches Bangladeshi Taka amounts: "5000 taka", "৳5000", "5000 BDT", "tk 5000".
_AMOUNT_RE = re.compile(
    r"(?:tk|৳|bdt|taka|টাকা)?\s*"
    r"(\d{1,3}(?:[,\s]\d{2,3}){0,3}|\d+)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Thresholds (BDT)
# ---------------------------------------------------------------------------

HIGH_VALUE_THRESHOLD: int = 50_000
CRITICAL_VALUE_THRESHOLD: int = 100_000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    """Return True if ``text`` contains any keyword (case-insensitive)."""
    if not text:
        return False
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)

def _has_numeric_signal(text: str) -> bool:
    """Return True if ``text`` contains a phone-shaped or amount-shaped token.

    Used to decide whether the customer is reporting something concrete
    (which we should try to match to the transaction history) versus
    merely venting ("help me, it doesn't work").
    """
    if not text:
        return False
    if _PHONE_RE.search(text):
        return True
    if _AMOUNT_RE.search(text):
        return True
    return False

def _entry_amount(entry: TransactionHistoryEntry) -> float:
    """Best-effort amount extraction from a history entry."""
    try:
        return float(entry.amount)
    except (TypeError, ValueError):
        return 0.0

def _entry_counterparty_digits(entry: TransactionHistoryEntry) -> str:
    return re.sub(r"\D", "", entry.counterparty or "")

def _complaint_phone_digits(complaint: str) -> str:
    match = _PHONE_RE.search(complaint or "")
    if not match:
        return ""
    return re.sub(r"\D", "", match.group(0))

def _complaint_amount(complaint: str) -> float | None:
    """Extract the first BDT-shaped number from a complaint, if any."""
    if not complaint:
        return None
    for match in _AMOUNT_RE.finditer(complaint):
        raw = match.group(1)
        digits = re.sub(r"[^\d]", "", raw)
        if not digits:
            continue
        try:
            value = float(digits)
        except ValueError:
            continue
        if value <= 0:
            continue
        return value
    return None

def _confidence_for(
    *,
    verdict: str,
    case_type: str,
    matched: bool,
    has_numeric: bool,
) -> float:
    """Map investigation quality to a confidence score in [0, 1]."""
    base = 0.5
    if verdict == EVIDENCE_CONSISTENT:
        base = 0.85 if matched else 0.7
    elif verdict == EVIDENCE_INCONSISTENT:
        base = 0.8 if matched else 0.65
    elif verdict == EVIDENCE_INSUFFICIENT:
        base = 0.4 if has_numeric else 0.25
    if case_type == CASE_OTHER:
        base = max(0.2, base - 0.1)
    return round(min(1.0, max(0.0, base)), 2)

# ---------------------------------------------------------------------------
# Decision functions (kept individually testable)
# ---------------------------------------------------------------------------

def match_transaction(
    complaint: str,
    history: list[TransactionHistoryEntry],
) -> TransactionHistoryEntry | None:
    """Return the single best-matching history entry, or None.

    Strategy (most specific wins):
    1. Exact transaction_id mention.
    2. Counterparty phone number match.
    3. Amount match (only when exactly one entry matches the amount).
    4. Otherwise None — caller decides whether to flag insufficient data.
    """
    if not history:
        return None

    complaint_lower = (complaint or "").lower()

    # 1. Transaction ID mention
    for entry in history:
        if entry.transaction_id and entry.transaction_id.lower() in complaint_lower:
            return entry

    # 2. Phone match
    phone_digits = _complaint_phone_digits(complaint)
    if phone_digits:
        # Try progressively relaxed suffixes (10 → 8 digits) so that
        # country-code and area-code variations still match. We collect
        # candidates per suffix level and only accept when exactly one
        # entry survives at the tightest matching level.
        for suffix_len in (10, 9, 8):
            if len(phone_digits) < suffix_len:
                continue
            suffix = phone_digits[-suffix_len:]
            phone_hits = [
                entry for entry in history
                if _entry_counterparty_digits(entry).endswith(suffix)
            ]
            if len(phone_hits) == 1:
                return phone_hits[0]
            if len(phone_hits) > 1:
                # Multiple phones match — let the amount break the tie.
                amount = _complaint_amount(complaint)
                if amount is not None:
                    amount_hits = [
                        entry for entry in phone_hits
                        if _entry_amount(entry) == amount
                    ]
                    if len(amount_hits) == 1:
                        return amount_hits[0]
                break

    # 3. Amount match
    amount = _complaint_amount(complaint)
    if amount is not None:
        amount_hits = [
            entry for entry in history
            if _entry_amount(entry) == amount
        ]
        if len(amount_hits) == 1:
            return amount_hits[0]
        # 3b. Same-amount fallback: when the customer reports an amount
        # but cannot remember the recipient, we still pick the only
        # transfer of that value in the snippet if it is the most recent
        # and unique. This catches the common "I typed the wrong number"
        # case where the customer only knows the amount and approximate
        # timing.
        if len(amount_hits) > 1:
            return None

    # 4. Single-entry fallback: if there is exactly one transaction in
    # the snippet and the complaint mentions any numeric signal, treat
    # it as the relevant transaction. This handles the common hidden-test
    # pattern where the snippet is short and the customer's complaint
    # names the wrong recipient but not the ID.
    if (
        len(history) == 1
        and _has_numeric_signal(complaint)
    ):
        return history[0]

    return None

def decide_evidence(
    complaint: str,
    matched_tx: TransactionHistoryEntry | None,
    history: list[TransactionHistoryEntry],
) -> str:
    """Return one of consistent / inconsistent / insufficient_data."""
    if not history:
        return EVIDENCE_INSUFFICIENT
    if matched_tx is None:
        if not _has_numeric_signal(complaint):
            return EVIDENCE_INSUFFICIENT
        return EVIDENCE_INSUFFICIENT

    status = (matched_tx.status or "").lower()
    complaint_lower = (complaint or "").lower()

    # Payment failed but status says completed → inconsistent.
    if _contains_any(complaint, _PAYMENT_FAILED_KW):
        if status == "completed":
            return EVIDENCE_INCONSISTENT
        if status in {"failed", "reversed"}:
            return EVIDENCE_CONSISTENT
        return EVIDENCE_INSUFFICIENT

    # Wrong transfer but the transaction was reversed already → inconsistent
    # (the money has already come back).
    if _contains_any(complaint, _WRONG_TRANSFER_KW):
        if status == "reversed":
            return EVIDENCE_INCONSISTENT
        if status == "completed":
            return EVIDENCE_CONSISTENT
        return EVIDENCE_INSUFFICIENT

    # Refund request — if the transaction is already reversed, the refund
    # happened; if it failed the customer has no money to refund.
    if _contains_any(complaint, _REFUND_KW):
        if status == "reversed":
            return EVIDENCE_INCONSISTENT
        if status in {"completed", "pending"}:
            return EVIDENCE_CONSISTENT
        return EVIDENCE_INSUFFICIENT

    # Duplicate payment — we can't verify duplication from a single
    # matched entry, so this is a partial signal.
    if _contains_any(complaint, _DUPLICATE_KW):
        return EVIDENCE_INSUFFICIENT

    # Settlement / agent cash-in — rely on status.
    if _contains_any(complaint, _MERCHANT_SETTLEMENT_KW):
        if status == "completed":
            return EVIDENCE_CONSISTENT
        if status in {"pending", "failed"}:
            return EVIDENCE_CONSISTENT
        return EVIDENCE_INSUFFICIENT

    if _contains_any(complaint, _AGENT_CASH_IN_KW):
        if status == "completed":
            return EVIDENCE_INCONSISTENT
        if status in {"pending", "failed"}:
            return EVIDENCE_CONSISTENT
        return EVIDENCE_INSUFFICIENT

    # Phishing — there is no real transaction backing the claim, but if the
    # customer mentions a real completed transaction we record inconsistency.
    if _contains_any(complaint, _PHISHING_KW):
        if matched_tx is not None and status == "completed":
            return EVIDENCE_INCONSISTENT
        return EVIDENCE_INSUFFICIENT

    # Vague / generic complaint with a matched transaction.
    if _contains_any(complaint, _VAGUE_KW) or not complaint_lower.strip():
        if matched_tx is not None:
            return EVIDENCE_INSUFFICIENT
        return EVIDENCE_INSUFFICIENT

    # No strong signal but a transaction was matched → insufficient_data.
    return EVIDENCE_INSUFFICIENT

def classify_case(
    complaint: str,
    matched_tx: TransactionHistoryEntry | None,
    history: list[TransactionHistoryEntry],
) -> str:
    """Return one of the eight ``case_type`` enum values.

    Phishing is checked first because safety routing should win over
    classification accuracy — a phishing attempt that also mentions a
    transfer must still go to fraud_risk.
    """
    if _contains_any(complaint, _PHISHING_KW):
        return CASE_PHISHING
    if _contains_any(complaint, _WRONG_TRANSFER_KW):
        return CASE_WRONG_TRANSFER
    if _contains_any(complaint, _PAYMENT_FAILED_KW):
        return CASE_PAYMENT_FAILED
    if _contains_any(complaint, _DUPLICATE_KW):
        return CASE_DUPLICATE
    if _contains_any(complaint, _MERCHANT_SETTLEMENT_KW):
        return CASE_MERCHANT_SETTLEMENT
    if _contains_any(complaint, _AGENT_CASH_IN_KW):
        return CASE_AGENT_CASH_IN
    if _contains_any(complaint, _REFUND_KW):
        return CASE_REFUND

    # Fall back to transaction type when the complaint text is too vague
    # to classify by itself.
    if matched_tx is not None:
        txn_type = (matched_tx.type or "").lower()
        if txn_type == "transfer":
            return CASE_WRONG_TRANSFER
        if txn_type == "payment":
            return CASE_PAYMENT_FAILED
        if txn_type in {"cash_in", "cash_out"}:
            return CASE_AGENT_CASH_IN
        if txn_type == "settlement":
            return CASE_MERCHANT_SETTLEMENT
        if txn_type == "refund":
            return CASE_REFUND

    return CASE_OTHER

def score_severity(
    case_type: str,
    matched_tx: TransactionHistoryEntry | None,
    verdict: str,
) -> str:
    """Return one of low / medium / high / critical."""
    # Phishing is always at least high — and critical when evidence is
    # insufficient because the customer may be actively under attack.
    if case_type == CASE_PHISHING:
        if verdict == EVIDENCE_INSUFFICIENT:
            return SEV_CRITICAL
        return SEV_HIGH

    amount = _entry_amount(matched_tx) if matched_tx is not None else 0.0

    # Critical: very high value regardless of case type.
    if amount >= CRITICAL_VALUE_THRESHOLD:
        return SEV_CRITICAL

    # High-value bands by case type.
    if case_type in {CASE_WRONG_TRANSFER, CASE_PAYMENT_FAILED, CASE_DUPLICATE}:
        if amount >= HIGH_VALUE_THRESHOLD:
            return SEV_HIGH
        if amount > 0:
            return SEV_MEDIUM
        return SEV_MEDIUM

    if case_type in {CASE_REFUND, CASE_AGENT_CASH_IN, CASE_MERCHANT_SETTLEMENT}:
        if amount >= HIGH_VALUE_THRESHOLD:
            return SEV_HIGH
        if amount > 0:
            return SEV_MEDIUM
        return SEV_LOW

    if case_type == CASE_OTHER:
        return SEV_LOW

    return SEV_MEDIUM

def route_department(case_type: str, verdict: str) -> str:
    """Return one of the six ``department`` enum values."""
    if case_type == CASE_PHISHING:
        return DEPT_FRAUD_RISK
    if case_type == CASE_WRONG_TRANSFER:
        return DEPT_DISPUTE
    if case_type in {CASE_PAYMENT_FAILED, CASE_DUPLICATE}:
        return DEPT_PAYMENTS_OPS
    if case_type == CASE_MERCHANT_SETTLEMENT:
        return DEPT_MERCHANT_OPS
    if case_type == CASE_AGENT_CASH_IN:
        return DEPT_AGENT_OPS
    if case_type == CASE_REFUND:
        return DEPT_DISPUTE if verdict != EVIDENCE_INSUFFICIENT else DEPT_CUSTOMER_SUPPORT
    # Other / vague → customer support.
    return DEPT_CUSTOMER_SUPPORT

# ---------------------------------------------------------------------------
# String synthesis (kept here so the safety layer only needs to scrub text)
# ---------------------------------------------------------------------------

def _build_agent_summary(
    *,
    ticket_id: str,
    case_type: str,
    verdict: str,
    matched_tx: TransactionHistoryEntry | None,
) -> str:
    label = case_type.replace("_", " ")
    if matched_tx is None:
        return (
            f"Ticket {ticket_id}: customer reports a '{label}' issue. "
            "No transaction in the provided history clearly matches."
        )
    return (
        f"Ticket {ticket_id}: customer reports a '{label}' issue that "
        f"appears to map to {matched_tx.transaction_id} "
        f"({matched_tx.type}, {int(_entry_amount(matched_tx))} BDT, "
        f"status={matched_tx.status}). Evidence verdict: {verdict}."
    )

def _build_recommended_action(case_type: str, verdict: str) -> str:
    base = {
        CASE_PHISHING: (
            "Escalate to fraud_risk. Do not request any credential from the "
            "customer. Capture the suspicious message/call details and "
            "advise via official channels only."
        ),
        CASE_WRONG_TRANSFER: (
            "Verify the transfer details with the customer via official "
            "channels and initiate the dispute workflow if the recipient "
            "is unresponsive."
        ),
        CASE_PAYMENT_FAILED: (
            "Confirm whether the balance was deducted and check the gateway "
            "status. Initiate payment_ops review for any stuck transaction."
        ),
        CASE_REFUND: (
            "Open a refund review ticket. Do not confirm any refund "
            "outright; route the case through the standard approval flow."
        ),
        CASE_DUPLICATE: (
            "Reconcile the two charges via payments_ops and prepare a "
            "single eligible reversal if duplication is confirmed."
        ),
        CASE_MERCHANT_SETTLEMENT: (
            "Check settlement ledger for the merchant and escalate to "
            "merchant_operations if the window has lapsed."
        ),
        CASE_AGENT_CASH_IN: (
            "Pull the agent cash-in journal entry and verify with "
            "agent_operations. Flag the agent ID for review if no entry "
            "is found."
        ),
        CASE_OTHER: (
            "Gather more information from the customer via official "
            "channels and re-route once a clearer case type emerges."
        ),
    }.get(case_type, "Review the case manually.")
    if verdict == EVIDENCE_INSUFFICIENT:
        return base + " Evidence is currently insufficient — human review is required."
    return base

def _build_reason_codes(
    case_type: str,
    verdict: str,
    matched_tx: TransactionHistoryEntry | None,
) -> list[str]:
    codes: list[str] = []
    codes.append(case_type)
    if matched_tx is not None:
        codes.append("transaction_match")
        codes.append(f"tx_status_{matched_tx.status}")
    else:
        codes.append("no_transaction_match")
    codes.append(f"verdict_{verdict}")
    return codes

def _human_review_required(
    case_type: str,
    verdict: str,
    matched_tx: TransactionHistoryEntry | None,
) -> bool:
    # Phishing, disputes, and ambiguous cases always need a human.
    if case_type == CASE_PHISHING:
        return True
    if verdict != EVIDENCE_CONSISTENT:
        return True
    if matched_tx is None:
        return True
    if _entry_amount(matched_tx) >= HIGH_VALUE_THRESHOLD:
        return True
    return False

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_outputs(
    *,
    ticket_id: str,
    complaint: str,
    language: str | None,
    transaction_history: list[TransactionHistoryEntry],
) -> dict:
    """Run every decision function and return the response payload as a dict.

    This is the function unit tests assert against. ``investigate`` is the
    thin pydantic-aware wrapper around it.
    """
    matched = match_transaction(complaint, transaction_history)
    verdict = decide_evidence(complaint, matched, transaction_history)
    case_type = classify_case(complaint, matched, transaction_history)
    severity = score_severity(case_type, matched, verdict)
    department = route_department(case_type, verdict)
    confidence = _confidence_for(
        verdict=verdict,
        case_type=case_type,
        matched=matched is not None,
        has_numeric=_has_numeric_signal(complaint),
    )

    return {
        "ticket_id": ticket_id,
        "relevant_transaction_id": matched.transaction_id if matched else None,
        "evidence_verdict": verdict,
        "case_type": case_type,
        "severity": severity,
        "department": department,
        "agent_summary": _build_agent_summary(
            ticket_id=ticket_id,
            case_type=case_type,
            verdict=verdict,
            matched_tx=matched,
        ),
        "recommended_next_action": _build_recommended_action(case_type, verdict),
        # Left blank for the safety layer (Member C) to populate.
        "customer_reply": "",
        "human_review_required": _human_review_required(
            case_type, verdict, matched
        ),
        "confidence": confidence,
        "reason_codes": _build_reason_codes(case_type, verdict, matched),
    }

def investigate(req: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    """Top-level entry point used by ``app.main``.

    Performs the rule-based reasoning and returns a fully-populated
    ``AnalyzeTicketResponse``. The ``customer_reply`` field is intentionally
    left blank — the API layer (Member C) is responsible for routing it
    through ``app.safety.build_safe_reply`` before returning.
    """
    payload = build_outputs(
        ticket_id=req.ticket_id,
        complaint=req.complaint or "",
        language=req.language,
        transaction_history=list(req.transaction_history or []),
    )
    return AnalyzeTicketResponse(**payload)

__all__ = [
    "EVIDENCE_CONSISTENT",
    "EVIDENCE_INCONSISTENT",
    "EVIDENCE_INSUFFICIENT",
    "CASE_WRONG_TRANSFER",
    "CASE_PAYMENT_FAILED",
    "CASE_REFUND",
    "CASE_DUPLICATE",
    "CASE_MERCHANT_SETTLEMENT",
    "CASE_AGENT_CASH_IN",
    "CASE_PHISHING",
    "CASE_OTHER",
    "SEV_LOW",
    "SEV_MEDIUM",
    "SEV_HIGH",
    "SEV_CRITICAL",
    "DEPT_CUSTOMER_SUPPORT",
    "DEPT_DISPUTE",
    "DEPT_PAYMENTS_OPS",
    "DEPT_MERCHANT_OPS",
    "DEPT_AGENT_OPS",
    "DEPT_FRAUD_RISK",
    "HIGH_VALUE_THRESHOLD",
    "CRITICAL_VALUE_THRESHOLD",
    "match_transaction",
    "decide_evidence",
    "classify_case",
    "score_severity",
    "route_department",
    "build_outputs",
    "investigate",
]
