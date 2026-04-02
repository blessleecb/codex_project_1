from __future__ import annotations

import webbrowser
import argparse
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local dashboard for the ledger reports.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser.")
    return parser.parse_args()


def serve_dashboard(project_root: Path, host: str = "127.0.0.1", port: int = 4173, open_browser: bool = False) -> int:
    root = project_root.resolve()
    handler = partial(SimpleHTTPRequestHandler, directory=os.fspath(root))
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/dashboard/"
    print(f"Serving dashboard from: {root}")
    print(f"Dashboard URL: {url}")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server.")
    finally:
        server.server_close()
    return 0


def main() -> int:
    args = parse_args()
    return serve_dashboard(args.project_root, host=args.host, port=args.port, open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main())
