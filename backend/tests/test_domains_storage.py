import base64

from conftest import act, client, login
from app.db import get_db


def data_url(n_bytes):
    return "data:application/pdf;base64," + base64.b64encode(b"%PDF-" + b"x" * max(0, n_bytes - 5)).decode()


async def test_storage_limit_blocks_upload_when_full():
    owner = await login("+919811112001")
    admin = await login("+919899992001", "Staff")
    await get_db().users.update_one({"phone": "+919899992001"}, {"$set": {"is_admin": True}})
    r = await admin.put("/api/admin/limits/storage_mb", json={"value": 1})
    assert r.status_code == 200
    r = await owner.post("/api/upload", json={"name": "a.pdf", "data": data_url(700_000)})
    assert r.status_code == 200, r.text
    r = await owner.post("/api/upload", json={"name": "b.pdf", "data": data_url(700_000)})
    assert r.status_code == 402 and r.json()["error"]["code"] == "limit"
    assert "storage is full" in r.json()["error"]["message"]


async def test_custom_domain_serves_client_pages():
    owner = await login("+919811112002")
    admin = await login("+919899992002", "Staff")
    await get_db().users.update_one({"phone": "+919899992002"}, {"$set": {"is_admin": True}})
    ws = await act(owner, "workspace.get")
    r = await admin.post("/api/admin/domains", json={"workspace_id": ws["id"], "host": "Book.MehtaAdvisory.in"})
    assert r.status_code == 200, r.text
    # TLS proxy check: known domain yes, unknown no.
    anon = client()
    assert (await anon.get("/api/public/domain-check", params={"domain": "book.mehtaadvisory.in"})).status_code == 200
    assert (await anon.get("/api/public/domain-check", params={"domain": "evil.example.com"})).status_code == 404
    # Links in emails now use the practice's own domain.
    from app.domain.documents.merge import client_base
    w = await get_db().workspaces.find_one({"_id": ws["id"]})
    assert client_base(w) == "https://book.mehtaadvisory.in"
    # Removing it puts links back on our domain.
    await admin.delete("/api/admin/domains/book.mehtaadvisory.in")
    w = await get_db().workspaces.find_one({"_id": ws["id"]})
    assert not w.get("domains")


async def test_reopen_lets_client_change_answers_then_completes_again():
    from conftest import ready_practice
    c = await login("+919811112003")
    await ready_practice(c)
    pr = await act(c, "projects.create", {"name": "Q", "contact": {"name": "Asha", "email": "a@x.in"}})
    pages = [{"title": "About you", "button": "Submit", "blocks": [
        {"type": "questions", "questions": [{"id": "q1", "kind": "short", "label": "Company size", "required": True}]}]}]
    f = await act(c, "files.create_from_template", {"project_id": pr["id"]})
    f = await act(c, "files.update", {"id": f["id"], "pages": pages})
    await act(c, "files.send", {"id": f["id"]})
    pub = client()
    v = (await pub.get(f"/api/public/f/{f['token']}")).json()
    bid = v["pages"][0]["blocks"][0]["id"]
    assert (await pub.post(f"/api/public/f/{f['token']}/answers", json={"block_id": bid, "answers": {"q1": "12"}})).status_code == 200
    assert (await pub.post(f"/api/public/f/{f['token']}/complete")).status_code == 200
    # Locked after submit.
    r = await pub.post(f"/api/public/f/{f['token']}/answers", json={"block_id": bid, "answers": {"q1": "40"}})
    assert r.status_code == 409
    # Consultant reopens; client changes the answer and submits again.
    await act(c, "files.reopen", {"id": f["id"]})
    assert (await pub.post(f"/api/public/f/{f['token']}/answers", json={"block_id": bid, "answers": {"q1": "40"}})).status_code == 200
    assert (await pub.post(f"/api/public/f/{f['token']}/complete")).status_code == 200
    doc = await get_db().client_files.find_one({"_id": f["id"]})
    assert doc["status"] == "completed" and not doc.get("reopened") and doc["answers"]["q1"] == "40"
    # Reopen on a file that isn't completed is refused plainly.
    await act(c, "files.reopen", {"id": f["id"]})
    r = await c.post("/api/a/files.reopen", json={"id": f["id"]})
    assert r.status_code == 400


async def test_practice_subdomain_serves_client_pages_but_app_host_does_not(monkeypatch):
    import os
    import pytest
    from app.api.routes import frontend as server
    from app.core import settings
    if not os.path.isfile(os.path.join(server.FRONTEND, "client.html")):
        pytest.skip("screens not built")
    owner = await login("+919811112004")
    ws = await act(owner, "workspace.get")
    monkeypatch.setattr(settings, "CLIENT_DOMAIN", "example.in")
    monkeypatch.setattr(settings, "APP_URL", "https://app.example.in")
    c = client()
    r = await c.get("/f/abc", headers={"host": f"{ws['slug']}.example.in"})
    assert f"window.__SLUG__='{ws['slug']}'" in r.text
    r = await c.get("/", headers={"host": "app.example.in"})
    assert "__SLUG__" not in r.text and r.status_code == 200
    r = await c.get("/", headers={"host": "nobody-here.example.in"})
    assert "__SLUG__" not in r.text
