"""Staging load test. Run against a real MongoDB, never production.

Start the app in QA mode on a real, throwaway database (fake vendors, real DB):

    cd backend
    QA_MODE=true QA_DB=mongo MONGO_URL=mongodb+srv://... DB_NAME=loadtest_throwaway \\
    RUN_JOBS=false uvicorn server:app --workers 2 --port 8000
    QA_MODE=true QA_DB=mongo MONGO_URL=... DB_NAME=loadtest_throwaway python worker.py

Then:

    pip install locust
    locust -f scripts/loadtest/locustfile.py --host http://localhost:8000 -u 500 -r 50 -t 10m --headless

Pass bars (from the playbook):
  - p95 under 800 ms for consultant screens, under 500 ms for client pages
  - zero 5xx
  - one ledger row per payment even when two confirms race (checked in tests too)
"""
import random

from locust import HttpUser, between, task

PERSONAS = ["owner", "admin", "manager", "member"]


class Consultant(HttpUser):
    """A consultant moving around the app."""
    weight = 1
    wait_time = between(2, 6)

    def on_start(self):
        self.client.post("/api/qa/login", json={"persona": random.choice(PERSONAS)})
        self.projects = []
        r = self.client.post("/api/a/projects.search", json={}, name="projects.search")
        if r.ok:
            self.projects = [p["id"] for p in r.json().get("items", [])][:20]

    def a(self, name, body=None):
        return self.client.post(f"/api/a/{name}", json=body or {}, name=name)

    @task(5)
    def home(self):
        self.a("home.get")

    @task(4)
    def board(self):
        self.a("projects.search", {})

    @task(4)
    def project(self):
        if self.projects:
            self.a("projects.get", {"id": random.choice(self.projects)})

    @task(2)
    def inbox(self):
        self.a("inbox.list", {})

    @task(2)
    def approvals(self):
        self.a("approvals.list", {})

    @task(1)
    def payments(self):
        self.a("payments.list_due", {})

    @task(1)
    def reports(self):
        self.a("reports.summary", {})

    @task(1)
    def search(self):
        self.a("search.all", {"q": random.choice(["an", "ra", "pri", "co"])})


class Client(HttpUser):
    """A client opening links from emails: lead form, booking page, a client file."""
    weight = 4
    wait_time = between(1, 4)

    def on_start(self):
        self.slug = "mehta-growth"
        r = self.client.get(f"/api/public/brand/{self.slug}", name="public.brand")
        self.ok = r.ok
        self.file_tokens = []
        # Consultant-side lookup of a few sent files to open as a client.
        s = self.client.post("/api/qa/login", json={"persona": "owner"})
        if s.ok:
            r = self.client.post("/api/a/files.list", json={}, name="files.list")
            if r.ok:
                self.file_tokens = [f["token"] for f in r.json() if f.get("token") and f.get("sent_at")][:10]
        self.client.cookies.clear()

    @task(4)
    def open_file(self):
        if self.file_tokens:
            self.client.get(f"/api/public/f/{random.choice(self.file_tokens)}", name="public.file")

    @task(2)
    def booking_page(self):
        self.client.get(f"/api/public/{self.slug}/book/discovery-call", name="public.booking")

    @task(1)
    def screens(self):
        self.client.get(f"/c/{self.slug}/book/discovery-call", name="client.html")
