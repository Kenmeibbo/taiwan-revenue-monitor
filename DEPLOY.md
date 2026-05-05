# Cloud deployment

This app is ready to deploy as a Docker web service.

## Render

1. Push this folder to a GitHub repository.
2. In Render, create a new Blueprint from that repository.
3. Render will read `render.yaml` and create:
   - one Docker web service
   - one persistent disk mounted at `/app/data`
4. After deployment, open the Render service URL.

The persistent disk matters because monthly snapshots are saved under `data/snapshots`.

## Generic Docker host

```powershell
docker build -t taiwan-revenue-monitor .
docker run -p 8088:8088 -e HOST=0.0.0.0 -v revenue-data:/app/data taiwan-revenue-monitor
```

Then open:

```text
http://SERVER_IP:8088
```

## Notes

- The service syncs official monthly revenue data every 3 hours.
- For "10-year single-month high", the app may need to backfill historical monthly snapshots in the background.
- A cloud account is required to actually publish the site. Local files alone cannot make the site reachable after your computer is turned off.
