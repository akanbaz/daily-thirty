# Daily Thirty — simplest possible design

## What you do each day
1. Put **£30** into **one** stock (or add £30 into the current holding).
2. Next morning, run the tool.
3. It says **HOLD** or **SELL & ROTATE**.
4. If rotate: it shows the **exit value** and the **next stock** to buy with that full amount.
5. After you trade in your broker, tell the tool what you did (`bought` / `sold`).

## What this tool is NOT
No ISA, FX, backtests, schedules, gates, benchmarks, or complex stats.

## Files
| File | Purpose |
|------|---------|
| `config.yaml` | Your watchlist + stop % (default 4%) |
| `position.json` | What you currently hold (ticker, shares, entry) |
| `daily` CLI | `decide` / `bought` / `sold` / `status` |

## Rules (as coded)
**Candidate must:**
- Close > SMA50 and close > SMA200 (uptrend)
- 10-day return > 0 (momentum)
- 5-day return < +15% (not overextended)

**HOLD** unless:
- Close ≤ entry × (1 − 4%), or
- Close < SMA20

**If rotating:** pick the eligible stock with the **highest 10-day return** (not the one you just sold, if possible).

## Daily flow
```
daily decide          → read decision
… trade in broker …
daily bought AAPL 0.12 185.50   → after a buy
daily sold 187.20               → after a sell (then decide again for next buy)
```
