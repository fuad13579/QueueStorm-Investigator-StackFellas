# QueueStorm-Investigator-StackFellas

Backend service that analyzes support tickets and returns an investigator's
diagnosis plus recommended remediation actions.

## Quick start

```powershell
cd c:\Users\Tahmeed\susthackathonproject\QueueStorm-Investigator-StackFellas

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
copy .env.example .env

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints

| Method | Path             | Purpose                                   |
| ------ | ---------------- | ----------------------------------------- |
| GET    | `/health`        | Liveness probe (`{"status":"ok", ...}`)  |
| POST   | `/analyze-ticket`| Run investigator on a ticket              |
| GET    | `/docs`          | Interactive OpenAPI / Swagger UI          |

## Example

```bash
curl -s http://127.0.0.1:8000/health

curl -s -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket":{"ticket_id":"T-1","title":"Checkout 500s","description":"Users see 500 on /checkout","severity":"high","status":"open","environment":"prod","category":"application","affected_services":["checkout","payments"]}}'
```