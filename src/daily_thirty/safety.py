"""Safety guardrails for anything that could touch the broker with orders.

Daily Thirty is an analysis-only tool. This module exists so that *if* an order
is ever placed, it cannot:
  * go to the LIVE (real-money) account by accident,
  * exceed a small size cap, or
  * fire without an explicit, deliberate action.

Read-only position sync (see trading212.py) is unaffected by anything here.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("daily_thirty")

# Hard size caps in pounds. Orders outside this range are refused outright.
# Deliberately small — this is a £30/day tool, not a desk. Override the max
# with T212_MAX_ORDER_GBP if you really need to, but it can never be unbounded.
MIN_ORDER_GBP = 1.0
DEFAULT_MAX_ORDER_GBP = 60.0
HARD_CEILING_GBP = 500.0  # even an override cannot exceed this

# The exact string a user must set in T212_ALLOW_LIVE to permit live orders.
# Anything else (including "true"/"yes"/"1") keeps execution on demo.
LIVE_OPT_IN = "I_UNDERSTAND_THIS_IS_REAL_MONEY"

DEMO_ENVS = {"demo", "practice", "paper"}


class SafetyError(RuntimeError):
    """Raised when a guardrail blocks an action. Always caught, never a crash."""


def setup_logging(level: int = logging.INFO) -> None:
    """Configure structured logging once (no-op if already configured)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


def execution_env() -> str:
    """Environment used for ORDER PLACEMENT — defaults to 'demo'.

    This is intentionally separate from T212_ENV (used by read-only sync) so
    your existing live *read* sync keeps working while orders stay on demo.
    """
    return (os.environ.get("T212_EXEC_ENV") or "demo").strip().lower()


def is_demo(env: str) -> bool:
    return env.strip().lower() in DEMO_ENVS


def live_execution_opted_in() -> bool:
    """True only if the user set the exact, deliberate opt-in string."""
    return os.environ.get("T212_ALLOW_LIVE", "").strip() == LIVE_OPT_IN


def max_order_gbp() -> float:
    """Configured max order size, clamped to the hard ceiling."""
    raw = os.environ.get("T212_MAX_ORDER_GBP")
    try:
        value = float(raw) if raw else DEFAULT_MAX_ORDER_GBP
    except ValueError:
        value = DEFAULT_MAX_ORDER_GBP
    return min(value, HARD_CEILING_GBP)


def assert_execution_allowed(env: str) -> None:
    """Block order placement unless it targets demo (or an explicit live opt-in)."""
    if is_demo(env):
        return
    if not live_execution_opted_in():
        raise SafetyError(
            f"Refusing to place orders against '{env}'. Execution is demo-only. "
            f"Use T212_EXEC_ENV=demo. Live orders require the explicit opt-in "
            f"T212_ALLOW_LIVE={LIVE_OPT_IN} (not recommended)."
        )
    log.warning("LIVE execution opt-in is set — real-money orders are ENABLED.")


def validate_order_value(value_gbp: float) -> None:
    """Reject non-positive, too-small, or over-cap order values."""
    cap = max_order_gbp()
    if not isinstance(value_gbp, (int, float)) or value_gbp != value_gbp:  # NaN guard
        raise SafetyError("Order value is not a number.")
    if value_gbp <= 0:
        raise SafetyError("Order value must be positive.")
    if value_gbp < MIN_ORDER_GBP:
        raise SafetyError(f"Order £{value_gbp:.2f} is below the minimum £{MIN_ORDER_GBP:.2f}.")
    if value_gbp > cap:
        raise SafetyError(f"Order £{value_gbp:.2f} exceeds the cap £{cap:.2f}.")
