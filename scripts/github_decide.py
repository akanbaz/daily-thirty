#!/usr/bin/env python3
"""Run decide + publish static site (used by GitHub Actions)."""

from __future__ import annotations

import os
from pathlib import Path

from daily_thirty.decide import decide
from daily_thirty.publish import write_outputs
from daily_thirty.state import load_config, load_position


def main() -> None:
    root = Path.cwd()
    cfg = load_config(root / "config.yaml")
    pos = load_position()
    result = decide(cfg, pos)
    repo = os.environ.get("GITHUB_REPOSITORY", "akanbaz/daily-thirty")
    repo_url = f"https://github.com/{repo}"
    site = write_outputs(result, pos, root=root, repo_url=repo_url)
    print(result.message)
    print(f"\nWrote {site / 'index.html'}")
    print(f"Action: {result.action}")


if __name__ == "__main__":
    main()
