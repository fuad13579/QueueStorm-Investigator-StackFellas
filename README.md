# QueueStorm-Investigator-StackFellas

> bKash SUST CSE Carnival 2026 — Codex Community Hackathon
> Online Preliminary Round — QueueStorm Investigator

AI/API copilot for digital finance support agents. Receives a customer complaint
plus recent transaction history, returns a structured JSON classification with
evidence verdict, routing, severity, and a safe customer reply.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then:

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/analyze-ticket -H "Content-Type: application/json" -d @data/SUST_Preli_Sample_Cases.json
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Returns `{"status":"ok"}` |
| POST | `/analyze-ticket` | Analyzes one complaint + history |

See `RUNBOOK.md` for full deployment instructions.

## Tech Stack

- **Language:** Python 3.11
- **Framework:** FastAPI + Uvicorn
- **Validation:** Pydantic v2
- **AI approach:** Rule-based investigator (no external LLM required)

## Project Structure

```
app/
├── main.py          # FastAPI app + endpoints (Member A)
├── models.py        # Pydantic schemas (Member A)
├── investigator.py  # Evidence reasoning logic (Member B)
└── safety.py        # Safety guardrails + reply gen (Member C)

tests/
├── test_api.py          (Member A)
├── test_investigator.py (Member B)
└── test_safety.py       (Member C)

data/
├── SUST_Preli_Sample_Cases.json
└── sample_output.json
```

## MODELS

This build uses **no external AI model**. The investigator is a deterministic,
rule-based engine that combines:

- Regex/keyword matchers for transaction identification
- Decision matrices for evidence verdict
- Enum-based classification taxonomy
- Template-based reply generation

This was chosen because:

1. The problem statement explicitly states *"an LLM is not required to score well"*.
2. No LLM API credits are provided for the preliminary round.
3. Rule-based reasoning is faster, deterministic, and fully reproducible for the
   judge harness.
4. Lower deployment cost — fits in 2 vCPU / 4 GB RAM easily.

If your team has its own LLM access, see `.env.example` for optional
configuration.

## Safety Logic

All customer replies pass through `app/safety.py` before being returned. The
safety layer enforces four hard rules (Section 8 of the problem statement):

1. Never request PIN / OTP / password / full card number
2. Never confirm a refund, reversal, unblock, or recovery
3. Never direct customer to a suspicious third party
4. Strip prompt-injection attempts from complaint text before processing

## Limitations

- Keyword matchers cover the most common English and Bangla patterns. Heavy
  Banglish variations may be classified as `other` or `insufficient_data`.
- Severity scoring uses simple thresholds; large hidden cases with edge-case
  amounts may need post-hoc tuning.
- No persistence layer — the service is stateless.

## License

See `LICENSE`.