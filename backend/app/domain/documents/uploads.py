"""Files attached to a project: consultant uploads, signed contracts, client uploads."""
from app.core.util import clean
from app.domain import perm
from app.domain.registry import P, action


class UploadsIn(P):
    project_id: str


@action("uploads.list", "read", UploadsIn, desc="Files on a project: uploads, signed contracts, client uploads.")
async def uploads_list(ctx, p: UploadsIn):
    await perm.project(ctx, p.project_id)
    return clean(await ctx.data.uploads.find({"project_id": p.project_id}, sort=[("created_at", -1)]))
