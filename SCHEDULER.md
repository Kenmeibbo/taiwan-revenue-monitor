# Pure-program cloud revenue updates

The public Sites website is updated by `.github/workflows/revenue-sync.yml` using Python standard-library HTTP calls. No AI model, Codex automation, paid runner or API key is used. `start.bat` and the local Python server are unchanged; this cloud workflow does not depend on the user's PC.

Recent revenues use TWSE `https://openapi.twse.com.tw/v1/opendata/t187ap05_L` (listed) and TPEx `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O` (OTC) when their `資料年月` matches the requested month. Stale/mismatched/failed exports fall back to official MOPS per-month reports to preserve partial current-month coverage; history uses official per-month reports as well. OpenAPI export dates are not company announcement times. The government holiday calendar is a separate official CSV source.

Nominal times: Asia/Taipei 08:00,11:00,14:00,17:00,20:00,23:00. GitHub scheduled jobs can be delayed or missed under load. The server accepts the current scheduled hour (including a delayed run within that hour), never a caller-supplied clock, and records one completed capture per slot. Delays beyond the hour are skipped rather than collected overnight.

Collection dates: 1-11 inclusive every month. If the 11th is a holiday or weekend, add only the next Mon-Fri working day, skipping consecutive holidays. The Sites server uses official DGPA calendar dataset 14718 and rejects incomplete/unavailable annual calendars. Opening or filtering the website reads stored data without fetching official sources. The manual refresh button follows the same policy; it does not override hours/dates. Later corrections outside these dates wait for the next month's window.

The workflow polls the site's read-only policy before performing a POST refresh. A push runs unit tests and a live read-only readiness check, never a data refresh. `Run workflow` in GitHub Actions follows the same restrictions. Check workflow runs for failures. Source failures retain existing data and produce a failed job; new-high counts never use incomplete history.

GitHub disables scheduled workflows in idle public repos after 60 days. To avoid that limit, the workflow saves one genuine successful synchronization receipt per month in `.github/revenue-sync-status.json`. Only the sync job has `contents: write`; it uses GitHub's short-lived built-in token to commit the receipt, not a personal token. Branch protection or Actions write restrictions may prevent the receipt commit: fix the reported job failure rather than assuming the schedule remains active forever. Receipt-only commits can trigger other existing repository deployment integrations (such as Render auto-deploy) if still enabled.

The old Sites AI task, "哲緯台股月營收自動同步", must be paused/deleted in ChatGPT Scheduled. Deploying the new code or GitHub workflow does not disable it automatically. Until confirmed paused, it can still consume model quota even when the server skips its out-of-window calls.

