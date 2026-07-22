from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from daily_thirty.decide import decide
from daily_thirty.state import Position, load_config, load_position, save_position

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


@app.command("decide")
def cmd_decide() -> None:
    """Today's decision: HOLD or SELL & ROTATE (or first buy)."""
    cfg = load_config()
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
    if existing and existing.ticker == ticker:
        total_shares = existing.shares + shares
        avg = (existing.shares * existing.entry_price + shares * fill_price) / total_shares
        pos = Position(ticker=ticker, shares=total_shares, entry_price=avg)
        console.print(
            f"Added to {ticker}. Now {pos.shares:.6f} shares, avg entry {pos.entry_price:.2f}."
        )
    else:
        pos = Position(ticker=ticker, shares=shares, entry_price=fill_price)
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
