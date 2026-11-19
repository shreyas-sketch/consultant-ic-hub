"""Worker process: runs the scheduled jobs (automations, agents, reminders, money).

Same image as web, different start command:

    python -m app.workers

Run one or more workers. Every job takes a database lease, so two workers never
run the same job at once; adding workers adds headroom, never duplicates.
SIGTERM (Railway redeploy/scale-down) stops the scheduler and lets running jobs
finish their current step before the process exits.
"""
import asyncio
import logging
import signal

from app import __version__
from app.core import settings

log = logging.getLogger("app.worker")


async def main():
    from app.main import startup
    await startup()
    from app.workers.health import serve_health
    from app.workers.jobs import start_scheduler
    sched = start_scheduler()
    health = await serve_health()
    log.info("worker started", extra={"fields": {"version": __version__, "env": settings.ENVIRONMENT}})

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover (Windows)
            pass
    await stop.wait()
    log.info("worker stopping")
    sched.shutdown(wait=True)
    if health:
        health.close()
    from app.db import close
    close()


if __name__ == "__main__":
    asyncio.run(main())
