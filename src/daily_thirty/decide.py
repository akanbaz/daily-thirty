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
    stale: bool = False


@dataclass
class Scan:
    """Result of scanning the watchlist, including how trustworthy it was."""
    best: Candidate | None
    notes: list[str]
    checked: int  # names we evaluated with usable prices
    failed: int   # names whose prices could not be loaded


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
) -> Scan:
    """Scan the watchlist for the best buy, tracking data failures."""
    import time

    best: Candidate | None = None
    notes: list[str] = []
    checked = 0
    failed = 0
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
            failed += 1
            continue
        row = _enriched_last(df)
        if row is None:
            notes.append(f"{ticker}: no price data")
            failed += 1
            continue
        checked += 1
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
            stale=bool(df.attrs.get("stale", False)),
        )
        notes.append(f"{ticker}: eligible ({why})")
        if best is None or cand.ret_10 > best.ret_10:
            best = cand
    return Scan(best=best, notes=notes, checked=checked, failed=failed)


def _scan_warning(scan: Scan) -> str:
    """Caution text when the watchlist scan couldn't be fully trusted."""
    lines: list[str] = []
    if scan.failed:
        total = scan.checked + scan.failed
        lines.append(
            f"Heads-up: only {scan.checked} of {total} names loaded "
            f"({scan.failed} failed). This pick may not be the true best — "
            f"re-run later before acting."
        )
    if scan.best is not None and scan.best.stale:
        lines.append(
            "Heads-up: this price is from cached data (live fetch failed); "
            "treat it as approximate."
        )
    return ("\n\n" + "\n".join(lines)) if lines else ""


def _price_note(df: pd.DataFrame) -> str:
    """Caution text when the held stock's price is stale cache."""
    if not df.attrs.get("stale"):
        return ""
    days = float(df.attrs.get("age_hours", 0.0)) / 24
    return (
        f"\n\nNote: live prices didn't load — using cached data about "
        f"{days:.0f} day(s) old. Re-run later to confirm before you act."
    )


def decide(cfg: dict, position: Position | None) -> Decision:
    stop_pct = float(cfg.get("stop_pct", 0.04))
    watchlist = [str(t).upper() for t in cfg.get("watchlist", [])]
    daily = float(cfg.get("daily_pounds", 30))

    if position is None:
        scan = pick_next(watchlist)
        if scan.best is None:
            detail = "\n".join(f"  - {n}" for n in scan.notes[-8:]) or "  (no details)"
            # If nothing qualified only because prices failed to load, say so.
            if scan.checked == 0 and scan.failed:
                headline = "No position yet, and no prices could be loaded today."
            else:
                headline = "No position yet, and no watchlist name qualifies today."
            return Decision(
                action="BUY_FIRST",
                message=(
                    f"{headline}\n"
                    f"Add cash (£{daily:.0f}) and wait, or edit config.yaml watchlist.\n"
                    f"Checked:\n{detail}"
                ),
            )
        return Decision(
            action="BUY_FIRST",
            message=(
                f"No position yet.\n"
                f"Buy £{daily:.0f} of {scan.best.ticker} (market ~{scan.best.close:.2f}).\n"
                f"Why: {scan.best.why}"
                f"{_scan_warning(scan)}"
            ),
            next_ticker=scan.best.ticker,
            next_price=scan.best.close,
            reason=scan.best.why,
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
                f"You can still add today's £{daily:.0f} into {position.ticker}."
                f"{_price_note(df)}"
            ),
            position=position,
            current_value=value,
            reason=exit_why,
        )

    # SELL & ROTATE
    scan = pick_next(watchlist, exclude=position.ticker)
    if scan.best is None:
        # Distinguish "nothing qualifies" from "couldn't check the watchlist".
        if scan.checked == 0 and scan.failed:
            replacement = (
                "Could not load any replacement candidates (all fetches failed).\n"
                "Re-run before rotating — don't sell into a blind spot."
            )
        else:
            replacement = "No replacement qualifies right now — you would sell to cash."
        return Decision(
            action="SELL_AND_ROTATE",
            message=(
                f"Decision: SELL {position.ticker}\n"
                f"Exit reason: {exit_why}\n"
                f"Last close: {close:.2f}\n"
                f"{replacement}"
                f"{_price_note(df)}"
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
            f"2) BUY {scan.best.ticker} with the full proceeds\n"
            f"   Market ~{scan.best.close:.2f}\n"
            f"   Why: {scan.best.why} (best 10-day momentum on the watchlist)"
            f"{_price_note(df)}"
            f"{_scan_warning(scan)}"
        ),
        position=position,
        exit_value=value,
        next_ticker=scan.best.ticker,
        next_price=scan.best.close,
        reason=exit_why,
    )
