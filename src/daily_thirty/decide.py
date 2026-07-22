from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from daily_thirty.prices import add_indicators, fetch_daily
from daily_thirty.state import Position


@dataclass
class Candidate:
    ticker: str
    close: float
    ret_10: float
    ret_5: float
    why: str


@dataclass
class Decision:
    action: str  # HOLD | SELL_AND_ROTATE | BUY_FIRST
    message: str
    position: Position | None = None
    current_value: float | None = None
    exit_value: float | None = None
    next_ticker: str | None = None
    next_price: float | None = None
    reason: str | None = None


def _latest_row(df: pd.DataFrame) -> pd.Series | None:
    if df.empty:
        return None
    enriched = add_indicators(df)
    row = enriched.iloc[-1]
    if pd.isna(row.get("sma200")):
        return None
    return row


def is_eligible(row: pd.Series) -> tuple[bool, str]:
    close = float(row["close"])
    if not (close > float(row["sma50"]) and close > float(row["sma200"])):
        return False, "not in uptrend (need price > SMA50 and SMA200)"
    ret_10 = float(row["ret_10"]) if pd.notna(row["ret_10"]) else float("-inf")
    if ret_10 <= 0:
        return False, "10-day momentum not positive"
    ret_5 = float(row["ret_5"]) if pd.notna(row["ret_5"]) else 0.0
    if ret_5 >= 0.15:
        return False, "up 15%+ in 5 days (overextended)"
    return True, (
        f"uptrend (above SMA50 & SMA200), "
        f"10d momentum {ret_10:+.1%}, 5d move {ret_5:+.1%}"
    )


def should_exit(row: pd.Series, entry_price: float, stop_pct: float) -> tuple[bool, str]:
    close = float(row["close"])
    stop_level = entry_price * (1.0 - stop_pct)
    if close <= stop_level:
        drop = close / entry_price - 1.0
        return True, f"stop hit ({drop:.1%} vs entry; stop at -{stop_pct:.0%})"
    if close < float(row["sma20"]):
        return True, "closed below SMA20"
    return False, "still above stop and SMA20"


def pick_next(
    watchlist: list[str],
    *,
    exclude: str | None = None,
) -> tuple[Candidate | None, list[str]]:
    """Return (best candidate, fetch/skip notes)."""
    import time

    best: Candidate | None = None
    notes: list[str] = []
    for ticker in watchlist:
        if exclude and ticker.upper() == exclude.upper():
            continue
        try:
            df = fetch_daily(ticker)
            time.sleep(0.6)
        except Exception as exc:
            notes.append(f"{ticker}: fetch failed ({exc})")
            time.sleep(1.0)
            continue
        row = _latest_row(df)
        if row is None:
            notes.append(f"{ticker}: not enough history")
            continue
        ok, why = is_eligible(row)
        if not ok:
            notes.append(f"{ticker}: {why}")
            continue
        cand = Candidate(
            ticker=ticker.upper(),
            close=float(row["close"]),
            ret_10=float(row["ret_10"]),
            ret_5=float(row["ret_5"]),
            why=why,
        )
        notes.append(f"{ticker}: eligible ({why})")
        if best is None or cand.ret_10 > best.ret_10:
            best = cand
    return best, notes


def decide(cfg: dict, position: Position | None) -> Decision:
    stop_pct = float(cfg.get("stop_pct", 0.04))
    watchlist = [str(t).upper() for t in cfg.get("watchlist", [])]
    daily = float(cfg.get("daily_pounds", 30))

    if position is None:
        nxt, notes = pick_next(watchlist)
        if nxt is None:
            detail = "\n".join(f"  - {n}" for n in notes[-8:]) or "  (no details)"
            return Decision(
                action="BUY_FIRST",
                message=(
                    f"No position yet, and no watchlist name qualifies today.\n"
                    f"Add cash (£{daily:.0f}) and wait, or edit config.yaml watchlist.\n"
                    f"Checked:\n{detail}"
                ),
            )
        return Decision(
            action="BUY_FIRST",
            message=(
                f"No position yet.\n"
                f"Buy £{daily:.0f} of {nxt.ticker} (about {daily / nxt.close:.4f} shares "
                f"at ~{nxt.close:.2f}).\n"
                f"Why: {nxt.why}\n"
                f"After the trade:  daily bought {nxt.ticker} <shares> <fill_price>"
            ),
            next_ticker=nxt.ticker,
            next_price=nxt.close,
            reason=nxt.why,
        )

    # Have a position — check HOLD vs exit
    try:
        df = fetch_daily(position.ticker)
    except Exception as exc:
        return Decision(
            action="HOLD",
            message=f"Could not fetch {position.ticker}: {exc}\nTry again later.",
            position=position,
        )
    row = _latest_row(df)
    if row is None:
        return Decision(
            action="HOLD",
            message=f"Not enough price history for {position.ticker} yet. HOLD for now.",
            position=position,
        )

    close = float(row["close"])
    value = position.shares * close
    exit_now, exit_why = should_exit(row, position.entry_price, stop_pct)

    if not exit_now:
        pnl = value / position.cost - 1.0 if position.cost else 0.0
        return Decision(
            action="HOLD",
            message=(
                f"Decision: HOLD {position.ticker}\n"
                f"Shares: {position.shares:.6f}\n"
                f"Entry: {position.entry_price:.2f}\n"
                f"Last close: {close:.2f}\n"
                f"Current value: £{value:.2f} ({pnl:+.1%} vs entry)\n"
                f"Why hold: {exit_why}\n"
                f"You can still add today's £{daily:.0f} into {position.ticker}."
            ),
            position=position,
            current_value=value,
            reason=exit_why,
        )

    # SELL & ROTATE
    nxt, _notes = pick_next(watchlist, exclude=position.ticker)
    if nxt is None:
        return Decision(
            action="SELL_AND_ROTATE",
            message=(
                f"Decision: SELL {position.ticker} (then stay in cash — no replacement qualifies)\n"
                f"Exit reason: {exit_why}\n"
                f"Shares: {position.shares:.6f}\n"
                f"Last close: {close:.2f}\n"
                f"Exit value (approx): £{value:.2f}\n"
                f"After selling:  daily sold <fill_price>"
            ),
            position=position,
            exit_value=value,
            reason=exit_why,
        )

    shares_next = value / nxt.close if nxt.close else 0.0
    return Decision(
        action="SELL_AND_ROTATE",
        message=(
            f"Decision: SELL & ROTATE\n"
            f"\n"
            f"1) SELL {position.ticker}\n"
            f"   Exit reason: {exit_why}\n"
            f"   Shares: {position.shares:.6f}\n"
            f"   Last close: {close:.2f}\n"
            f"   Exit value (approx): £{value:.2f}\n"
            f"\n"
            f"2) BUY {nxt.ticker} with that full amount (~£{value:.2f})\n"
            f"   About {shares_next:.4f} shares at ~{nxt.close:.2f}\n"
            f"   Why chosen: {nxt.why} (best 10-day momentum on the watchlist)\n"
            f"\n"
            f"After trades:\n"
            f"  daily sold <sell_fill_price>\n"
            f"  daily bought {nxt.ticker} <shares> <buy_fill_price>"
        ),
        position=position,
        exit_value=value,
        next_ticker=nxt.ticker,
        next_price=nxt.close,
        reason=exit_why,
    )
