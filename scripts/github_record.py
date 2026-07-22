#!/usr/bin/env python3
"""Update position.json from workflow_dispatch inputs, then re-publish."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from daily_thirty.decide import decide
from daily_thirty.publish import write_outputs
from daily_thirty.state import Position, load_config, load_position, save_position


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["bought", "sold"])
    p.add_argument("--ticker", default="")
    p.add_argument("--shares", type=float, default=0.0)
    p.add_argument("--price", type=float, required=True)
    args = p.parse_args()

    root = Path.cwd()
    if args.action == "sold":
        pos = load_position()
        if pos is None:
            raise SystemExit("No position to sell.")
        print(f"Sold {pos.ticker} (size private) @ {args.price}")
        save_position(None)
    else:
        ticker = args.ticker.upper().strip()
        if not ticker or args.shares <= 0 or args.price <= 0:
            raise SystemExit("bought requires --ticker --shares --price")
        existing = load_position()
        if existing and existing.ticker == ticker:
            total = existing.shares + args.shares
            avg = (existing.shares * existing.entry_price + args.shares * args.price) / total
            pos = Position(ticker=ticker, shares=total, entry_price=avg)
        else:
            pos = Position(ticker=ticker, shares=args.shares, entry_price=args.price)
        save_position(pos)
        print(f"Saved {pos.ticker} (size private)")

    cfg = load_config(root / "config.yaml")
    pos = load_position()
    result = decide(cfg, pos)
    repo = os.environ.get("GITHUB_REPOSITORY", "akanbaz/daily-thirty")
    write_outputs(result, pos, root=root, repo_url=f"https://github.com/{repo}")
    print(result.message)


if __name__ == "__main__":
    main()
