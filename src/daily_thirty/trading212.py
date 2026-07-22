from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from daily_thirty.state import Position, save_position


LIVE_BASE = "https://live.trading212.com"
DEMO_BASE = "https://demo.trading212.com"


@dataclass
class SyncResult:
    position: Position | None
    message: str
    raw_count: int = 0


def credentials_configured() -> bool:
    return bool(os.environ.get("T212_API_KEY") and os.environ.get("T212_API_SECRET"))


def _base_url(env: str | None = None) -> str:
    choice = (env or os.environ.get("T212_ENV") or "live").strip().lower()
    if choice in {"demo", "paper", "practice"}:
        return DEMO_BASE
    return LIVE_BASE


def _auth() -> tuple[str, str]:
    key = os.environ.get("T212_API_KEY", "").strip()
    secret = os.environ.get("T212_API_SECRET", "").strip()
    if not key or not secret:
        raise RuntimeError(
            "Missing T212_API_KEY / T212_API_SECRET. "
            "Create them in Trading 212 → Settings → API (Beta)."
        )
    return key, secret


def symbol_from_t212(ticker: str) -> str:
    """AAPL_US_EQ → AAPL."""
    raw = ticker.strip().upper()
    if "_US_EQ" in raw:
        return raw.split("_US_EQ", 1)[0]
    if "_" in raw:
        return raw.split("_", 1)[0]
    return raw


def fetch_positions(*, env: str | None = None) -> list[dict[str, Any]]:
    """GET /api/v0/equity/positions — read-only."""
    url = f"{_base_url(env)}/api/v0/equity/positions"
    with httpx.Client(timeout=30.0, auth=_auth()) as client:
        resp = client.get(url)
        if resp.status_code == 401:
            raise RuntimeError("Trading 212 auth failed (check API key/secret)")
        if resp.status_code == 403:
            raise RuntimeError(
                "Trading 212 forbidden — API is only for Invest / Stocks ISA, "
                "and the key needs Positions read permission."
            )
        if resp.status_code == 429:
            raise RuntimeError("Trading 212 rate-limited; try again in a few seconds")
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise RuntimeError(f"Unexpected Trading 212 positions payload: {type(data)}")


def _position_fields(raw: dict[str, Any]) -> tuple[str, float, float, float]:
    instrument = raw.get("instrument") or {}
    t212_ticker = (
        (instrument.get("ticker") if isinstance(instrument, dict) else None)
        or raw.get("ticker")
        or ""
    )
    symbol = symbol_from_t212(str(t212_ticker))
    qty = float(raw.get("quantity") or 0.0)
    avg = float(raw.get("averagePricePaid") or raw.get("average_price_paid") or 0.0)
    impact = raw.get("walletImpact") or raw.get("wallet_impact") or {}
    value = float(
        (impact.get("currentValue") if isinstance(impact, dict) else None)
        or (impact.get("current_value") if isinstance(impact, dict) else None)
        or 0.0
    )
    if value <= 0 and qty and raw.get("currentPrice"):
        value = qty * float(raw["currentPrice"])
    return symbol, qty, avg, value


def pick_single_position(
    rows: list[dict[str, Any]],
    *,
    watchlist: list[str] | None = None,
) -> Position | None:
    """Daily Thirty tracks one stock — pick the best matching open position."""
    parsed: list[tuple[Position, float]] = []
    wl = {t.upper() for t in (watchlist or [])}
    for raw in rows:
        symbol, qty, avg, value = _position_fields(raw)
        if qty <= 0 or not symbol or avg <= 0:
            continue
        if wl and symbol not in wl:
            continue
        parsed.append((Position(ticker=symbol, shares=qty, entry_price=avg), value))

    if not parsed and wl:
        # Fall back to any equity position if watchlist filter emptied the list
        for raw in rows:
            symbol, qty, avg, value = _position_fields(raw)
            if qty <= 0 or not symbol or avg <= 0:
                continue
            parsed.append((Position(ticker=symbol, shares=qty, entry_price=avg), value))

    if not parsed:
        return None
    parsed.sort(key=lambda x: x[1], reverse=True)
    return parsed[0][0]


def sync_position(
    *,
    watchlist: list[str] | None = None,
    env: str | None = None,
    persist: bool = True,
) -> SyncResult:
    """Pull open positions from Trading 212 and optionally write position.json."""
    rows = fetch_positions(env=env)
    pos = pick_single_position(rows, watchlist=watchlist)
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if persist:
        save_position(pos)
    if pos is None:
        return SyncResult(
            position=None,
            message=f"Trading 212: no open position (synced {when}).",
            raw_count=len(rows),
        )
    return SyncResult(
        position=pos,
        message=(
            f"Trading 212 sync ({when}): "
            f"{pos.shares:.6f} × {pos.ticker} @ {pos.entry_price:.4f} "
            f"(from {len(rows)} open position(s))."
        ),
        raw_count=len(rows),
    )


def sync_if_configured(
    *,
    watchlist: list[str] | None = None,
    persist: bool = True,
) -> SyncResult | None:
    """No-op when secrets are missing (keeps manual position.json workflow)."""
    if not credentials_configured():
        return None
    return sync_position(watchlist=watchlist, persist=persist)
