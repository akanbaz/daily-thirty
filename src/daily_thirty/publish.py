from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd

from daily_thirty.decide import Decision, is_eligible
from daily_thirty.prices import add_indicators, fetch_daily
from daily_thirty.state import Position


def _num(x: float | None, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{x:,.{nd}f}"


def _pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{x:+.1%}"


def _held_status(position: Position, stop_pct: float) -> dict | None:
    """Financials + indicators for the held stock (None if no prices)."""
    try:
        df = fetch_daily(position.ticker)
    except Exception:
        return None
    if df.empty:
        return None
    row = add_indicators(df).iloc[-1]
    close = float(row["close"])
    value = position.shares * close
    cost = position.cost
    pnl = value - cost
    return {
        "shares": position.shares,
        "entry_price": position.entry_price,
        "current_price": close,
        "cost": cost,
        "value": value,
        "pnl": pnl,
        "pnl_pct": (pnl / cost) if cost else None,
        "close": close,
        "sma20": float(row["sma20"]) if pd.notna(row["sma20"]) else None,
        "sma50": float(row["sma50"]) if pd.notna(row["sma50"]) else None,
        "sma200": float(row["sma200"]) if pd.notna(row["sma200"]) else None,
        "ret_10": float(row["ret_10"]) if pd.notna(row["ret_10"]) else None,
        "ret_5": float(row["ret_5"]) if pd.notna(row["ret_5"]) else None,
        "stop_level": position.entry_price * (1.0 - stop_pct),
        "stale": bool(df.attrs.get("stale", False)),
        "age_days": float(df.attrs.get("age_hours", 0.0)) / 24,
    }


def _watchlist_status(watchlist: list[str], held: str | None) -> list[dict]:
    """One row per watchlist name: does it qualify as a buy, and its momentum."""
    rows: list[dict] = []
    for ticker in watchlist:
        t = ticker.upper()
        try:
            df = fetch_daily(t)
        except Exception:
            rows.append({"ticker": t, "close": None, "qualifies": None,
                         "ret_10": None, "note": "no data", "is_held": t == held})
            continue
        if df.empty:
            rows.append({"ticker": t, "close": None, "qualifies": None,
                         "ret_10": None, "note": "no data", "is_held": t == held})
            continue
        r = add_indicators(df).iloc[-1]
        ok, why = is_eligible(r)
        rows.append({
            "ticker": t,
            "close": float(r["close"]),
            "qualifies": ok,
            "ret_10": float(r["ret_10"]) if pd.notna(r["ret_10"]) else None,
            "note": why,
            "is_held": t == held,
        })
    return rows


def build_payload(decision: Decision, position: Position | None, cfg: dict) -> dict:
    """Full status payload — now includes financials (site is intentionally detailed)."""
    stop_pct = float(cfg.get("stop_pct", 0.04))
    watchlist = [str(t).upper() for t in cfg.get("watchlist", [])]
    held = position.ticker if position else None

    status = _held_status(position, stop_pct) if position else None
    pos_block = None
    ind_block = None
    if position and status:
        pos_block = {
            "ticker": position.ticker,
            "shares": status["shares"],
            "entry_price": status["entry_price"],
            "current_price": status["current_price"],
            "cost": status["cost"],
            "value": status["value"],
            "pnl": status["pnl"],
            "pnl_pct": status["pnl_pct"],
        }
        ind_block = {
            "close": status["close"],
            "sma20": status["sma20"],
            "sma50": status["sma50"],
            "sma200": status["sma200"],
            "ret_10": status["ret_10"],
            "ret_5": status["ret_5"],
            "stop_level": status["stop_level"],
            "stale": status["stale"],
            "age_days": status["age_days"],
        }
    elif position:
        pos_block = {"ticker": position.ticker, "shares": position.shares,
                     "entry_price": position.entry_price, "current_price": None,
                     "cost": position.cost, "value": None, "pnl": None, "pnl_pct": None}

    return {
        "action": decision.action,
        "label": _action_label(decision.action),
        "message": decision.message,
        "reason": decision.reason,
        "next_ticker": decision.next_ticker,
        "next_price": decision.next_price,
        "position": pos_block,
        "indicators": ind_block,
        "watchlist": _watchlist_status(watchlist, held),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_outputs(
    decision: Decision,
    position: Position | None,
    cfg: dict,
    *,
    root: Path,
    repo_url: str = "https://github.com/akanbaz/daily-thirty",
) -> Path:
    """Write site/index.html, decision.json, DECISION.md. Returns site dir."""
    site = root / "site"
    site.mkdir(parents=True, exist_ok=True)
    payload = build_payload(decision, position, cfg)

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
    ind = payload.get("indicators")

    parts = [
        "# Today's decision",
        "",
        f"**{payload['label']}**",
        "",
        f"Updated (UTC): `{payload['generated_at']}`",
        "",
    ]

    parts += ["## Your position", ""]
    if pos:
        parts += [
            f"- **Ticker:** {pos['ticker']}",
            f"- **Shares:** {_num(pos['shares'], 6)}",
            f"- **Entry price:** {_num(pos['entry_price'])}",
            f"- **Current price:** {_num(pos['current_price'])}",
            f"- **Cost:** £{_num(pos['cost'])}",
            f"- **Value now:** £{_num(pos['value'])}",
            f"- **Profit / loss:** £{_num(pos['pnl'])} ({_pct(pos['pnl_pct'])})",
        ]
    else:
        parts.append("No position yet.")
    parts.append("")

    if ind:
        parts += [
            "## Signals",
            "",
            f"- Close **{_num(ind['close'])}** · SMA20 {_num(ind['sma20'])} · "
            f"SMA50 {_num(ind['sma50'])} · SMA200 {_num(ind['sma200'])}",
            f"- Momentum: 10-day {_pct(ind['ret_10'])} · 5-day {_pct(ind['ret_5'])}",
            f"- Sell if it closes below **{_num(ind['sma20'])}** (SMA20) or "
            f"**{_num(ind['stop_level'])}** (stop)",
        ]
        if ind["stale"]:
            parts.append(f"- ⚠️ Prices are cached ~{ind['age_days']:.0f} day(s) old — re-run to refresh.")
        parts.append("")

    parts += ["## Watchlist", "", "| Ticker | Price | Qualifies to buy | 10-day |",
              "|---|---|---|---|"]
    for w in payload["watchlist"]:
        mark = "✅" if w["qualifies"] else ("❌" if w["qualifies"] is False else "—")
        held = " *(held)*" if w["is_held"] else ""
        parts.append(f"| {w['ticker']}{held} | {_num(w['close'])} | {mark} | {_pct(w['ret_10'])} |")
    parts.append("")

    parts += [
        "## Details",
        "```",
        payload["message"],
        "```",
        "",
        "## Run again",
        f"- [Re-run decision]({repo_url}/actions/workflows/decide.yml)",
        f"- [Record trade]({repo_url}/actions/workflows/record-trade.yml)",
        "",
        "> This page shows your real position size and P/L. The repo is public — "
        "make it private (Settings → General → Danger Zone) if you don't want this visible.",
        "",
    ]
    return "\n".join(parts)


def _html(payload: dict, repo_url: str) -> str:
    action = payload["action"]
    label = payload["label"]
    badge = {
        "HOLD": "#0f6b5c",
        "SELL_AND_ROTATE": "#b45309",
        "BUY_FIRST": "#1d4ed8",
    }.get(action, "#334155")
    pos = payload.get("position")
    ind = payload.get("indicators")
    when = escape(payload["generated_at"])
    msg = escape(payload["message"])
    decide_url = f"{repo_url}/actions/workflows/decide.yml"
    buy_url = f"{repo_url}/actions/workflows/record-trade.yml"

    # Position financials grid
    if pos:
        pnl = pos.get("pnl")
        pnl_color = "#0f6b5c" if (pnl is not None and pnl >= 0) else "#b91c1c"
        pnl_txt = f"£{_num(pnl)} ({_pct(pos.get('pnl_pct'))})" if pnl is not None else "n/a"
        cells = [
            ("Ticker", escape(pos["ticker"])),
            ("Shares", _num(pos["shares"], 6)),
            ("Entry", _num(pos["entry_price"])),
            ("Price now", _num(pos["current_price"])),
            ("Cost", f"£{_num(pos['cost'])}"),
            ("Value now", f"£{_num(pos['value'])}"),
        ]
        grid = "".join(
            f'<div class="stat"><div class="k">{escape(k)}</div>'
            f'<div class="v">{escape(str(v))}</div></div>'
            for k, v in cells
        )
        grid += (
            f'<div class="stat"><div class="k">Profit / loss</div>'
            f'<div class="v" style="color:{pnl_color}">{escape(pnl_txt)}</div></div>'
        )
        pos_card = f'<div class="card"><div class="meta">Your position</div><div class="grid">{grid}</div></div>'
    else:
        pos_card = '<div class="card"><div class="meta">Your position</div><p>No position yet.</p></div>'

    # Signals card
    sig_card = ""
    if ind:
        stale = ""
        if ind["stale"]:
            stale = (f'<p class="warn">⚠️ Prices are cached ~{ind["age_days"]:.0f} day(s) old — '
                     f're-run to refresh.</p>')
        sig_card = f"""<div class="card"><div class="meta">Signals</div>
      <p>Close <strong>{_num(ind['close'])}</strong> · SMA20 {_num(ind['sma20'])} ·
         SMA50 {_num(ind['sma50'])} · SMA200 {_num(ind['sma200'])}</p>
      <p>Momentum: 10-day <strong>{_pct(ind['ret_10'])}</strong> · 5-day {_pct(ind['ret_5'])}</p>
      <p class="meta">Sell if it closes below {_num(ind['sma20'])} (SMA20) or
         {_num(ind['stop_level'])} (stop).</p>{stale}</div>"""

    # Watchlist table
    rows_html = ""
    for w in payload["watchlist"]:
        if w["qualifies"] is True:
            mark = '<span style="color:#0f6b5c">✅ yes</span>'
        elif w["qualifies"] is False:
            mark = '<span style="color:#b91c1c">❌ no</span>'
        else:
            mark = "—"
        held = ' <span class="meta">(held)</span>' if w["is_held"] else ""
        rows_html += (
            f"<tr><td>{escape(w['ticker'])}{held}</td><td>{_num(w['close'])}</td>"
            f"<td>{mark}</td><td>{_pct(w['ret_10'])}</td></tr>"
        )
    wl_card = f"""<div class="card"><div class="meta">Watchlist</div>
      <div class="tablewrap"><table>
        <thead><tr><th>Ticker</th><th>Price</th><th>Qualifies to buy</th><th>10-day</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table></div></div>"""

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
    main {{ max-width: 44rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
    h1 {{ font-size: 1.75rem; letter-spacing: -0.03em; margin: 0 0 0.25rem; }}
    .sub {{ color: #475569; margin-bottom: 1rem; }}
    .badge {{
      display: inline-block; background: {badge}; color: #fff;
      padding: 0.4rem 0.85rem; border-radius: 999px; font-weight: 700;
      letter-spacing: 0.02em; margin: 0.5rem 0 1rem;
    }}
    .card {{
      background: #fff; border-radius: 8px; padding: 1.1rem 1.25rem;
      box-shadow: 0 1px 2px rgba(18,32,42,0.06);
      border-left: 4px solid {badge}; margin-bottom: 1rem;
    }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); gap: 0.75rem; margin-top: 0.5rem; }}
    .stat .k {{ font-size: 0.8rem; color: #64748b; }}
    .stat .v {{ font-size: 1.15rem; font-weight: 700; }}
    pre {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem; margin: 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{ text-align: left; padding: 0.45rem 0.5rem; border-bottom: 1px solid #e2e8f0; }}
    th {{ color: #64748b; font-weight: 600; font-size: 0.85rem; }}
    .tablewrap {{ overflow-x: auto; }}
    a.btn {{ display: inline-block; margin: 0.35rem 0.5rem 0.35rem 0; padding: 0.55rem 0.9rem;
      background: #12202a; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 0.95rem; }}
    a.btn.secondary {{ background: #fff; color: #12202a; border: 1px solid #cbd5e1; }}
    .meta {{ font-size: 0.85rem; color: #64748b; }}
    .warn {{ color: #b45309; font-weight: 600; }}
  </style>
</head>
<body>
  <main>
    <h1>Daily Thirty</h1>
    <p class="sub">£30 a day · one stock · HOLD or SELL &amp; ROTATE</p>
    <div class="badge">{escape(label)}</div>
    {pos_card}
    {sig_card}
    {wl_card}
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
      This page shows your real position size and profit/loss. The repo is public —
      make it private if you don't want this visible. Amounts use the stock's price
      (USD for US listings); your Trading 212 GBP value will differ with the exchange rate.
    </p>
  </main>
</body>
</html>
"""
