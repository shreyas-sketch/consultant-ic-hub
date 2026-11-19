"""Deploy step: build indexes and run pending migrations, then exit.

    python -m app.db.migrate

On Railway this is the web service's pre-deploy command, so a bad migration
stops the deploy before any new code takes traffic.
"""
import asyncio
import logging
import sys

from app.core import settings
from app.core.logging import setup_logging


async def main() -> int:
    setup_logging()
    log = logging.getLogger("app.db.migrate")
    settings.validate()
    from app import domain
    from app.db import close, ensure_indexes, ping
    from app.db.migrations import migrate
    domain.load()
    log.info("database reachable in %sms", await ping())
    log.info("indexes ensured: %s", await ensure_indexes())
    applied = await migrate()
    log.info("migrations applied: %s", applied or "none pending")
    close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
