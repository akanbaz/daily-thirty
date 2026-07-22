from __future__ import annotations

import time
from io import StringIO
from pathlib import Path

import httpx
import pandas as pd

CACHE_DIR = Path.cwd() / "cache"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# Prefer cache this long without even trying the network (GHA IPs get Yahoo 429s).
FRESH_HOURS = 20
# After that, try one refresh; if it fails, still use cache this long.
STALE_OK_HOURS = 24 * 14


def fetch_daily(ticker: str, years: int = 2, *, force: bool = False) -> pd.DataFrame:
    """Daily OHLCV with cache. Stooq → Yahoo once; falls back to stale cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{ticker.upper()}.parquet"

    cached: pd.DataFrame | None = None
    age_hours = float("inf")
    if path.exists():
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        cached = pd.read_parquet(path)
        if not force and age_hours < FRESH_HOURS and not cached.empty:
            return _tag(cached, stale=False, age_hours=age_hours)

    last_err: Exception | None = None
    try:
        df = _fetch_stooq(ticker)
        if not df.empty:
            df.to_parquet(path)
            return _tag(df, stale=False, age_hours=0.0)
    except Exception as exc:  # noqa: BLE001
        last_err = exc

    try:
        df = _fetch_yahoo(ticker, years=years)
        if not df.empty:
            df.to_parquet(path)
            return _tag(df, stale=False, age_hours=0.0)
    except Exception as exc:  # noqa: BLE001
        last_err = exc

    # Live fetch failed — fall back to cache, but mark it stale so callers can warn.
    if cached is not None and not cached.empty and age_hours < STALE_OK_HOURS:
        return _tag(cached, stale=True, age_hours=age_hours)
    if last_err:
        raise last_err
    return pd.DataFrame()


def _tag(df: pd.DataFrame, *, stale: bool, age_hours: float) -> pd.DataFrame:
    """Attach freshness metadata so the decision layer can flag stale prices."""
    df.attrs["stale"] = stale
    df.attrs["age_hours"] = age_hours
    return df


def _fetch_stooq(ticker: str) -> pd.DataFrame:
    symbol = f"{ticker.lower()}.us"
    url = "https://stooq.com/q/d/l/"
    with httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        resp = client.get(url, params={"s": symbol, "i": "d"})
        text = resp.text.strip()
        if not text or text.lower().startswith("<!doctype") or text.lower().startswith("<html"):
            raise RuntimeError("Stooq returned HTML/challenge")
        if text.lower().startswith("access denied") or "No data" in text:
            raise RuntimeError("Stooq no data / denied")
        df = pd.read_csv(StringIO(text))
        if df.empty or "Date" not in df.columns:
            return pd.DataFrame()
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        df.columns = [c.strip().lower() for c in df.columns]
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        out = df[keep].astype(float)
        out["open"] = out["open"].fillna(out["close"])
        return out


def _fetch_yahoo(ticker: str, years: int = 2) -> pd.DataFrame:
    end = int(time.time())
    start = end - years * 365 * 24 * 3600
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    params = {"interval": "1d", "period1": start, "period2": end}
    with httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": UA}) as client:
        resp = client.get(url, params=params)
        if resp.status_code == 429:
            raise RuntimeError("Yahoo rate-limited (429)")
        resp.raise_for_status()
        result = resp.json().get("chart", {}).get("result")
        if not result:
            return pd.DataFrame()
        r0 = result[0]
        ts = r0.get("timestamp") or []
        q = (r0.get("indicators") or {}).get("quote") or [{}]
        q0 = q[0]
        if not ts:
            return pd.DataFrame()
        df = pd.DataFrame(
            {
                "open": q0.get("open"),
                "high": q0.get("high"),
                "low": q0.get("low"),
                "close": q0.get("close"),
                "volume": q0.get("volume"),
            },
            index=pd.to_datetime(ts, unit="s").tz_localize(None).normalize(),
        )
        df = df.dropna(subset=["close"]).sort_index()
        df["open"] = df["open"].fillna(df["close"])
        return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sma20"] = out["close"].rolling(20, min_periods=20).mean()
    out["sma50"] = out["close"].rolling(50, min_periods=50).mean()
    out["sma200"] = out["close"].rolling(200, min_periods=200).mean()
    out["ret_10"] = out["close"] / out["close"].shift(10) - 1.0
    out["ret_5"] = out["close"] / out["close"].shift(5) - 1.0
    return out
