"""Connected accounts (Gmail, Outlook, Zoom): list, toggle the lead finder, disconnect.

The OAuth dance itself is HTTP-shaped and lives in app/api/routes/connections.py.
"""
from app.domain.registry import P, action


@action("connections.list", "read", agent_ok=False, desc="Connected accounts.")
async def connections_list(ctx, p):
    return [{"id": c["_id"], "provider": c["provider"], "account": c.get("account"), "lead_finder": c.get("lead_finder", False),
             "mine": c["user_id"] == ctx.user_id} for c in await ctx.data.connections.find({})]


class ConnIn(P):
    id: str
    lead_finder: bool = None


@action("connections.update", "internal", ConnIn, agent_ok=False, desc="Turn the inbox lead finder on or off for a connected inbox.")
async def connections_update(ctx, p: ConnIn):
    await ctx.data.connections.update({"_id": p.id, "user_id": ctx.user_id}, {"lead_finder": bool(p.lead_finder)})
    return await connections_list(ctx, None)


@action("connections.disconnect", "destructive", ConnIn, agent_ok=False, desc="Disconnect an account.")
async def connections_disconnect(ctx, p: ConnIn):
    await ctx.data.connections.hard_delete({"_id": p.id, "user_id": ctx.user_id})
    return await connections_list(ctx, None)
