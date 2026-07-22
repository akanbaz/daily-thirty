# Daily Thirty

A **very simple** £30/day single-stock helper — with a small web UI.

Each day it answers: **HOLD** or **SELL & ROTATE**?

This is **not** the StockAnalysis research app (no ISA, FX, backtests, schedules, or gates).

## Setup

```bash
cd ~/Projects/daily-thirty
uv sync
```

## Use the UI (recommended)

```bash
cd ~/Projects/daily-thirty
uv run daily ui
```

Open **http://127.0.0.1:8501**

1. Click **Get today's decision**
2. Trade in your broker
3. Record the buy or sell on the same page

## Or use the terminal

```bash
uv run daily decide
uv run daily bought AAPL 0.15 190.20
uv run daily sold 188.50
uv run daily status
```

## Rules

**Buy candidates** must have:
- Price > SMA50 and > SMA200
- Positive 10-day momentum
- Not up ≥ 15% in the last 5 days

**HOLD** unless:
- Price is ≥ 4% below your entry, or
- Price closes below SMA20

On rotate, it picks the eligible watchlist name with the strongest 10-day momentum.

Edit the watchlist in `config.yaml`.

## Design

See [DESIGN.md](DESIGN.md).
