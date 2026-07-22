from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from daily_thirty.decide import Decision, is_eligible
from daily_thirty.prices import add_indicators, fetch_daily
from daily_thirty.state import Position

# Name of the GitHub Actions secret / env var holding the site passphrase.
PASSPHRASE_ENV = "SITE_PASSPHRASE"
PBKDF2_ITERATIONS = 200_000


def _num(x: float | None, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{x:,.{nd}f}"


def _pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n/a"
    return f"{x:+.1%}"


def _encrypt_secret(data: dict, passphrase: str) -> dict:
    """AES-256-GCM with a PBKDF2 key. Only the ciphertext is ever published."""
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, PBKDF2_ITERATIONS, 32)
    ct = AESGCM(key).encrypt(iv, json.dumps(data).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "iter": PBKDF2_ITERATIONS}


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
            df = pd.DataFrame()
        if df.empty:
            rows.append({"ticker": t, "close": None, "qualifies": None,
                         "ret_10": None, "is_held": t == held})
            continue
        r = add_indicators(df).iloc[-1]
        ok, _why = is_eligible(r)
        rows.append({
            "ticker": t,
            "close": float(r["close"]),
            "qualifies": ok,
            "ret_10": float(r["ret_10"]) if pd.notna(r["ret_10"]) else None,
            "is_held": t == held,
        })
    return rows


def build_payload(decision: Decision, position: Position | None, cfg: dict) -> dict:
    """Public payload. Money numbers go into an encrypted blob, not the clear text."""
    stop_pct = float(cfg.get("stop_pct", 0.04))
    watchlist = [str(t).upper() for t in cfg.get("watchlist", [])]
    held = position.ticker if position else None

    status = _held_status(position, stop_pct) if position else None

    # Clear (public) blocks — nothing that reveals size, entry, value, or P/L.
    # Note: the entry-based stop level is left OUT because it would reveal entry.
    ind_block = None
    secret = None
    if position and status:
        ind_block = {
            "close": status["close"],
            "sma20": status["sma20"],
            "sma50": status["sma50"],
            "sma200": status["sma200"],
            "ret_10": status["ret_10"],
            "ret_5": status["ret_5"],
            "stale": status["stale"],
            "age_days": status["age_days"],
        }
        secret = {
            "shares": status["shares"],
            "entry_price": status["entry_price"],
            "current_price": status["current_price"],
            "cost": status["cost"],
            "value": status["value"],
            "pnl": status["pnl"],
            "pnl_pct": status["pnl_pct"],
            "stop_level": status["stop_level"],
        }

    payload: dict = {
        "action": decision.action,
        "label": _action_label(decision.action),
        "message": decision.message,
        "reason": decision.reason,
        "next_ticker": decision.next_ticker,
        "next_price": decision.next_price,
        "position": {"ticker": position.ticker} if position else None,
        "indicators": ind_block,
        "watchlist": _watchlist_status(watchlist, held),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    passphrase = os.environ.get(PASSPHRASE_ENV, "").strip()
    if secret and passphrase:
        payload["financials"] = "locked"
        payload["encrypted"] = _encrypt_secret(secret, passphrase)
    elif secret:
        # No passphrase configured — publish nothing rather than leak the numbers.
        payload["financials"] = "hidden"
    else:
        payload["financials"] = "none"
    return payload


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
        "# Today's decision", "",
        f"**{payload['label']}**", "",
        f"Updated (UTC): `{payload['generated_at']}`", "",
        "## Your position", "",
    ]
    if pos:
        parts.append(f"**{pos['ticker']}** — shares, value & profit/loss are private "
                     "(unlock on the site with your passphrase).")
    else:
        parts.append("No position yet.")
    parts.append("")

    if ind:
        parts += [
            "## Signals", "",
            f"- Close **{_num(ind['close'])}** · SMA20 {_num(ind['sma20'])} · "
            f"SMA50 {_num(ind['sma50'])} · SMA200 {_num(ind['sma200'])}",
            f"- Momentum: 10-day {_pct(ind['ret_10'])} · 5-day {_pct(ind['ret_5'])}",
            f"- Sell if it closes below **{_num(ind['sma20'])}** (SMA20).",
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
    parts += [
        "", "## Details", "```", payload["message"], "```", "",
        f"- [Re-run decision]({repo_url}/actions/workflows/decide.yml)",
        f"- [Record trade]({repo_url}/actions/workflows/record-trade.yml)", "",
        "> Financials (size / value / P&L) are encrypted and only viewable on the "
        "site with your passphrase. The repo is public.", "",
    ]
    return "\n".join(parts)


def _financials_card_html(payload: dict) -> str:
    state = payload.get("financials")
    if state == "locked":
        enc = json.dumps(payload["encrypted"])
        return f"""<div class="card" id="fin">
      <div class="meta">Financials 🔒</div>
      <div id="locked">
        <p class="meta">Private — enter your passphrase to view size, value &amp; P/L.</p>
        <div class="row">
          <input id="pass" type="password" placeholder="passphrase"
                 autocomplete="off" onkeydown="if(event.key==='Enter')unlock()" />
          <button class="btn" onclick="unlock()">Unlock</button>
        </div>
        <p id="err" class="warn" style="display:none">Wrong passphrase — try again.</p>
      </div>
      <div id="unlocked" style="display:none"></div>
    </div>
    <script>
      const ENC = {enc};
      const b = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
      const money = x => (x==null? 'n/a' : '£'+Number(x).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}}));
      const num = (x,n=2) => (x==null? 'n/a' : Number(x).toLocaleString(undefined,{{minimumFractionDigits:n,maximumFractionDigits:n}}));
      const pct = x => (x==null? 'n/a' : (x>=0?'+':'')+(x*100).toFixed(1)+'%');
      async function unlock() {{
        const pass = document.getElementById('pass').value;
        const err = document.getElementById('err');
        try {{
          const baseKey = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
          const key = await crypto.subtle.deriveKey(
            {{name:'PBKDF2', salt:b(ENC.salt), iterations:ENC.iter, hash:'SHA-256'}},
            baseKey, {{name:'AES-GCM', length:256}}, false, ['decrypt']);
          const ptBuf = await crypto.subtle.decrypt({{name:'AES-GCM', iv:b(ENC.iv)}}, key, b(ENC.ct));
          const f = JSON.parse(new TextDecoder().decode(ptBuf));
          const pnlColor = f.pnl >= 0 ? '#0f6b5c' : '#b91c1c';
          document.getElementById('unlocked').innerHTML =
            '<div class="grid">' +
            '<div class="stat"><div class="k">Shares</div><div class="v">'+num(f.shares,6)+'</div></div>' +
            '<div class="stat"><div class="k">Entry</div><div class="v">'+num(f.entry_price)+'</div></div>' +
            '<div class="stat"><div class="k">Price now</div><div class="v">'+num(f.current_price)+'</div></div>' +
            '<div class="stat"><div class="k">Cost</div><div class="v">'+money(f.cost)+'</div></div>' +
            '<div class="stat"><div class="k">Value now</div><div class="v">'+money(f.value)+'</div></div>' +
            '<div class="stat"><div class="k">Profit / loss</div><div class="v" style="color:'+pnlColor+'">'+money(f.pnl)+' ('+pct(f.pnl_pct)+')</div></div>' +
            '</div>' +
            '<p class="meta">Also sells if it closes below '+num(f.stop_level)+' (your entry stop).</p>';
          document.getElementById('locked').style.display = 'none';
          document.getElementById('unlocked').style.display = 'block';
        }} catch (e) {{
          err.style.display = 'block';
        }}
      }}
    </script>"""
    if state == "hidden":
        return ('<div class="card"><div class="meta">Financials 🔒</div>'
                '<p class="meta">Not published — no site passphrase configured '
                f'(set the <code>{PASSPHRASE_ENV}</code> Actions secret).</p></div>')
    return ""


def _html(payload: dict, repo_url: str) -> str:
    action = payload["action"]
    label = payload["label"]
    badge = {"HOLD": "#0f6b5c", "SELL_AND_ROTATE": "#b45309",
             "BUY_FIRST": "#1d4ed8"}.get(action, "#334155")
    pos = payload.get("position")
    ind = payload.get("indicators")
    when = escape(payload["generated_at"])
    msg = escape(payload["message"])
    decide_url = f"{repo_url}/actions/workflows/decide.yml"
    buy_url = f"{repo_url}/actions/workflows/record-trade.yml"

    pos_line = (f"<strong>{escape(pos['ticker'])}</strong>" if pos else "No position yet.")
    pos_card = (f'<div class="card"><div class="meta">Position</div><p>{pos_line}</p></div>')

    fin_card = _financials_card_html(payload)

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
      <p class="meta">Sell if it closes below {_num(ind['sma20'])} (SMA20).</p>{stale}</div>"""

    rows_html = ""
    for w in payload["watchlist"]:
        if w["qualifies"] is True:
            mark = '<span style="color:#0f6b5c">✅ yes</span>'
        elif w["qualifies"] is False:
            mark = '<span style="color:#b91c1c">❌ no</span>'
        else:
            mark = "—"
        held = ' <span class="meta">(held)</span>' if w["is_held"] else ""
        rows_html += (f"<tr><td>{escape(w['ticker'])}{held}</td><td>{_num(w['close'])}</td>"
                      f"<td>{mark}</td><td>{_pct(w['ret_10'])}</td></tr>")
    wl_card = f"""<div class="card"><div class="meta">Watchlist</div>
      <div class="tablewrap"><table>
        <thead><tr><th>Ticker</th><th>Price</th><th>Qualifies to buy</th><th>10-day</th></tr></thead>
        <tbody>{rows_html}</tbody></table></div></div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Daily Thirty — today's decision</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #eef2f4; color: #12202a; line-height: 1.5; }}
    main {{ max-width: 44rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
    h1 {{ font-size: 1.75rem; letter-spacing: -0.03em; margin: 0 0 0.25rem; }}
    .sub {{ color: #475569; margin-bottom: 1rem; }}
    .badge {{ display: inline-block; background: {badge}; color: #fff; padding: 0.4rem 0.85rem;
      border-radius: 999px; font-weight: 700; letter-spacing: 0.02em; margin: 0.5rem 0 1rem; }}
    .card {{ background: #fff; border-radius: 8px; padding: 1.1rem 1.25rem;
      box-shadow: 0 1px 2px rgba(18,32,42,0.06); border-left: 4px solid {badge}; margin-bottom: 1rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); gap: 0.75rem; margin-top: 0.5rem; }}
    .stat .k {{ font-size: 0.8rem; color: #64748b; }}
    .stat .v {{ font-size: 1.15rem; font-weight: 700; }}
    .row {{ display: flex; gap: 0.5rem; margin-top: 0.5rem; }}
    input {{ flex: 1; padding: 0.5rem 0.7rem; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 1rem; }}
    button.btn {{ border: none; cursor: pointer; }}
    pre {{ white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem; margin: 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{ text-align: left; padding: 0.45rem 0.5rem; border-bottom: 1px solid #e2e8f0; }}
    th {{ color: #64748b; font-weight: 600; font-size: 0.85rem; }}
    .tablewrap {{ overflow-x: auto; }}
    a.btn, button.btn {{ display: inline-block; margin: 0.35rem 0.5rem 0.35rem 0; padding: 0.55rem 0.9rem;
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
    {fin_card}
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
      Decision, signals and watchlist are public. Your size, value and profit/loss are
      AES-encrypted and only readable in your browser after you enter the passphrase.
    </p>
  </main>
</body>
</html>
"""
