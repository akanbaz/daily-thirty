from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from daily_thirty.decide import decide
from daily_thirty.state import load_config, load_position, record_buy, save_position
from daily_thirty.trading212 import credentials_configured, list_holdings, sync_position

app = typer.Typer(
    name="daily",
    help="£30/day single-stock tool: HOLD or SELL & ROTATE.",
    no_args_is_help=True,
)
console = Console()


@app.command("status")
def cmd_status() -> None:
    """Show the saved position."""
    pos = load_position()
    if pos is None:
        console.print("No position saved. Run: [bold]daily decide[/bold]")
        return
    console.print(
        f"Holding {pos.ticker}\n"
        f"Shares: {pos.shares:.6f}\n"
        f"Entry: {pos.entry_price:.2f}\n"
        f"Cost: £{pos.cost:.2f}"
    )


@app.command("sync")
def cmd_sync() -> None:
    """Read-only: pull your Trading 212 position into position.json (no orders)."""
    if not credentials_configured():
        console.print(
            "Set [bold]T212_API_KEY[/bold] and [bold]T212_API_SECRET[/bold] "
            "(optional [bold]T212_ENV=live|demo[/bold]).\n"
            "Create keys in Trading 212 → Settings → API (Beta). Use read-only scopes."
        )
        raise typer.Exit(1)
    cfg = load_config()
    watchlist = [str(t).upper() for t in cfg.get("watchlist", [])]
    result = sync_position(watchlist=watchlist)
    console.print(result.message)
    if result.position is None:
        console.print("position.json cleared (flat / no matching holding).")
    else:
        console.print("Saved to position.json. Run [bold]daily decide[/bold] next.")


@app.command("holdings")
def cmd_holdings() -> None:
    """Read-only: list ALL open Trading 212 positions (not just the tracked one)."""
    if not credentials_configured():
        console.print(
            "Set [bold]T212_API_KEY[/bold] and [bold]T212_API_SECRET[/bold] first "
            "(Trading 212 → Settings → API (Beta), read-only)."
        )
        raise typer.Exit(1)
    rows = list_holdings()
    if not rows:
        console.print("No open positions.")
        return
    console.print(f"You hold [bold]{len(rows)}[/bold] position(s):")
    for symbol, qty, avg, value in rows:
        val = f" · value ~{value:.2f}" if value else ""
        console.print(f"  {symbol}: {qty:.6f} shares @ avg {avg:.2f}{val}")
    console.print(
        "\n(The daily decision tracks the largest of these that is on your watchlist.)"
    )


@app.command("decide")
def cmd_decide(
    sync: bool = typer.Option(
        False,
        "--sync",
        help="Pull Trading 212 position first (needs T212_API_KEY/SECRET).",
    ),
) -> None:
    """Today's decision: HOLD or SELL & ROTATE (or first buy)."""
    cfg = load_config()
    if sync:
        if not credentials_configured():
            console.print("Missing T212_API_KEY / T212_API_SECRET for --sync.")
            raise typer.Exit(1)
        watchlist = [str(t).upper() for t in cfg.get("watchlist", [])]
        synced = sync_position(watchlist=watchlist)
        console.print(synced.message)
    pos = load_position()
    result = decide(cfg, pos)
    console.print(result.message)


@app.command("bought")
def cmd_bought(
    ticker: str = typer.Argument(..., help="Ticker you bought"),
    shares: float = typer.Argument(..., help="Shares bought (fractional OK)"),
    fill_price: float = typer.Argument(..., help="Price paid per share"),
) -> None:
    """Record a buy after you executed it in the broker."""
    ticker = ticker.upper()
    existing = load_position()
    pos = record_buy(existing, ticker, shares, fill_price)
    if existing and existing.ticker == ticker:
        console.print(
            f"Added to {ticker}. Now {pos.shares:.6f} shares, avg entry {pos.entry_price:.2f}."
        )
    else:
        console.print(
            f"Saved position: {pos.shares:.6f} × {pos.ticker} @ {pos.entry_price:.2f}"
        )
    save_position(pos)


@app.command("sold")
def cmd_sold(
    fill_price: float = typer.Argument(..., help="Price you sold at"),
) -> None:
    """Record a full sell. Clears the position."""
    pos = load_position()
    if pos is None:
        console.print("No position to sell.")
        raise typer.Exit(1)
    proceeds = pos.shares * fill_price
    console.print(
        f"Sold {pos.shares:.6f} × {pos.ticker} @ {fill_price:.2f} → £{proceeds:.2f}.\n"
        f"Position cleared. Run [bold]daily decide[/bold] for the next buy if needed."
    )
    save_position(None)


@app.command("reset")
def cmd_reset() -> None:
    """Clear saved position."""
    save_position(None)
    console.print("Position cleared.")


@app.command("ui")
def cmd_ui(
    port: int = typer.Option(8501, help="Port"),
    host: str = typer.Option("127.0.0.1", help="Bind address"),
) -> None:
    """Open the simple web UI in your browser."""
    import sys
    from streamlit.web import cli as stcli

    app_path = Path(__file__).resolve().parent / "ui.py"
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
        "--server.address",
        host,
        "--browser.gatherUsageStats",
        "false",
    ]
    console.print(f"Opening http://{host}:{port}")
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    app()
