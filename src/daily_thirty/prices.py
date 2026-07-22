from __future__ import annotations

import time
from pathlib import Path

import httpx
import pandas as pd

CACHE_DIR = Path.cwd() / "cache"


def fetch_daily(ticker: str, years: int = 2, *, force: bool = False) -> pd.DataFrame:
    """Yahoo chart daily OHLCV, with a small on-disk cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{ticker.upper()}.parquet"
    if path.exists() and not force:
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours < 12:
            return pd.read_parquet(path)

    end = int(time.time())
    start = end - years * 365 * 24 * 3600
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker.upper()}"
    params = {"interval": "1d", "period1": start, "period2": end}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
        try:
            client.get("https://fc.yahoo.com", timeout=5.0)
        except Exception:
            pass
        resp = client.get(url, params=params)
        if resp.status_code == 429:
            time.sleep(3.0)
            resp = client.get(url, params=params)
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
        df.to_parquet(path)
        return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sma20"] = out["close"].rolling(20, min_periods=20).mean()
    out["sma50"] = out["close"].rolling(50, min_periods=50).mean()
    out["sma200"] = out["close"].rolling(200, min_periods=200).mean()
    out["ret_10"] = out["close"] / out["close"].shift(10) - 1.0
    out["ret_5"] = out["close"] / out["close"].shift(5) - 1.0
    return out
