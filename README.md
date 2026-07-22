# Daily Thirty

£30/day · one stock · **HOLD** or **SELL & ROTATE**

Compute runs on **GitHub Actions**. The UI is a static page on **GitHub Pages**.

## Live UI (GitHub)

After the first Actions deploy:

**https://akanbaz.github.io/daily-thirty/**

Also always available in-repo:

**https://github.com/akanbaz/daily-thirty/blob/master/DECISION.md**

> Private repos: GitHub Pages needs **GitHub Pro** (or make the repo public) for a public `github.io` site. Collaborators can still open `DECISION.md` and Actions summaries.

## What happens when you run it
You trigger it yourself — there is no scheduler. Each run:
1. Actions fetches prices and applies your rules.
2. Publishes `site/index.html` + updates `DECISION.md`.
3. Pages serves the UI.

Run it: [Actions → Decide → Run workflow](https://github.com/akanbaz/daily-thirty/actions/workflows/decide.yml)

## Privacy (public repo)

- **API keys:** store only as GitHub Actions secrets — never in files.
- **`position.json`:** gitignored; not committed. Decide syncs from Trading 212 each run when secrets are set.
- **Public UI:** shows action + ticker + reasons; **not** share counts, entry, or £ position size.

## Trading 212 sync (read-only)

The app can **read** your open position from Trading 212 into a local `position.json` for that run.
It does **not** place buys or sells.

1. In Trading 212: **Settings → API (Beta)** → create a key with **positions read** only (Invest or Stocks ISA).
2. Add GitHub Actions secrets on this repo:
   - `T212_API_KEY`
   - `T212_API_SECRET`
   - optional `T212_ENV` = `live` (default) or `demo`
3. Re-run [Decide](https://github.com/akanbaz/daily-thirty/actions/workflows/decide.yml).

Locally:
```bash
export T212_API_KEY=...
export T212_API_SECRET=...
export T212_ENV=live   # or demo
uv run daily sync
uv run daily decide --sync
```

If you hold several names, it picks the largest (by value) that is on the watchlist.

## Record a trade (optional)
Still available for a one-off fill in Actions; holdings are **not** committed to git.
Prefer Trading 212 sync for an ongoing position.

## Rules
- Uptrend: price > SMA50 and SMA200  
- Positive 10-day momentum  
- Skip if +15% in 5 days  
- HOLD unless −4% from entry or close < SMA20  

Edit the watchlist in [`config.yaml`](config.yaml).

## Local (optional)
```bash
cd ~/Projects/daily-thirty
uv sync
uv run daily ui          # local only
uv run python scripts/github_decide.py
```
