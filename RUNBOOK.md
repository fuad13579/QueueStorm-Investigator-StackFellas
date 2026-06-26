# QueueStorm Investigator — Runbook

> Member C — fill in once service is deployed.

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
curl http://localhost:8000/health
# Expected: {"status":"ok"}

curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @data/SUST_Preli_Sample_Cases.json
```

## Docker
```bash
docker build -t queuestorm-investigator .
docker run -p 8000:8000 queuestorm-investigator
```

## Environment Variables
See `.env.example`. No secrets required for the rule-based baseline.
