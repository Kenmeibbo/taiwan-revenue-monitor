# Security Audit Report (Strict API Key Leakage Check)

Date: 2026-05-08 (UTC)
Repository: `taiwan-revenue-monitor`

## Scope
- Current working tree (all tracked repository files).
- Git history scan across recent commits on this branch (`git rev-list --all | head -n 200`).
- Sensitive filename pattern check (`.env`, `.pem`, private-key style names).

## Strict Check Methods
1. **Current tree secret-pattern scan** using regex for common credential formats:
   - `api key`, `secret`, `token`, `password`
   - AWS key IDs (`AKIA...`, `ASIA...`)
   - GitHub tokens (`ghp_`, `github_pat_`)
   - OpenAI-like keys (`sk-...`)
   - Slack token prefixes (`xox...`)
   - Google API key style (`AIza...`)
   - PEM private key headers (`-----BEGIN ... PRIVATE KEY-----`)
2. **Git history secret-pattern scan** on commit snapshots (same regex set).
3. **Sensitive filename scan** for likely leaked credential files.
4. **Long-string heuristic scan** for suspicious high-entropy token-like strings.

## Results
- **No hard-coded API keys, access tokens, passwords, or private key blocks were found** in the current tree.
- **No leaked credentials were found** in scanned git history snapshots.
- **No sensitive credential-like files** (`.env`, `.pem`, private-key names) are tracked.
- The only keyword hits were non-secret text/variable names (e.g., `market_token`) and audit-document wording.

## GitHub and Render Relationship
Yes, this repository is directly designed for **GitHub → Render** deployment:
- `DEPLOY.md` states: push to GitHub, then create Render Blueprint from that repo.
- `render.yaml` is a Render Blueprint spec (`type: web`, `runtime: docker`, env vars).
- `README.md` repeats Render deployment from GitHub repository.

Conclusion: **GitHub hosts source code; Render consumes this repo (especially `render.yaml`) to deploy.**

## Notes / Residual Risk
- Regex/heuristic scanning cannot guarantee detection of every possible secret format.
- For maximum assurance, add CI secret scanning (e.g., gitleaks/trufflehog) on every push and PR.
