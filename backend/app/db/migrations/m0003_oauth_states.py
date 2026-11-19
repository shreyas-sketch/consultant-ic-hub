"""0003: connected-account OAuth states moved out of `otp_codes` into `oauth_states`.

Old rows looked like {"phone": "oauth:<state>", ...}. They are only valid for
minutes, so they are simply removed; anyone mid-connect clicks Connect again.
"""
ID = "0003_oauth_states"


async def up(db):
    r = await db.otp_codes.delete_many({"phone": {"$regex": "^oauth:"}})
    return r.deleted_count
