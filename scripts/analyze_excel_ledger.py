from __future__ import annotations

from pathlib import Path

from auto_ledger.local_cli import run_analysis


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    return run_analysis(root)


if __name__ == "__main__":
    raise SystemExit(main())
