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
