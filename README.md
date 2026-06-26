# QueueStorm-Investigator-StackFellas

> **bKash SUST CSE Carnival 2026 — Codex Community Hackathon**
> *AI / API SupportOps Challenge for Digital Finance*

Backend copilot for support agents handling campaign-driven complaint
volume. Given one customer complaint (English / Bangla / Banglish) and a
short snippet of recent transactions, the service classifies the case,
reasons about whether the ledger evidence supports the complaint, routes
it to the right department, drafts a safe customer reply, and flags
whether a human must approve any next step.

Built for the Online Preliminary Round — 4.5 h, rule-based, no LLM.

---

## What it does

`POST /analyze-ticket` accepts the request schema defined in
**Section 5** of the problem statement (see `problem_statement.md`) and
returns the response schema from **Section 6** — same enums, same
field names, same shape that the judge harness will validate.

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending 5000 BDT via TXN-9101...",
  "recommended_next_action": "Verify TXN-9101 details with the customer...",
  "customer_reply": "We have noted your concern about transaction TXN-9101...",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["wrong_transfer", "transaction_match"]
}
```

`GET /health` returns `{"status": "ok", ...}` within 60 s of service
start so the harness can confirm readiness.

---

## Tech stack

| Layer        | Choice                                | Why                                          |
| ------------ | ------------------------------------- | -------------------------------------------- |
| Runtime      | Python 3.11                           | Stable, fast cold start on Render free tier. |
| Web          | FastAPI 0.115 + Uvicorn 0.30         | Async, OpenAPI out of the box (`/docs`).     |
| Validation   | Pydantic v2 2.9                       | Type-safe request / response models.         |
| Logic        | Pure rule-based investigator          | Deterministic, no API cost, no network.     |
| Tests        | pytest 8.3 + httpx TestClient          | 43 unit / integration tests.                 |
| Container    | `python:3.11-slim` Dockerfile         | Image ~180 MB, well under 5 GB budget.       |

**No LLM is used.** The investigator is a deterministic rule engine
over keyword sets, regex, and explicit decision trees. See
[AI approach](#ai-approach) and [MODELS](#models) below.

---

## Quick start (local)

```powershell
cd c:\Users\Tahmeed\susthackathonproject\QueueStorm-Investigator-StackFellas

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
copy .env.example .env

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints

| Method | Path              | Required? | Purpose                                                |
| ------ | ----------------- | --------- | ------------------------------------------------------ |
| `GET`  | `/health`         | yes       | Liveness probe. `{"status":"ok","service":"…"}`.      |
| `POST` | `/analyze-ticket` | yes       | Run the investigator on one ticket. JSON body in/out.  |
| `GET`  | `/docs`           | no        | Interactive OpenAPI / Swagger UI (FastAPI built-in).   |
| `GET`  | `/openapi.json`   | no        | Raw OpenAPI 3.1 schema for the harness / Postman.      |

### HTTP response codes

| Code | When                                                  |
| ---- | ----------------------------------------------------- |
| 200  | Request processed; body matches Section 6 schema.     |
| 422  | Request body fails Pydantic validation (missing / wrong-type fields). |
| 500  | Unexpected internal error (logged with stack trace).  |

---

## AI approach

A **deterministic, rule-based investigator** — no LLM, no vector DB, no
external call. Six stages run per request, in order, each producing a
field on the Section 6 response:

1. **Parse & normalize.** Pydantic validates the request, lowercases
   text, detects language (`en` / `bn` / `mixed`), strips diacritics
   for Bangla matching.
2. **Keyword + regex classify.** Per `case_type`, score keyword sets
   (English + transliterated Bangla + Banglish). Tie-breaker:
   `evidence_verdict == "inconsistent"` favors `wrong_transfer`;
   `metadata` and `transaction_history` boost their case type.
3. **Evidence match.** If `transaction_history` is non-empty, pick the
   best candidate by: status (`failed` > `reversed` > `pending` >
   `completed`), recency, then amount proximity to any number in the
   complaint. Set `relevant_transaction_id` to the winner, or `null`
   if no candidate clears the threshold.
4. **Verdict.** Compare complaint claim vs ledger evidence:
   - claim + ledger agree → `consistent`
   - claim + ledger disagree → `inconsistent`
   - no usable history → `insufficient_data`
5. **Route & severity.** Map `case_type` to a `department` (see
   `app/safety.py` taxonomy). Severity scales with amount
   (≥ 10 000 BDT → `high`, ≥ 50 000 BDT → `critical`) and with
   `evidence_verdict == "inconsistent"`.
6. **Draft reply.** Compose `agent_summary`, `recommended_next_action`,
   and `customer_reply` from templated fragments. Every reply is
   post-processed by the **safety filter** below before it leaves the
   service.

**Why rule-based for the preliminary round?**

- **Latency.** Single-digit-ms p99 on free-tier CPU. No cold-start
  model load.
- **Cost.** Zero per-request spend. No token budget, no rate limits.
- **Determinism.** Same input → same output, every time. Judges can
  diff expected vs actual without flakiness.
- **No network.** Section 9.1 explicitly restricts the allowed
  external services; pulling in an LLM API would either be
  disallowed or another failure mode to debug in 4.5 h.
- **Auditable.** Every `reason_codes` entry maps to a literal code
  path in `app/investigator.py`.

The trade-off is recall on phrasings the keyword sets do not cover.
A post-round upgrade path is sketched under [MODELS](#models).

---

## Safety logic (Section 8)

`app/safety.py` enforces the four automatic-check rules from Section 8.
A violation subtracts points (and on critical rules, can disqualify).

| Rule (Section 8)                                          | Field checked                          | Penalty     | Enforcement                              |
| --------------------------------------------------------- | -------------------------------------- | ----------- | ---------------------------------------- |
| Never ask for PIN / OTP / password / full card number.    | `customer_reply`                       | −15         | Regex block-list + phrase rewrite.       |
| Never confirm a refund / reversal / unblock / recovery.   | `customer_reply`, `recommended_next_action` | −10     | Forced phrasing: *"any eligible amount will be returned through official channels"*. |
| Never direct the customer to a suspicious third party.    | `customer_reply`                       | −10         | Strip non-official URLs / phone numbers. |
| Never include internal codes, stack traces, or secrets.   | every string field                     | −5          | Redact env vars and exception messages.  |

`human_review_required` is set to `true` for: any dispute
(`wrong_transfer`, contested refund), any `phishing_or_social_engineering`
case, any transaction ≥ 10 000 BDT, any `inconsistent` evidence verdict,
and any ambiguity where a regex cannot disambiguate two case types.

---

## MODELS

No model is used. `app/investigator.py` is pure Python.

| Model           | Purpose                              | Cost / latency          |
| --------------- | ------------------------------------ | ----------------------- |
| *none*          | Classification, evidence match, reply drafting | Free / < 5 ms p99 |

**Why no model was picked:** the preliminary round optimizes for
deterministic correctness on a fixed taxonomy, not open-ended
generation. Adding an LLM would buy nothing the rule engine does
not already produce, and would add two new failure modes (latency +
API cost / outage) inside a 4.5 h window.

**If we had to add one:** a small instruction-tuned model served
locally (`llama-3.1-8b-instruct` INT4, ~4 GB RAM) for free-text
`customer_reply` drafting, with the rule engine still owning
classification, verdict, and safety. That keeps the safety-critical
fields in deterministic code and uses the model only where its
quality adds user-visible value.

---

## Project layout

```
QueueStorm-Investigator-StackFellas/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, /health and /analyze-ticket
│   ├── models.py          # Pydantic request / response models (Sec 5 + 6)
│   ├── investigator.py    # Rule-based pipeline (classify → match → verdict → route → draft)
│   └── safety.py          # Section 8 enforcement + taxonomy lookups
├── data/
│   ├── sample_input.json      # One full Section 5 request (SAMPLE-01)
│   └── sample_output.json     # Investigator's response for SAMPLE-01
├── tests/
│   ├── test_health.py
│   ├── test_analyze_ticket.py
│   ├── test_safety.py
│   └── test_taxonomy.py
├── problem_statement.md
├── SUST_Preli_Sample_Cases.json
├── Dockerfile             # python:3.11-slim, port 8000
├── render.yaml            # Render Blueprint (web service, free plan, /health)
├── requirements.txt
├── .env.example
├── RUNBOOK.md             # Local + Render deploy runbook
└── README.md
```

---

## Assumptions

- **Language detection** is heuristic (Unicode range + Bangla-script
  ratio). Mixed Banglish is treated as `mixed` and matched against
  both English and transliterated Bangla keyword sets.
- **Transaction matching** prefers `failed` and `reversed` status over
  `completed`, because those are the statuses customers usually
  complain about. Recency and amount proximity are tie-breakers.
- **Severity** is amount-driven (low < 1 000 BDT, medium < 10 000 BDT,
  high < 50 000 BDT, critical ≥ 50 000 BDT) plus a one-step bump on
  `inconsistent` evidence. The judge can override by setting
  `metadata.priority`.
- **Empty `transaction_history`** is valid (used for safety-only /
  phishing cases) and yields `evidence_verdict: "insufficient_data"`.
- **Department routing** follows Section 7.2; unknown / unconfident
  cases route to `customer_support`.

---

## Known limitations

- Keyword sets are hand-written for the public sample cases. A
  rephrased complaint that avoids every keyword falls back to
  `case_type: "other"` and `department: "customer_support"`.
- No persistence. Each request is processed in isolation; there is
  no in-memory or disk store of tickets.
- No auth, no rate limiting. Section 9.1 does not require it for the
  preliminary round; production would need both.
- `confidence` is a calibrated anchor per `case_type` + verdict
  combination, not a learned probability. See `app/investigator.py`
  `_confidence_for` for the lookup.
- `customer_reply` is templated. It will read robotic on a long,
  emotional complaint — that is the explicit trade-off for
  deterministic safety.

---

## Deliverables checklist (Section 11)

| Deliverable                                          | Where in this repo                                            |
| ---------------------------------------------------- | ------------------------------------------------------------- |
| Deployed AI / API service with `POST /analyze-ticket` | `app/main.py` + `Dockerfile` (Render URL after deploy)        |
| `GET /health`                                        | `app/main.py`                                                 |
| Live URL, Docker image, or code + runbook            | Render Blueprint (`render.yaml`) or `RUNBOOK.md` (local)      |
| Team Instructions Manual                             | `RUNBOOK.md`                                                  |
| Evaluation Rubric for Teams                          | See the hackathon pack; service code is the answer.           |
| Companion file `SUST_Preli_Sample_Cases.json`        | included at repo root (10 worked sample cases)                |

**Sample output** for `SAMPLE-01` is checked in at
`data/sample_output.json`.

---

## Example

A full Section 5 request → Section 6 response (SAMPLE-01):

```bash
curl -s -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @data/sample_input.json
```

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending 5000 BDT to +8801719876543 via TXN-9101 and suspects a wrong recipient. Ledger shows a completed transfer of 5000 BDT to the same counterparty at 2026-04-14T14:08:22Z, which is consistent with the complaint.",
  "recommended_next_action": "Verify the recipient number with the customer through the official app, then raise a dispute for TXN-9101 if the number is confirmed wrong. Any eligible amount will be returned through official channels after investigation.",
  "customer_reply": "Thank you for contacting support. We have noted your concern about transaction TXN-9101 for 5000 BDT. A support agent will verify the details and any eligible amount will be returned through official channels. Please do not share your PIN, OTP, or password with anyone.",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["wrong_transfer", "transaction_match", "completed_transfer"]
}
```

---

## Deploy on Render

The repo includes a Dockerfile and `render.yaml` Blueprint.

1. Push this branch to GitHub (already on `feat/investigator`).
2. In Render: **New → Blueprint → connect repo** → pick
   `fuad13579/QueueStorm-Investigator-StackFellas`.
3. Render reads `render.yaml` and provisions `queuestorm-investigator`
   from the `Dockerfile`, exposes port 8000, health-checks `/health`.
4. After deploy, your URL is `https://queuestorm-investigator.onrender.com`.

Or skip the Blueprint: **New → Web Service → Docker** → point at this
repo and Render uses `Dockerfile` directly.
