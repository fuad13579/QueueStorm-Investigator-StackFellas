# QueueStorm Investigator — Runbook

## Prerequisites

- Python 3.11+
- pip

## Local Setup

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Verify Service

```bash
# Liveness check
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Single-ticket smoke test (data/sample_input.json is a single request payload)
curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @data/sample_input.json

# Full validation against all 10 SUST sample cases
curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @data/SUST_Preli_Sample_Cases.json
# Note: data/SUST_Preli_Sample_Cases.json is a 10-case fixture pack, not a single
# request. To run each case through the API, iterate cases[i].input client-side.
# A captured reference response for TKT-001 lives at data/sample_output.json.
```

## Docker

```bash
docker build -t queuestorm-investigator .
docker run -p 8000:8000 queuestorm-investigator
```

## Environment Variables

See `.env.example`. No secrets required for the rule-based baseline.
