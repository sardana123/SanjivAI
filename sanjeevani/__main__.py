"""CLI:  python -m sanjeevani serve | demo"""
from __future__ import annotations

import argparse
import logging

from . import __version__
from .app import build_companion
from .config import Settings
from .demo import seed
from .server import Ticker, create_server
from .timeutil import now_local


def main() -> None:
    ap = argparse.ArgumentParser(prog="sanjeevani", description="Voice-first medication companion")
    ap.add_argument("command", choices=["serve", "demo"], nargs="?", default="serve")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--db", help="SQLite path (demo defaults to demo.db)")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings.from_env()
    overrides = {k: v for k, v in {"host": a.host, "port": a.port, "db_path": a.db}.items() if v}
    if a.command == "demo" and not a.db:
        overrides["db_path"] = "demo.db"
    s = Settings(**{**s.__dict__, **overrides})

    companion = build_companion(s)
    if a.command == "demo" and not companion.list_patients():
        seed(companion, now_local())
        logging.info("Seeded demo patient with 14 days of history in %s", s.db_path)

    ticker = Ticker(companion, s.tick_seconds)
    ticker.start()
    server = create_server(companion, s)
    logging.info("Sanjeevani %s running at http://%s:%d  (LLM: %s, webhook: %s, auth: %s)", __version__, s.host,
                 s.port, "on" if companion.llm.enabled else "off", "on" if s.webhook_url else "off",
                 "token" if s.api_token else "open")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ticker.stop()
        server.server_close()


if __name__ == "__main__":
    main()
