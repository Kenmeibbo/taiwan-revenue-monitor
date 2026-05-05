# Taiwan Revenue Monitor

Local/cloud web app for querying monthly revenue of Taiwan listed and OTC companies.

Core features:

- Query monthly revenue by month, market, industry, stock code, or company name.
- Show companies whose selected month revenue is a new high against the previous 10 years of all monthly revenue.
- Sync latest official MOPS open-data CSV.
- Fetch historical monthly revenue summary pages from MOPS old site and cache snapshots.
- Supports Docker deployment with persistent data storage.

## Run Locally

```powershell
python server.py
```

Open:

```text
http://127.0.0.1:8088
```

Background start on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_server.ps1
```

## Configuration

Environment variables:

- `HOST`: bind host. Local default is `127.0.0.1`; cloud should use `0.0.0.0`.
- `PORT`: HTTP port. Default `8088`.
- `REVENUE_DATA_DIR`: data directory. Default `./data`.
- `REVENUE_SYNC_SECONDS`: auto-sync interval. Default `10800` seconds.

## Data Sources

- Listed monthly revenue CSV: `https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv`
- OTC monthly revenue CSV: `https://mopsfin.twse.com.tw/opendata/t187ap05_O.csv`
- Historical/monthly summary HTML: `https://mopsov.twse.com.tw/nas/t21/...`

Snapshots are saved under `data/snapshots`. In cloud deployment, mount persistent storage at the configured data directory.

## Docker

```powershell
docker build -t taiwan-revenue-monitor .
docker run -p 8088:8088 -e HOST=0.0.0.0 -v revenue-data:/app/data taiwan-revenue-monitor
```

## Render

This repository includes `render.yaml`. Create a Render Blueprint from the GitHub repository. Render will create a Docker web service and mount a persistent disk at `/app/data`.
