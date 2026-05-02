"""CLI for serving the packaged ApexAI static telemetry UI."""

from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    """Serve the built static UI through ``uv run apexai-ui``."""

    args = _build_parser().parse_args(argv)
    static_dir = Path(args.directory).resolve() if args.directory else _default_static_dir()

    if not (static_dir / "index.html").exists():
        raise SystemExit(
            f"Could not find built UI assets at {static_dir}. "
            "Run `make ui-build` first."
        )

    handler = partial(SimpleHTTPRequestHandler, directory=static_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url_host = "localhost" if args.host in {"0.0.0.0", "::"} else args.host

    print(f"Serving ApexAI UI from {static_dir}")
    print(f"Open http://{url_host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ApexAI UI server")
    finally:
        server.server_close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the packaged ApexAI static telemetry UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the static UI server")
    parser.add_argument("--port", default=3000, type=int, help="Port for the static UI server")
    parser.add_argument(
        "--directory",
        default=None,
        help="Static UI directory to serve; defaults to the packaged ApexAI UI assets",
    )
    return parser


def _default_static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


if __name__ == "__main__":
    main(sys.argv[1:])
