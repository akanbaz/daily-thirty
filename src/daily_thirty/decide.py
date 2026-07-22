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


def _enriched_last(df: pd.DataFrame) -> pd.Series | None:
    """Latest day with indicators attached, or None if there's no price data."""
    if df.empty:
        return None
    return add_indicators(df).iloc[-1]


def is_eligible(row: pd.Series) -> tuple[bool, str]:
    # Buying rules need the long trend, so we need ~200 days of history.
    if pd.isna(row.get("sma200")):
        return False, "not enough price history yet (need ~200 days)"
    close = float(row["close"])
    if not (close > float(row["sma50"]) and close > float(row["sma200"])):
        return False, "not in uptrend (need price > SMA50 and SMA200)"
    ret_10 = float(row["ret_10"]) if pd.notna(row["ret_10"]) else float("-inf")
    if ret_10 <= 0:
        return False, "10-day momentum not positive"
    ret_5 = float(row["ret_5"]) if pd.notna(row["ret_5"]) else 0.0
    if ret_5 > 0.15:
        return False, "up more than 15% in 5 days (overextended)"
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
            time.sleep(0.15)
        except Exception as exc:
            err = str(exc).split("\n")[0]
            if "429" in err:
                err = "rate-limited (Yahoo 429) — need committed cache"
            notes.append(f"{ticker}: fetch failed ({err})")
            continue
        row = _enriched_last(df)
        if row is None:
            notes.append(f"{ticker}: no price data")
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
                f"Buy £{daily:.0f} of {nxt.ticker} (market ~{nxt.close:.2f}).\n"
                f"Why: {nxt.why}"
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
    row = _enriched_last(df)
    # The HOLD/SELL rules only need entry price and SMA20 (20 days), so we can
    # decide even for a stock that doesn't yet have the 200 days buying needs.
    if row is None or pd.isna(row.get("sma20")):
        return Decision(
            action="HOLD",
            message=f"Not enough price history for {position.ticker} yet (need ~20 days). HOLD for now.",
            position=position,
        )

    close = float(row["close"])
    value = position.shares * close
    exit_now, exit_why = should_exit(row, position.entry_price, stop_pct)

    if not exit_now:
        return Decision(
            action="HOLD",
            message=(
                f"Decision: HOLD {position.ticker}\n"
                f"Last close: {close:.2f}\n"
                f"Why hold: {exit_why}\n"
                f"You can still add today's £{daily:.0f} into {position.ticker}.\n"
                f"(Share count / entry kept private — check Trading 212.)"
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
                f"Last close: {close:.2f}\n"
                f"(Size / £ value kept private — check Trading 212.)"
            ),
            position=position,
            exit_value=value,
            reason=exit_why,
        )

    return Decision(
        action="SELL_AND_ROTATE",
        message=(
            f"Decision: SELL & ROTATE\n"
            f"\n"
            f"1) SELL {position.ticker}\n"
            f"   Exit reason: {exit_why}\n"
            f"   Last close: {close:.2f}\n"
            f"\n"
            f"2) BUY {nxt.ticker} with the full proceeds\n"
            f"   Market ~{nxt.close:.2f}\n"
            f"   Why: {nxt.why} (best 10-day momentum on the watchlist)\n"
            f"\n"
            f"(Share counts / £ amounts kept private — check Trading 212.)"
        ),
        position=position,
        exit_value=value,
        next_ticker=nxt.ticker,
        next_price=nxt.close,
        reason=exit_why,
    )
