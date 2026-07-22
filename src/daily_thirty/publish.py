from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from daily_thirty.decide import Decision
from daily_thirty.state import Position


def decision_to_dict(d: Decision, pos: Position | None) -> dict:
    """Public payload — ticker only, no shares / entry / £ size."""
    return {
        "action": d.action,
        "message": d.message,
        "reason": d.reason,
        "next_ticker": d.next_ticker,
        "next_price": d.next_price,
        # Intentionally omit shares, entry, current_value, exit_value
        "position": {"ticker": pos.ticker} if pos else None,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_outputs(
    decision: Decision,
    position: Position | None,
    *,
    root: Path,
    repo_url: str = "https://github.com/akanbaz/daily-thirty",
) -> Path:
    """Write site/index.html, decision.json, DECISION.md. Returns site dir."""
    site = root / "site"
    site.mkdir(parents=True, exist_ok=True)
    payload = decision_to_dict(decision, position)

    (site / "decision.json").write_text(json.dumps(payload, indent=2) + "\n")
    (root / "DECISION.md").write_text(_markdown(payload, repo_url))
    (site / "index.html").write_text(_html(payload, repo_url))
    return site


def _action_label(action: str) -> str:
    return {
        "HOLD": "HOLD",
        "SELL_AND_ROTATE": "SELL & ROTATE",
        "BUY_FIRST": "BUY (open / first £30)",
    }.get(action, action)


def _markdown(payload: dict, repo_url: str) -> str:
    pos = payload.get("position")
    pos_line = "No position yet."
    if pos:
        pos_line = f"**{pos['ticker']}** (size private)"
    return f"""# Today's decision

**{_action_label(payload['action'])}**

Updated (UTC): `{payload['generated_at']}`

## Position
{pos_line}

## Details
```
{payload['message']}
```

## Sync / record
- Position syncs from Trading 212 when secrets are set (read-only; not committed).
- [Re-run decision]({repo_url}/actions/workflows/decide.yml)
- [Record trade]({repo_url}/actions/workflows/record-trade.yml) (optional; does not commit holdings)
"""


def _html(payload: dict, repo_url: str) -> str:
    action = payload["action"]
    label = _action_label(action)
    badge = {
        "HOLD": "#0f6b5c",
        "SELL_AND_ROTATE": "#b45309",
        "BUY_FIRST": "#1d4ed8",
    }.get(action, "#334155")
    pos = payload.get("position")
    if pos:
        pos_html = f"<strong>{escape(pos['ticker'])}</strong> <span class=\"meta\">(size private)</span>"
    else:
        pos_html = "No position yet."

    msg = escape(payload["message"])
    when = escape(payload["generated_at"])
    buy_url = f"{repo_url}/actions/workflows/record-trade.yml"
    decide_url = f"{repo_url}/actions/workflows/decide.yml"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daily Thirty — today's decision</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{
      margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
      background: #eef2f4; color: #12202a; line-height: 1.5;
    }}
    main {{ max-width: 42rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
    h1 {{ font-size: 1.75rem; letter-spacing: -0.03em; margin: 0 0 0.25rem; }}
    .sub {{ color: #475569; margin-bottom: 1.5rem; }}
    .badge {{
      display: inline-block; background: {badge}; color: #fff;
      padding: 0.4rem 0.85rem; border-radius: 999px; font-weight: 700;
      letter-spacing: 0.02em; margin: 0.5rem 0 1rem;
    }}
    .card {{
      background: #fff; border-radius: 8px; padding: 1.25rem 1.35rem;
      box-shadow: 0 1px 2px rgba(18,32,42,0.06);
      border-left: 4px solid {badge}; margin-bottom: 1rem;
    }}
    pre {{
      white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.95rem; margin: 0;
    }}
    a.btn {{
      display: inline-block; margin: 0.35rem 0.5rem 0.35rem 0;
      padding: 0.55rem 0.9rem; background: #12202a; color: #fff;
      text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 0.95rem;
    }}
    a.btn.secondary {{ background: #fff; color: #12202a; border: 1px solid #cbd5e1; }}
    .meta {{ font-size: 0.85rem; color: #64748b; }}
  </style>
</head>
<body>
  <main>
    <h1>Daily Thirty</h1>
    <p class="sub">£30 a day · one stock · HOLD or SELL &amp; ROTATE</p>
    <div class="badge">{escape(label)}</div>
    <div class="card">
      <div class="meta">Position</div>
      <p>{pos_html}</p>
    </div>
    <div class="card">
      <div class="meta">Details</div>
      <pre>{msg}</pre>
    </div>
    <p class="meta">Computed on GitHub Actions · UTC {when}</p>
    <p>
      <a class="btn" href="{decide_url}">Re-run decision</a>
      <a class="btn secondary" href="{buy_url}">Record buy / sell</a>
      <a class="btn secondary" href="{repo_url}">Repo</a>
    </p>
    <p class="meta">
      Public repo: API keys stay in Actions secrets; share counts are not published.
      Sync is read-only from Trading 212 — no orders are placed.
    </p>
  </main>
</body>
</html>
"""
