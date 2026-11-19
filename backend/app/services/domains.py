"""Which practice a request host belongs to: <slug>.<CLIENT_DOMAIN> or a mapped custom domain."""
from urllib.parse import urlparse

from app.core import settings
from app.db import get_db

RESERVED_SUBDOMAINS = {"app", "www", "api", "admin", "mail", "reply", "static", "assets"}


async def slug_for_host(host: str):
    host = (host or "").split(":")[0].lower()
    if not host or host == (urlparse(settings.APP_URL).hostname or "").lower():
        return None   # the consultant app itself
    if settings.CLIENT_DOMAIN and host.endswith("." + settings.CLIENT_DOMAIN):
        sub = host[: -len(settings.CLIENT_DOMAIN) - 1]
        if sub in RESERVED_SUBDOMAINS or "." in sub:
            return None
        ws = await get_db().workspaces.find_one({"slug": sub}, {"_id": 1})
        return sub if ws else None
    d = await get_db().domains.find_one({"host": host})
    if d:
        ws = await get_db().workspaces.find_one({"_id": d["workspace_id"]}, {"slug": 1})
        return (ws or {}).get("slug")
    return None
