from __future__ import annotations

import argparse
from pathlib import Path

from auto_ledger.local_dashboard import serve_dashboard
from auto_ledger.local_ledger_analysis import analyze_local_ledger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local Excel-based ledger analysis and dashboard workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Read files from excel/ and regenerate reports/.")
    analyze_parser.add_argument("--project-root", type=Path, default=Path.cwd())

    serve_parser = subparsers.add_parser("serve", help="Serve the dashboard directory over HTTP.")
    serve_parser.add_argument("--project-root", type=Path, default=Path.cwd())
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=4173)
    serve_parser.add_argument("--open", action="store_true")

    all_parser = subparsers.add_parser("all", help="Regenerate reports and then serve the dashboard.")
    all_parser.add_argument("--project-root", type=Path, default=Path.cwd())
    all_parser.add_argument("--host", default="127.0.0.1")
    all_parser.add_argument("--port", type=int, default=4173)
    all_parser.add_argument("--open", action="store_true")

    return parser.parse_args()


def run_analysis(project_root: Path) -> int:
    outputs = analyze_local_ledger(project_root.resolve())
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "analyze":
        return run_analysis(args.project_root)

    if args.command == "serve":
        return serve_dashboard(args.project_root, host=args.host, port=args.port, open_browser=args.open)

    if args.command == "all":
        run_analysis(args.project_root)
        return serve_dashboard(args.project_root, host=args.host, port=args.port, open_browser=args.open)

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
