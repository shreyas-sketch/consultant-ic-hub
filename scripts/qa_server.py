"""Run the whole app on sample data: no database, no keys, no internet.

    cd backend && python ../scripts/qa_server.py      # http://localhost:8765

- Every outside service is fake. A demo practice is seeded so every screen has data.
- The login code is shown on screen, and 000000 also works.
- POST /api/qa/login {"persona": "owner" | "admin" | "manager" | "member" | "collaborator" | "new" | "staff"}
"""
import os
import sys

os.environ.setdefault("QA_MODE", "true")
os.environ.setdefault("RUN_JOBS", "true")
os.environ.setdefault("APP_URL", "http://localhost:8765")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8765")), log_level="warning")
