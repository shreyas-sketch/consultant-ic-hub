"""Worker process: runs the scheduled jobs (automations, agents, reminders).

Same image as web, different start command:  python worker.py
Set RUN_JOBS=false on web processes and run one or more workers.
"""
import asyncio

from app import main as server  # noqa: F401  (registers every action)
from app.db import ensure_indexes
from app.workers.jobs import start_scheduler


async def main():
    await ensure_indexes()
    start_scheduler()
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
