"""Worker process: runs the scheduled jobs (automations, agents, reminders).

Same image as web, different start command:  python worker.py
Set RUN_JOBS=false on web processes and run one or more workers.
"""
import asyncio

import server  # noqa: F401  (registers every action)
from core.db import ensure_indexes
from jobs import start_scheduler


async def main():
    await ensure_indexes()
    start_scheduler()
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
