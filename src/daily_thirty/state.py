from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


ROOT = Path.cwd()


@dataclass
class Position:
    ticker: str
    shares: float
    entry_price: float

    @property
    def cost(self) -> float:
        return self.shares * self.entry_price


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or ROOT / "config.yaml"
    return yaml.safe_load(cfg_path.read_text()) or {}


def position_path() -> Path:
    return ROOT / "position.json"


def load_position() -> Position | None:
    path = position_path()
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    if not raw or not raw.get("ticker"):
        return None
    return Position(
        ticker=str(raw["ticker"]).upper(),
        shares=float(raw["shares"]),
        entry_price=float(raw["entry_price"]),
    )


def save_position(pos: Position | None) -> None:
    path = position_path()
    if pos is None:
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps(asdict(pos), indent=2) + "\n")
