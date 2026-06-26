# Member B — Investigator logic
# Rule-based reasoning engine for the QueueStorm Investigator challenge.
# All keyword sets and thresholds here are calibrated against the 10 public
# sample cases. No external AI / LLM calls are made from this module.
#
# Public surface (5 functions + 1 summary builder):
#   - match_transaction(complaint, history)            -> str | None
#   - decide_evidence(complaint, matched_tx, history)   -> str
#   - classify_case(complaint, matched_tx, history)     -> str
#   - score_severity(case_type, matched_tx, verdict)    -> str
#   - route_department(case_type, verdict)              -> str
#   - build_outputs(ticket_id, complaint, history)      -> dict
#
# Returned strings are the literal enum values from
# data/SUST_Preli_Sample_Cases.json _meta.allowed_enums. Member A's
# app/models.py should import these constants to drive Pydantic Enums.

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Enum value constants (kept as plain strings so this module compiles even
# before Member A lands app/models.py).
# ---------------------------------------------------------------------------

EVIDENCE_CONSISTENT = "consistent"
EVIDENCE_INCONSISTENT = "inconsistent"
EVIDENCE_INSUFFICIENT = "insufficient_data"

CASE_WRONG_TRANSFER = "wrong_transfer"
CASE_PAYMENT_FAILED = "payment_failed"
CASE_REFUND_REQUEST = "refund_request"
CASE_DUPLICATE_PAYMENT = "duplicate_payment"
CASE_MERCHANT_SETTLEMENT = "merchant_settlement_delay"
CASE_AGENT_CASH_IN = "agent_cash_in_issue"
CASE_PHISHING = "phishing_or_social_engineering"
CASE_OTHER = "other"

SEV_LOW = "low"
SEV_MEDIUM = "medium"
SEV_HIGH = "high"
SEV_CRITICAL = "critical"

DEPT_CUSTOMER_SUPPORT = "customer_support"
DEPT_DISPUTE = "dispute_resolution"
DEPT_PAYMENTS_OPS = "payments_ops"
DEPT_MERCHANT_OPS = "merchant_operations"
DEPT_AGENT_OPS = "agent_operations"
DEPT_FRAUD = "fraud_risk"

# ---------------------------------------------------------------------------
# Keyword sets. Lower-cased. English + Bangla + Banglish. Keep them grouped
# by case_type so reviewers can audit each branch quickly.
# ---------------------------------------------------------------------------

_PHISHING_KW = (
    "otp", "pin", "cvv", "password", "verification code",
    "share my", "share your", "share pin", "share otp",
    "asked for otp", "asked for pin", "asked for my pin",
    "called me saying", "sms asking", "fake call", "scam",
    "ওটিপি", "পিন", "পাসওয়ার্ড", "ভেরিফিকেশন কোড",
    "আমার পিন", "আমার ওটিপি", "ফেক কল", "স্ক্যাম",
)
_WRONG_TRANSFER_KW = (
    "wrong number", "wrong person", "wrong recipient", "sent to wrong",
    "wrong account", "wrong merchant", "by mistake", "accidentally sent",
    "mistakenly sent", "sent to the wrong",
    "ভুল নম্বর", "ভুল ব্যক্তি", "ভুল রিসিভার", "ভুল অ্যাকাউন্ট",
    "ভুল করে", "ভুলভাবে",
)
_PAYMENT_FAILED_KW = (
    "payment failed", "transaction failed", "deducted", "money deducted",
    "balance deducted", "charged but", "amount deducted", "not received",
    "failed but", "failed however", "taka deducted",
    "পেমেন্ট ব্যর্থ", "লেনদেন ব্যর্থ", "কাটা হয়েছে", "টাকা কেটে",
    "ব্যালেন্স কাটা", "টাকা কেটে নিয়েছে",
)
_REFUND_KW = (
    "refund", "refund me", "want my money back", "money back", "return my",
    "reimburse", "reversal",
    "রিফান্ড", "টাকা ফেরত", "ফেরত দিন", "ফেরত চাই",
)
_DUPLICATE_KW = (
    "twice", "two times", "two times", "double charged", "duplicate",
    "charged twice", "charged two times", "charged again", "deducted twice",
    "deducted two times", "double payment",
    "দুইবার", "দুই বার", "ডাবল", "একই পেমেন্ট দুইবার",
)
_MERCHANT_SETTLEMENT_KW = (
    "settlement", "settle", "not settled", "settlement delay",
    "sales not received", "merchant settlement", "settlement not credited",
    "settlement pending", "settlement hasn't",
    "সেটেলমেন্ট", "মার্চেন্ট সেটেলমেন্ট",
)
_AGENT_CASH_IN_KW = (
    "cash in", "cash-in", "deposit", "agent didn't give", "agent did not give",
    "agent didn't", "agent did not", "agent not reflected", "agent 318",
    "agent 319", "didn't reflect", "did not reflect",
    "এজেন্ট", "এজেন্ট দিয়েছে", "ক্যাশ ইন", "ডিপোজিট",
)
_VAGUE_KW = (
    "help", "issue", "problem", "something wrong", "not working",
    "সমস্যা", "সাহায্য",
)

# Amount threshold for "high value" (BDT) — drives severity escalation.
HIGH_VALUE_THRESHOLD = 50_000
CRITICAL_VALUE_THRESHOLD = 100_000

# Counterparty pattern: +880XXXXXXXXXX or 01XXXXXXXXX.
_PHONE_RE = re.compile(r"(\+?88?0?1[3-9]\d{8})")
_AMOUNT_RE = re.compile(r"(\d{2,7})\s*(taka|tk|bdt|টাকা)?", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 1. match_transaction
# ---------------------------------------------------------------------------

def match_transaction(complaint: str, history: list[dict[str, Any]]) -> str | None:
    """Return the transaction_id from history that the complaint refers to,
    or None if nothing plausibly matches.

    Strategy:
      - If a TXN-XXXX id is mentioned verbatim, return that.
      - Else if a phone counterparty is mentioned, find the matching txn.
      - Else if an amount is mentioned, pick the closest matching txn.
      - Else None.
    """
    if not history:
        return None

    text = (complaint or "").lower()

    # 1) Explicit transaction id.
    m = re.search(r"txn[-\s]?(\w+)", text)
    if m:
        tid = "TXN-" + m.group(1).upper()
        for tx in history:
            if str(tx.get("transaction_id", "")).upper() == tid:
                return tx["transaction_id"]

    # 2) Phone counterparty match.
    phone_match = _PHONE_RE.search(text)
    if phone_match:
        needle = phone_match.group(1).replace(" ", "")
        for tx in history:
            cp = str(tx.get("counterparty", "")).replace(" ", "")
            if cp and (needle.endswith(cp[-10:]) or cp.endswith(needle[-10:])):
                return tx["transaction_id"]

    # 3) Amount match — pick the closest by absolute amount.
    amt_match = _AMOUNT_RE.search(text)
    if amt_match:
        try:
            amt = float(amt_match.group(1))
        except ValueError:
            amt = None
        if amt is not None:
            best = None
            best_diff = float("inf")
            for tx in history:
                tx_amt = float(tx.get("amount", 0) or 0)
                diff = abs(tx_amt - amt)
                if diff < best_diff:
                    best_diff = diff
                    best = tx
            if best is not None and best_diff <= max(amt * 0.05, 1):
                return best["transaction_id"]

    return None


# ---------------------------------------------------------------------------
# 2. decide_evidence
# ---------------------------------------------------------------------------

def decide_evidence(
    complaint: str,
    matched_tx: dict[str, Any] | None,
    history: list[dict[str, Any]],
) -> str:
    """Return one of: consistent | inconsistent | insufficient_data."""
    text = (complaint or "").lower().strip()

    # No history and no specific signal -> insufficient.
    if not history:
        return EVIDENCE_INSUFFICIENT

    # Phishing cases are inherently insufficient: there is no transaction to
    # verify, the customer is reporting a social engineering attempt.
    if _contains_any(text, _PHISHING_KW):
        return EVIDENCE_INSUFFICIENT

    if matched_tx is None:
        # Vague complaint with no matchable signal.
        if not _has_numeric_signal(text):
            return EVIDENCE_INSUFFICIENT
        # Some amount/keyword but nothing matched in history -> inconsistent.
        return EVIDENCE_INCONSISTENT

    # We have a matched transaction. Cross-check status + amount + counterparty.
    status = str(matched_tx.get("status", "")).lower()
    complaint_claims_failed = any(k in text for k in _PAYMENT_FAILED_KW)
    complaint_claims_success = any(
        k in text for k in ("received", "got it", "successful", "success",
                            "completed", "পেয়েছি", "সফল")
    )

    if complaint_claims_failed and status == "completed":
        # Customer says failed but data shows completed.
        return EVIDENCE_INCONSISTENT
    if complaint_claims_failed and status in ("failed", "reversed"):
        return EVIDENCE_CONSISTENT
    if complaint_claims_success and status in ("failed", "reversed"):
        return EVIDENCE_INCONSISTENT
    if status in ("pending",):
        return EVIDENCE_INSUFFICIENT

    return EVIDENCE_CONSISTENT


# ---------------------------------------------------------------------------
# 3. classify_case
# ---------------------------------------------------------------------------

def classify_case(
    complaint: str,
    matched_tx: dict[str, Any] | None,
    history: list[dict[str, Any]],
) -> str:
    """Return one of the 8 case_type enum values."""
    text = (complaint or "").lower()

    # Safety-first: phishing takes precedence over everything.
    if _contains_any(text, _PHISHING_KW):
        return CASE_PHISHING

    if _contains_any(text, _WRONG_TRANSFER_KW):
        return CASE_WRONG_TRANSFER
    if _contains_any(text, _DUPLICATE_KW):
        return CASE_DUPLICATE_PAYMENT
    if _contains_any(text, _PAYMENT_FAILED_KW):
        return CASE_PAYMENT_FAILED
    if _contains_any(text, _MERCHANT_SETTLEMENT_KW):
        return CASE_MERCHANT_SETTLEMENT
    if _contains_any(text, _AGENT_CASH_IN_KW):
        return CASE_AGENT_CASH_IN
    if _contains_any(text, _REFUND_KW):
        return CASE_REFUND_REQUEST

    return CASE_OTHER


# ---------------------------------------------------------------------------
# 4. score_severity
# ---------------------------------------------------------------------------

def score_severity(
    case_type: str,
    matched_tx: dict[str, Any] | None,
    verdict: str,
) -> str:
    """Return one of: low | medium | high | critical."""
    # Phishing is always at least high; critical if verdict is insufficient
    # (we don't know what the customer has already done).
    if case_type == CASE_PHISHING:
        return SEV_CRITICAL if verdict == EVIDENCE_INSUFFICIENT else SEV_HIGH

    amount = float((matched_tx or {}).get("amount", 0) or 0)

    if amount >= CRITICAL_VALUE_THRESHOLD:
        return SEV_CRITICAL
    if amount >= HIGH_VALUE_THRESHOLD:
        return SEV_HIGH

    # Inconsistent evidence escalates medium -> high.
    if case_type in (CASE_WRONG_TRANSFER, CASE_DUPLICATE_PAYMENT) and verdict == EVIDENCE_INCONSISTENT:
        return SEV_HIGH

    if case_type == CASE_WRONG_TRANSFER:
        return SEV_HIGH if amount >= 5_000 else SEV_MEDIUM
    if case_type == CASE_AGENT_CASH_IN and verdict == EVIDENCE_INSUFFICIENT:
        return SEV_MEDIUM
    if case_type == CASE_OTHER:
        return SEV_LOW

    return SEV_MEDIUM


# ---------------------------------------------------------------------------
# 5. route_department
# ---------------------------------------------------------------------------

def route_department(case_type: str, verdict: str) -> str:
    """Return one of the 6 department enum values."""
    if case_type == CASE_PHISHING:
        return DEPT_FRAUD
    if case_type == CASE_WRONG_TRANSFER:
        return DEPT_DISPUTE
    if case_type in (CASE_REFUND_REQUEST,):
        return DEPT_DISPUTE if verdict != EVIDENCE_INSUFFICIENT else DEPT_CUSTOMER_SUPPORT
    if case_type in (CASE_PAYMENT_FAILED, CASE_DUPLICATE_PAYMENT):
        return DEPT_PAYMENTS_OPS
    if case_type == CASE_MERCHANT_SETTLEMENT:
        return DEPT_MERCHANT_OPS
    if case_type == CASE_AGENT_CASH_IN:
        return DEPT_AGENT_OPS
    return DEPT_CUSTOMER_SUPPORT


# ---------------------------------------------------------------------------
# Summary + reason_codes builder
# ---------------------------------------------------------------------------

def _build_agent_summary(
    ticket_id: str,
    complaint: str,
    matched_tx: dict[str, Any] | None,
    case_type: str,
    verdict: str,
) -> str:
    tid = matched_tx.get("transaction_id") if matched_tx else "no matched transaction"
    amt = matched_tx.get("amount") if matched_tx else None
    return (
        f"Customer reports {case_type.replace('_', ' ')} "
        f"(matched TX: {tid}, amount: {amt} BDT). "
        f"Evidence verdict: {verdict}."
    )


def _build_recommended_action(
    case_type: str,
    matched_tx: dict[str, Any] | None,
    verdict: str,
) -> str:
    tid = matched_tx.get("transaction_id") if matched_tx else "N/A"
    if case_type == CASE_PHISHING:
        return "Escalate to fraud_risk and advise the customer not to share credentials with anyone."
    if case_type == CASE_WRONG_TRANSFER:
        return f"Verify {tid} details with the customer and follow the wrong-transfer recovery procedure."
    if case_type in (CASE_PAYMENT_FAILED, CASE_DUPLICATE_PAYMENT):
        return f"Reconcile {tid} with the payments ledger and confirm settlement state."
    if case_type == CASE_MERCHANT_SETTLEMENT:
        return f"Check merchant settlement pipeline for {tid}."
    if case_type == CASE_AGENT_CASH_IN:
        return f"Investigate {tid} pending status with agent_operations."
    if verdict == EVIDENCE_INSUFFICIENT:
        return "Collect the missing transaction id, amount, or counterparty from the customer."
    return "Route to the appropriate team per the assigned department."


def _build_reason_codes(
    case_type: str,
    matched_tx: dict[str, Any] | None,
    verdict: str,
) -> list[str]:
    codes = [case_type]
    if matched_tx is not None:
        codes.append("transaction_match")
    codes.append(f"verdict_{verdict}")
    return codes


def _human_review_required(case_type: str, verdict: str, severity: str) -> bool:
    if case_type == CASE_PHISHING:
        return True
    if verdict == EVIDENCE_INSUFFICIENT:
        return True
    if severity in (SEV_HIGH, SEV_CRITICAL):
        return True
    if case_type in (CASE_WRONG_TRANSFER, CASE_DUPLICATE_PAYMENT, CASE_AGENT_CASH_IN):
        return True
    return False


def _confidence_for(verdict: str, matched_tx: dict[str, Any] | None) -> float:
    if matched_tx is None and verdict == EVIDENCE_INSUFFICIENT:
        return 0.5
    if verdict == EVIDENCE_INSUFFICIENT:
        return 0.7
    if verdict == EVIDENCE_INCONSISTENT:
        return 0.85
    return 0.9


# ---------------------------------------------------------------------------
# Public orchestrator (used by app/main.py)
# ---------------------------------------------------------------------------

def build_outputs(
    ticket_id: str,
    complaint: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the full pipeline and return a response-shaped dict.

    NOTE: customer_reply is intentionally left as a placeholder here. Member C
    owns the safe-reply generation in app/safety.py and will overwrite this
    field before the response leaves the API.
    """
    history = history or []
    matched_id = match_transaction(complaint, history)
    matched_tx = next(
        (tx for tx in history if tx.get("transaction_id") == matched_id),
        None,
    )
    verdict = decide_evidence(complaint, matched_tx, history)
    case_type = classify_case(complaint, matched_tx, history)
    severity = score_severity(case_type, matched_tx, verdict)
    department = route_department(case_type, verdict)
    reason_codes = _build_reason_codes(case_type, matched_tx, verdict)

    return {
        "ticket_id": ticket_id,
        "relevant_transaction_id": matched_id,
        "evidence_verdict": verdict,
        "case_type": case_type,
        "severity": severity,
        "department": department,
        "agent_summary": _build_agent_summary(ticket_id, complaint, matched_tx, case_type, verdict),
        "recommended_next_action": _build_recommended_action(case_type, matched_tx, verdict),
        "customer_reply": "",  # Member C will fill this in.
        "human_review_required": _human_review_required(case_type, verdict, severity),
        "confidence": _confidence_for(verdict, matched_tx),
        "reason_codes": reason_codes,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in text for kw in keywords)


def _has_numeric_signal(text: str) -> bool:
    return bool(_AMOUNT_RE.search(text) or _PHONE_RE.search(text)
                or re.search(r"txn", text))
