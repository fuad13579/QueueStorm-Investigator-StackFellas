# QueueStorm-Investigator-StackFellas

Backend service that analyzes support tickets and returns an investigator's
diagnosis and recommended remediation actions.

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

## Example

```bash
curl -s http://127.0.0.1:8000/health

curl -s -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{"ticket":{"ticket_id":"T-1","title":"Checkout 500s","description":"Users see 500 on /checkout","severity":"high","status":"open","environment":"prod","category":"application","affected_services":["checkout","payments"]}}'
```
