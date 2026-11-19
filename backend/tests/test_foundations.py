"""Step 0: invite-only access, tenant isolation, limits from the database, roles."""
import os
import re

from conftest import act, client, invite, login
from app.core import limits
from app.db import get_db


async def test_invited_number_logs_in_and_gets_a_workspace():
    c = await login("+919811111111")
    me = (await c.get("/api/auth/me")).json()
    assert me["workspaces"] and me["workspaces"][0]["role"] == "owner"


async def test_not_invited_number_sees_one_line_both_ways():
    c = client()
    r = await c.post("/api/auth/otp/request", json={"phone": "9822222222"})
    assert r.status_code == 403
    assert r.json()["error"]["message"] == "This product is by invitation right now."
    # Going straight to the API is blocked too.
    r = await c.post("/api/auth/otp/verify", json={"phone": "9822222222", "code": "000000"})
    assert r.status_code == 403
    assert (await c.post("/api/a/projects.search", json={})).status_code == 401


async def test_no_cross_workspace_read():
    a = await login("+919811111112")
    b = await login("+919811111113")
    pa = await act(a, "projects.create", {"name": "A's secret", "contact": {"name": "Client A", "phone": "9800000001"}})
    r = await b.post("/api/a/projects.get", json={"id": pa["id"]})
    assert r.status_code == 404
    rows = await act(b, "projects.search", {"q": "secret"})
    assert rows["total"] == 0
    r = await b.post("/api/a/contacts.get", json={"id": pa["contact_ids"][0]})
    assert r.status_code == 404


def test_actions_never_touch_tenant_collections_directly():
    """Every tenant read goes through ctx.data (the workspace filter)."""
    from app.db import TENANT_COLLECTIONS
    here = os.path.join(os.path.dirname(__file__), "..", "app", "domain")
    bad = []
    paths = [os.path.join(r, f) for r, _, fs in os.walk(here) for f in fs if f.endswith(".py")]
    assert len(paths) > 20, "domain modules not found"
    for path in paths:
        fn = os.path.basename(path)
        src = open(path).read()
        for m in re.finditer(r"get_db\(\)\.(\w+)", src):
            if m.group(1) in TENANT_COLLECTIONS:
                bad.append(f"{fn}: get_db().{m.group(1)}")
        for m in re.finditer(r"\bdb\.(\w+)\.", src):
            if m.group(1) in TENANT_COLLECTIONS and fn != "workspace.py":
                bad.append(f"{fn}: db.{m.group(1)}")
    assert not bad, bad


async def test_tenant_helper_refuses_global_and_unknown_collections():
    from app.db.tenant import Data
    d = Data("ws1")
    for name in ("users", "invites"):
        try:
            getattr(d, name)
            assert False
        except PermissionError:
            pass


async def test_limit_change_in_admin_takes_effect_without_deploy():
    owner = await login("+919811111114")
    admin = await login("+919899999999", "Staff")
    await get_db().users.update_one({"phone": "+919899999999"}, {"$set": {"is_admin": True}})
    for i in range(5):
        await act(owner, "views.save", {"name": f"V{i}"})
    r = await owner.post("/api/a/views.save", json={"name": "V6"})
    assert r.status_code == 402 and r.json()["error"]["code"] == "limit"
    r = await admin.put("/api/admin/limits/saved_views", json={"value": 8})
    assert r.status_code == 200
    await act(owner, "views.save", {"name": "V6"})
    log = (await admin.get("/api/admin/changes")).json()
    assert log[0]["what"] == "limit.saved_views" and log[0]["old"] == 5
    # One-click revert
    await admin.post(f"/api/admin/changes/{log[0]['id']}/revert")
    limits.bust_cache()
    assert (await limits.value("x", "saved_views")) == 5


async def test_limit_for_new_accounts_only_keeps_old_accounts():
    old = await login("+919811111115")
    admin = await login("+919899999998", "Staff")
    await get_db().users.update_one({"phone": "+919899999998"}, {"$set": {"is_admin": True}})
    await admin.put("/api/admin/limits/users_per_workspace", json={"value": 3, "applies_to": "new_accounts"})
    old_ws = (await act(old, "workspace.get"))
    assert old_ws["limits"]["users_per_workspace"] == 10
    new = await login("+919811111116")
    assert (await act(new, "workspace.get"))["limits"]["users_per_workspace"] == 3


async def test_admin_routes_matrix():
    c = client()
    assert (await c.get("/api/admin/kpis")).status_code == 401
    member = await login("+919811111117")
    assert (await member.get("/api/admin/kpis")).status_code == 403


async def test_team_member_counts_as_invited_and_roles_apply():
    owner = await login("+919811111118")
    await act(owner, "team.add", {"phone": "9811111119", "name": "Kabir", "role": "member"})
    m = await login("+919811111119", invited=False)  # added by the Owner, so invited
    me = (await m.get("/api/auth/me")).json()
    assert any(w["role"] == "member" for w in me["workspaces"])
    other = await act(owner, "projects.create", {"name": "Owner's project", "contact": {"name": "X", "phone": "9800000002"}})
    await m.post("/api/auth/switch", json={"workspace_id": next(w["id"] for w in me["workspaces"] if w["role"] == "member")})
    r = await m.post("/api/a/projects.get", json={"id": other["id"]})
    assert r.status_code == 404  # a Member can't open another member's project by changing the URL
    r = await m.post("/api/a/stages.save", json={"stages": [{"name": "Only"}]})
    assert r.status_code == 403


async def test_admin_can_add_team_but_refunds_are_owner_admin_only():
    owner = await login("+919811111120")
    await act(owner, "team.add", {"phone": "9811111121", "name": "Arjun", "role": "admin"})
    adm = await login("+919811111121", invited=False)
    await act(adm, "team.add", {"phone": "9811111122", "name": "Kabir", "role": "member"})
    from app.domain.registry import ACTIONS
    assert ACTIONS["payments.refund"].roles <= {"owner", "admin", "system"}


async def test_removed_access_is_read_only_and_client_links_keep_working():
    from app.db import get_db
    c = await login("+919811111123")
    await act(c, "workspace.update", {"invoice": {"upi_id": "x@okicici"}})
    pr = await act(c, "projects.create", {"name": "P", "contact": {"name": "Client", "phone": "9800000003", "email": "c@x.in"}})
    t = await act(c, "templates.list", {"kind": "file"})
    f = await act(c, "files.create_from_template", {"project_id": pr["id"], "template_id": next(x["id"] for x in t if x["name"].startswith("Onboarding"))})
    await act(c, "files.send", {"id": f["id"], "channel": "email"})
    admin = await login("+919899999997", "Staff")
    await get_db().users.update_one({"phone": "+919899999997"}, {"$set": {"is_admin": True}})
    inv = await get_db().invites.find_one({"phone": "+919811111123"})
    await admin.post(f"/api/admin/invites/{inv['_id']}/access", json={})
    r = await c.post("/api/a/projects.create", json={"name": "New"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    assert (await c.post("/api/a/projects.search", json={})).status_code == 200
    r = await client().get(f"/api/public/f/{f['token']}")
    assert r.status_code == 200
    # And the number can't start a new login.
    r = await client().post("/api/auth/otp/request", json={"phone": "+919811111123"})
    assert r.status_code == 403


async def test_plain_error_messages():
    c = await login("+919811111124")
    r = await c.post("/api/a/projects.create", json={})
    assert r.status_code == 400
    msg = r.json()["error"]["message"]
    assert "Name" in msg and "{" not in msg


_ = invite
