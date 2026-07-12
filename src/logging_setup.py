"""Central logging configuration.

Call setup_logging() ONCE at process start. The entry points already do this:
  - main.py   (the CLI, and imported by server.py — so it covers both)
  - server.py (the web server's __main__)

Every other module does NOT import a shared logger object. It just calls:

    import logging
    log = logging.getLogger("starsage.<module>")   # e.g. "starsage.llm"

and uses log.info(...) / log.warning(...) / log.error(..., exc_info=True).
Because all "starsage.*" loggers propagate to the root handler configured here,
their output goes to stdout — which Docker captures, so `docker compose logs app`
(or `docker compose logs -f app`) shows everything.

Level is controlled by env: STARSAGE_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR (default INFO).
"""
import logging
import os
import sys

_CONFIGURED = False


def setup_logging(force=False):
    """Idempotent. Sends all logs to stdout; keeps our own namespace verbose while
    leaving noisy third-party libraries at WARNING."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level_name = os.environ.get("STARSAGE_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger()
    root.handlers[:] = [handler]          # replace, so repeat calls don't duplicate lines
    root.setLevel(logging.WARNING)        # third-party libs stay quiet
    logging.getLogger("starsage").setLevel(level)   # our modules are verbose

    _CONFIGURED = True
    logging.getLogger("starsage.logging").info("logging configured (level=%s)", level_name)
