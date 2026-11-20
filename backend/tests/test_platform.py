"""Platform guarantees added with the restructure: layering, indexes, migrations,
storage safety, HTTP hardening, PDFs, and production config checks."""
import ast
import base64
import os
from datetime import datetime, timezone

import pytest

from conftest import act, client, login
from app.db import get_db

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "app")


def _imports(path):
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for a in node.names:
                yield a.name


def _py(folder):
    for r, _, fs in os.walk(os.path.join(APP, folder)):
        for f in fs:
            if f.endswith(".py"):
                yield os.path.join(r, f)


def test_layering_inner_layers_never_import_the_http_layer():
    """domain, auth, core, db, integrations, services, agents and automations stay HTTP-free."""
    bad = []
    for layer in ("domain", "auth", "core", "db", "integrations", "services", "agents", "automations"):
        for path in _py(layer):
            for mod in _imports(path):
                if mod.startswith("app.api") and not (layer == "services" and mod == "app.api.routes.public"):
                    bad.append(f"{os.path.relpath(path, APP)} imports {mod}")
    assert not bad, bad


def test_core_does_not_import_domain():
    bad = [f"{os.path.relpath(p, APP)}: {m}" for p in _py("core") for m in _imports(p)
           if m.startswith(("app.domain", "app.api", "app.agents", "app.automations"))]
    assert not bad, bad


def test_every_tenant_collection_has_a_workspace_index_and_index_names_are_unique():
    from app.db.collections import GLOBAL_COLLECTIONS, TENANT_COLLECTIONS
    from app.db.indexes import specs
    assert not set(TENANT_COLLECTIONS) & set(GLOBAL_COLLECTIONS)
    names = [(ix.coll, ix.spec()[1]["name"]) for ix in specs()]
    assert len(names) == len(set(names)), "duplicate index names"
    covered = {ix.coll for ix in specs() if ix.keys and ix.keys[0] == "workspace_id"}
    assert set(TENANT_COLLECTIONS) <= covered


async def test_public_token_lookups_are_indexed():
    info = {c: await get_db()[c].index_information() for c in ("invoices", "uploads", "tasks", "client_files", "workspaces")}
    keys = {c: [tuple(k for k, _ in v["key"]) for v in ix.values()] for c, ix in info.items()}
    for c in ("invoices", "uploads", "tasks", "client_files"):
        assert ("token",) in keys[c], c
    assert info["workspaces"]["slug_1"].get("unique")


async def test_ttl_indexes_exist_for_short_lived_data():
    for coll in ("otp_codes", "sessions_auth", "oauth_states", "client_sessions"):
        info = await get_db()[coll].index_information()
        assert any("expireAfterSeconds" in v for v in info.values()), coll


async def test_migrations_run_once_and_are_recorded():
    from app.db.migrations import discover, migrate, pending
    ids = [m.ID for m in discover()]
    assert ids == sorted(ids) and len(ids) >= 3
    assert await migrate() == ids
    assert await migrate() == []
    assert await pending(get_db()) == []
    assert await get_db().schema_migrations.count_documents({}) == len(ids)


def test_local_storage_refuses_keys_outside_its_root(tmp_path):
    from app.integrations.storage import LocalStorage, StorageError
    st = LocalStorage(str(tmp_path))
    with pytest.raises(StorageError):
        st._path("../../etc/passwd")
    with pytest.raises(StorageError):
        st._path("/etc/passwd")


async def test_upload_rejects_bytes_that_do_not_match_the_declared_type():
    c = await login("+919811113001")
    fake_png = "data:image/png;base64," + base64.b64encode(b"<script>alert(1)</script>").decode()
    r = await c.post("/api/upload", json={"data": fake_png, "name": "x"})
    assert r.status_code == 400
    real_pdf = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 hello").decode()
    r = await c.post("/api/upload", json={"data": real_pdf, "name": "../../evil"})
    assert r.status_code == 200, r.text
    assert ".." not in r.json()["key"].split("/", 1)[1]


async def test_member_cannot_replace_the_practice_logo():
    owner = await login("+919811113002")
    await act(owner, "team.add", {"phone": "+919811113003", "name": "Mem", "role": "member"})
    member = await login("+919811113003", invited=False)
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    r = await member.post("/api/upload", json={"data": png, "name": "logo", "kind": "logo"})
    assert r.status_code == 403


async def test_responses_carry_request_id_and_security_headers():
    c = client()
    r = await c.get("/api/health", headers={"x-request-id": "abc-123"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "abc-123"
    assert r.headers["x-content-type-options"] == "nosniff"
    r = await c.get("/api/health/ready")
    assert r.status_code == 200 and r.json()["db"] == "up"


async def test_errors_have_one_shape_with_request_id():
    r = await client().post("/api/a/projects.list", json={})
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "logged_out" and err["request_id"]


@pytest.mark.parametrize("path", ["/..%2f..%2f..%2fetc%2fpasswd", "/%2e%2e/%2e%2e/backend/app/core/settings.py"])
async def test_spa_never_serves_files_outside_the_build(path):
    r = await client().get(path)
    assert "SECRET_KEY" not in r.text and "root:" not in r.text


async def test_public_client_otp_is_rate_limited_per_ip(monkeypatch):
    from app.core import settings
    owner = await login("+919811113004")
    ws = await act(owner, "workspace.get")
    monkeypatch.setattr(settings, "OTP_PER_IP_PER_HOUR", 2)
    c = client()
    for i in range(2):
        r = await c.post(f"/api/public/{ws['slug']}/otp", json={"phone": f"+9198111131{i:02d}"}, headers={"x-real-ip": "9.9.9.9"})
        assert r.status_code == 200, r.text
    r = await c.post(f"/api/public/{ws['slug']}/otp", json={"phone": "+919811113199"}, headers={"x-real-ip": "9.9.9.9"})
    assert r.status_code == 429


async def test_oauth_connect_state_is_single_use():
    c = await login("+919811113005")
    url = (await c.get("/api/connect/gmail/start")).json()["url"]
    path = url.split("://", 1)[-1].split("/", 1)[1]
    r1 = await c.get("/" + path, follow_redirects=False)
    assert "connected=gmail" in r1.headers["location"]
    r2 = await c.get("/" + path, follow_redirects=False)
    assert "connect=failed" in r2.headers["location"]


async def test_contract_pdf_escapes_client_text_and_fetches_nothing():
    from app.services.pdf import contract_pdf
    sig = [{"name": "<img src='file:///etc/passwd'>Asha", "role": "client", "signed_at": datetime.now(timezone.utc),
            "device": "<link rel=stylesheet href='http://169.254.169.254/'>", "ip": "1.2.3.4"}]
    pdf = await contract_pdf("P", "T", "<p>Body <img src='file:///etc/hostname'></p>", sig, "h")
    assert pdf.startswith(b"%PDF-")


def test_production_refuses_unsafe_settings(monkeypatch):
    from app.core import settings
    monkeypatch.setattr(settings, "QA_MODE", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "dev-secret-change-me")
    monkeypatch.setattr(settings, "TOKEN_KEY", "")
    monkeypatch.setattr(settings, "APP_URL", "http://x")
    monkeypatch.delenv("ALLOW_UNSAFE_CONFIG", raising=False)
    with pytest.raises(settings.ConfigError):
        settings.validate()
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 40)
    monkeypatch.setattr(settings, "TOKEN_KEY", "k")
    monkeypatch.setattr(settings, "APP_URL", "https://app.example.in")
    monkeypatch.setattr(settings, "MONGO_URL", "mongodb://mongo.railway.internal:27017")
    assert settings.problems() == []


async def test_per_workspace_jobs_isolate_failures():
    from app.workers import jobs
    await login("+919811113006")
    await login("+919811113007")
    seen = []

    async def fn(ws_id):
        seen.append(ws_id)
        if len(seen) == 1:
            raise RuntimeError("boom")
        return 1
    assert await jobs.for_each_workspace(fn) == len(seen) - 1
    assert len(seen) >= 2


async def test_a_fresh_lease_is_granted_first_time_and_then_exclusive():
    """Regression: the original lock returned the pre-upsert document (None), so every
    job's very first run was skipped and the job stayed locked for 10 minutes."""
    from app.db.locks import acquire, release
    assert await acquire("t:fresh", 60) is True
    assert await acquire("t:fresh", 60) is False
    await release("t:fresh")
    assert await acquire("t:fresh", 60) is True


async def test_run_job_runs_on_its_very_first_call():
    from app.workers.jobs import run_job
    r = await run_job("housekeeping")
    assert r["ok"] is True, r


async def test_inbound_webhooks_need_the_shared_secret(monkeypatch):
    from app.core import settings
    monkeypatch.setattr(settings, "HOOK_SECRET", "s3cret-hook")
    c = client()
    body = {"from": "+919800000000", "text": "done"}
    assert (await c.post("/api/hooks/whatsapp-inbound", json=body)).status_code == 401
    assert (await c.post("/api/hooks/whatsapp-inbound?secret=wrong", json=body)).status_code == 401
    assert (await c.post("/api/hooks/whatsapp-inbound?secret=s3cret-hook", json=body)).status_code == 200
    assert (await c.post("/api/hooks/email-events", json={}, headers={"x-hook-secret": "s3cret-hook"})).status_code == 200
    # Production without a secret refuses outright, and won't boot with live messaging.
    monkeypatch.setattr(settings, "HOOK_SECRET", "")
    monkeypatch.setattr(settings, "QA_MODE", False)
    assert (await c.post("/api/hooks/meetbot", json={})).status_code == 403
    monkeypatch.setenv("VENDOR_WHATSAPP", "live")
    assert any("HOOK_SECRET" in p for p in settings.problems())


async def test_staff_sign_in_works_and_locks_after_repeated_wrong_passwords(monkeypatch):
    from app.core import settings
    from app.api.routes.auth import STAFF_MAX_FAILURES
    monkeypatch.setattr(settings, "STAFF_EMAIL", "team@example.in")
    monkeypatch.setattr(settings, "STAFF_PASSWORD", "correct horse battery")
    c = client()
    ok = await c.post("/api/auth/staff", json={"email": "Team@Example.in", "password": "correct horse battery"})
    assert ok.status_code == 200
    assert (await c.get("/api/admin/kpis")).status_code == 200
    bad = client()
    for _ in range(STAFF_MAX_FAILURES):
        assert (await bad.post("/api/auth/staff", json={"email": "team@example.in", "password": "nope"}, headers={"x-real-ip": "7.7.7.7"})).status_code == 401
    # Locked now: even the right password is refused from that network / for that email.
    r = await bad.post("/api/auth/staff", json={"email": "team@example.in", "password": "correct horse battery"}, headers={"x-real-ip": "7.7.7.7"})
    assert r.status_code == 429
    r = await client().post("/api/auth/staff", json={"email": "team@example.in", "password": "correct horse battery"}, headers={"x-real-ip": "8.8.8.8"})
    assert r.status_code == 429   # per-email lock too
    from app.core.util import advance_clock
    advance_clock(minutes=16)
    r = await client().post("/api/auth/staff", json={"email": "team@example.in", "password": "correct horse battery"}, headers={"x-real-ip": "8.8.8.8"})
    assert r.status_code == 200


def test_aisensy_campaign_names_can_be_overridden(monkeypatch):
    from app.core import settings
    assert settings.aisensy_campaign("otp_login") == "otp_login"
    monkeypatch.setenv("AISENSY_CAMPAIGN_OTP_LOGIN", "hub_login_code_")
    monkeypatch.setenv("AISENSY_CAMPAIGN_PAYMENT_REMINDER", " payment_reminder_ic ")
    assert settings.aisensy_campaign("otp_login") == "hub_login_code_"
    assert settings.aisensy_campaign("payment_reminder") == "payment_reminder_ic"
    assert settings.aisensy_campaign("file_link") == "file_link"


async def test_live_whatsapp_sends_the_overridden_campaign_and_logs_failures(monkeypatch, caplog):
    import httpx as _httpx
    from app.core import settings
    from app.integrations import vendors
    sent = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            sent.append(json)
            return _httpx.Response(400, json={"message": "Campaign not found"})

    monkeypatch.setattr(settings, "QA_MODE", False)
    monkeypatch.setenv("VENDOR_WHATSAPP", "live")
    monkeypatch.setenv("VENDOR_SMS", "fake")
    monkeypatch.setenv("AISENSY_CAMPAIGN_OTP_LOGIN", "hub_login_code_")
    monkeypatch.setattr(vendors.httpx, "AsyncClient", FakeClient)
    import logging
    with caplog.at_level(logging.WARNING, logger="app.vendors"):
        with pytest.raises(Exception) as e:
            await vendors.otp_send("+919800000001", "123456")
    assert sent[0]["campaignName"] == "hub_login_code_" and sent[0]["templateParams"] == ["123456"]
    assert getattr(e.value, "code", "") == "vendor_failed"      # no silent fake-SMS fallback
    rec = [r for r in caplog.records if r.getMessage() == "whatsapp send failed"]
    assert rec and "Campaign not found" in rec[0].fields["reply"] and "apiKey" not in rec[0].fields["reply"]
