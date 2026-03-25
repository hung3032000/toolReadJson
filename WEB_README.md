# toolReadJson Web

## Run

```powershell
pip install -r requirements-web.txt
uvicorn app_web:app --host 127.0.0.1 --port 8000 --reload
```

Open:

```
http://127.0.0.1:8000
```

## LAN via nginx on Windows

One-line start from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\start_public.ps1
```

What it does:

- starts or reuses the backend on `127.0.0.1:8000`
- runs `nginx -t`, then starts or reloads `nginx`
- checks `http://127.0.0.1:8000/healthz` and `http://127.0.0.1/healthz`
- prints local and LAN URLs for quick sharing
- does not change Windows Firewall, router settings, or any network policy

Optional flags:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\start_public.ps1 -Restart
powershell -ExecutionPolicy Bypass -File .\deploy\start_public.ps1 -NginxRoot C:\path\to\nginx
```

This repo also includes:

- `deploy/start_web_prod.ps1`: start FastAPI backend on `127.0.0.1:8000`
- `deploy/stop_web_prod.ps1`: stop the backend using saved PID
- `deploy/start_public.ps1`: wrapper to start backend + nginx for LAN testing
- `deploy/nginx/toolreadjson.windows.conf`: reverse-proxy server block for `nginx`

Typical flow:

```powershell
cd C:\Users\hung.pn\Desktop\Code\toolReadJson
powershell -ExecutionPolicy Bypass -File .\deploy\start_public.ps1
```

If you prefer the old manual flow, keep `nginx` port `80` pointed to `http://127.0.0.1:8000` and run:

```powershell
cd C:\Users\hung.pn\Desktop\Code\toolReadJson
.\deploy\start_web_prod.ps1

cd C:\Users\hung.pn\Downloads\nginx-1.29.4\nginx-1.29.4
.\nginx.exe -t
.\nginx.exe -s reload
```

Quick checks:

- `http://127.0.0.1/`
- `http://127.0.0.1/healthz`

Stop only the backend:

```powershell
cd C:\Users\hung.pn\Desktop\Code\toolReadJson
.\deploy\stop_web_prod.ps1
```

To expose it outside your machine, you still need:
This LAN-only setup does not try to expose the app to the Internet.

Notes:

- `start_public.ps1` does not open Windows Firewall, create rules, or change any network policy.
- The user running `start_public.ps1` still needs write access to the `nginx` root, especially its `logs` folder and `nginx.pid`.
- Users should be on the same local network to access the printed `LAN URL`.

## API quick check

- `GET /api/v1/meta/options`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/logs`
- `GET /api/v1/jobs/{job_id}/sheets`
- `GET /api/v1/jobs/{job_id}/results?sheet=single_case&page=1&page_size=100`
- `POST /api/v1/jobs/{job_id}/exports`
- `GET /api/v1/jobs/{job_id}/exports/{export_id}`
- `GET /api/v1/jobs/{job_id}/exports/{export_id}/download`
- `GET /api/v1/history`

## Notes

- Web backend runs jobs in background queue (single worker).
- Job execution bridges to existing `Code/process.py` pipeline.
- `config.json` runtime block controls async throttle behavior.
- Job/history is persisted in `web_state.db` (SQLite).
- Result tables are cached to `artifacts/<job_id>/*.parquet` for faster query.
- Retention cleanup removes terminal jobs older than 7 days from DB and cache.
- Web jobs skip immediate Excel write; Excel is generated on-demand via export API.
- Secrets can be sourced from keyring/env vars using `Code/secret_provider.py`.

## Secret migration (optional but recommended)

```powershell
python Code\migrate_secrets.py
```

Then rotate/remove secret values from `config.json`.
You can bootstrap from `config.example.json` for a non-secret baseline.
