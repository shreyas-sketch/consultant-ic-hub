# Load test

## What was run

`cd backend && python ../scripts/load_scenarios.py` runs the playbook's three heavy moments inside one process on the in-memory database (mongomock).

| Scenario | Bar | Result | Pass? |
|---|---|---|---|
| 200 clients open client files at once after a bulk send | all load, no errors | 200 OK, 0 failed, 0.79 s | yes |
| 5,000 automation runs due in the same minute | all done within about a minute | 5,000 done, 0 double sends, 178 s | not on this database |
| 300 Daily brief agent runs at 8:00 IST | queue, don't fail | 301 ran, 0 failed, 4.3 s | yes |

## The honest caveat

These numbers are from an in-memory fake of MongoDB in one Python process. They check our own code, not production speed.

- On the 5,000-runs test, 67% of the time was spent inside the fake database itself (profiled). Real MongoDB with indexes is usually much faster for this kind of claim-and-update work, but **this has not been measured**.
- The tick was rewritten to claim runs in batches and run 25 at a time. That took the same test from 504 s to 178 s.
- If real MongoDB still misses the bar: run 2–3 workers (each claims its own runs safely), or raise `TICK_CONCURRENCY` in `app/automations/engine.py`.

## To do before launch: real-database run

1. Make a throwaway Atlas database (same tier as production).
2. Start the app in QA mode on it. Vendors stay fake, database is real:

   ```bash
   cd backend
   export QA_MODE=true QA_DB=mongo MONGO_URL=mongodb+srv://... DB_NAME=loadtest_throwaway
   RUN_JOBS=false uvicorn app.main:app --workers 2 --port 8000
   python -m app.workers
   ```

3. Same three scenarios on the real database: `QA_DB=mongo MONGO_URL=... DB_NAME=loadtest_throwaway python ../scripts/load_scenarios.py`
4. Traffic test: `locust -f scripts/loadtest/locustfile.py --host http://localhost:8000 -u 500 -r 50 -t 10m --headless`
   (4 clients for every consultant, opening files, booking pages and the app.)

Pass bars:

- p95 under 800 ms on consultant screens, under 500 ms on client pages
- zero 5xx errors
- 5,000 due runs finished within 60–90 s
- one ledger row per payment (also covered by tests)

Then delete the throwaway database.
