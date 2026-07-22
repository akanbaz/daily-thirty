# Daily Thirty

£30/day · one stock · **HOLD** or **SELL & ROTATE**

Compute runs on **GitHub Actions**. The UI is a static page on **GitHub Pages**.

## Live UI (GitHub)

After the first Actions deploy:

**https://akanbaz.github.io/daily-thirty/**

Also always available in-repo:

**https://github.com/akanbaz/daily-thirty/blob/master/DECISION.md**

> Private repos: GitHub Pages needs **GitHub Pro** (or make the repo public) for a public `github.io` site. Collaborators can still open `DECISION.md` and Actions summaries.

## What happens each weekday
1. Actions fetches prices and applies your rules.
2. Publishes `site/index.html` + updates `DECISION.md`.
3. Pages serves the UI.

Manual re-run: [Actions → Decide → Run workflow](https://github.com/akanbaz/daily-thirty/actions/workflows/decide.yml)

## Record a trade (also on GitHub)
1. Open [Record trade](https://github.com/akanbaz/daily-thirty/actions/workflows/record-trade.yml)
2. **Run workflow**
3. Choose `bought` or `sold`, enter fill details
4. Site refreshes automatically

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
