"""Data migrations run at start. Each is safe to repeat."""
from app.domain.billing.rates import resolve


async def backfill_time_entries(db):
    """Migration: older entries get a billing status and a rate snapshot. Runs at start; safe to repeat."""
    from app.core.context import system_ctx
    n = 0
    async for e in db.time_entries.find({"billing_status": {"$exists": False}}):
        ctx = system_ctx(e["workspace_id"])
        status = "billed" if e.get("invoiced") else "unbilled"
        rate = int(e.get("rate_paise") or 0)
        if not rate:
            pr = await ctx.data.projects.get(e["project_id"])
            rate = (await resolve(ctx, pr, e.get("date"))).get("hourly_paise", 0)
        await db.time_entries.update_one({"_id": e["_id"]}, {"$set": {
            "billing_status": status, "billable": True, "rate_snapshot_paise": rate, "cost_snapshot_paise": 0, "currency": "INR",
            "invoice_id": e.get("invoice_id"), "locked": status == "billed", "service_id": e.get("service_id"), "task_id": e.get("task_id")}})
        n += 1
    return n
