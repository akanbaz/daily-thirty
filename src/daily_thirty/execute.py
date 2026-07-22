"""Optional order placement for Trading 212 — DEMO-only, DRY-RUN by default.

This is the one place the tool can send an order, and every guardrail in
`safety.py` sits in front of it:

  * Uses the EXECUTION environment (T212_EXEC_ENV), which defaults to DEMO.
    Read-only sync (T212_ENV) is left completely untouched.
  * dry_run=True by default: the order is built and validated, but nothing is
    sent to the broker.
  * Order value is capped and validated before anything leaves the process.
  * Live placement additionally requires the exact T212_ALLOW_LIVE opt-in.
  * All broker/network errors are caught and returned, never raised as a crash.

The rest of Daily Thirty never imports or calls this. It is not wired into the
GitHub Actions workflow. Placing an order is always a deliberate manual step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from daily_thirty import safety
from daily_thirty.trading212 import DEMO_BASE, LIVE_BASE, _auth

log = logging.getLogger("daily_thirty.execute")


@dataclass
class OrderResult:
    ok: bool
    dry_run: bool
    env: str
    detail: str
    request: dict | None = None


def _exec_base(env: str) -> str:
    return DEMO_BASE if safety.is_demo(env) else LIVE_BASE


def place_market_order(
    t212_ticker: str,
    quantity: float,
    *,
    est_value_gbp: float,
    dry_run: bool = True,
) -> OrderResult:
    """Validate and (optionally) submit a market order. Demo-only by default.

    Args:
        t212_ticker: the Trading 212 instrument ticker, e.g. "AAPL_US_EQ"
                     (NOT the plain "AAPL" symbol).
        quantity:    number of shares (fractional allowed).
        est_value_gbp: your estimate of the order's value, for the size guard.
        dry_run:     when True (default) nothing is sent — the order is only
                     validated and echoed back.
    """
    env = safety.execution_env()

    # --- Guardrails first; if any block, we return cleanly (no exception). ---
    try:
        safety.assert_execution_allowed(env)
        safety.validate_order_value(est_value_gbp)
    except safety.SafetyError as exc:
        log.warning("order blocked: %s", exc)
        return OrderResult(ok=False, dry_run=dry_run, env=env, detail=f"blocked: {exc}")

    if not t212_ticker or quantity <= 0:
        return OrderResult(ok=False, dry_run=dry_run, env=env,
                           detail="need a T212 ticker and a positive quantity")

    payload = {"ticker": t212_ticker.upper(), "quantity": quantity}

    if dry_run:
        log.info("DRY RUN: market %s x%s on %s (nothing sent)", t212_ticker, quantity, env)
        return OrderResult(ok=True, dry_run=True, env=env,
                           detail="dry run — order validated, nothing sent", request=payload)

    # --- Real submission (still demo unless the live opt-in was set). ---
    url = f"{_exec_base(env)}/api/v0/equity/orders/market"
    try:
        with httpx.Client(timeout=30.0, auth=_auth()) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 401:
                return OrderResult(False, False, env, "auth failed (check API key/secret)", payload)
            if resp.status_code == 403:
                return OrderResult(False, False, env,
                                   "forbidden — key needs order scope / not permitted", payload)
            if resp.status_code == 429:
                return OrderResult(False, False, env, "rate-limited (429) — try again later", payload)
            resp.raise_for_status()
            log.info("order submitted on %s: %s x%s", env, t212_ticker, quantity)
            return OrderResult(True, False, env, f"submitted: {resp.json()}", payload)
    except httpx.HTTPError as exc:
        log.error("order submission failed: %s", exc)
        return OrderResult(False, False, env, f"API error: {exc}", payload)
