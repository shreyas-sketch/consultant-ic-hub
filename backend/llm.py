"""The one AI helper. Every model call in the product goes through here.

- A queue per worker (LLM_MAX_CONCURRENCY) with a wait limit; when full the
  caller gets "Busy, try again in a minute".
- Fake mode returns the caller's canned answer, so every screen works in QA.
- Every call returns token counts and the cost in paise for metering.
Model names live in settings (and Admin > Settings), never in code.
"""
import asyncio
import json

import httpx

from core import settings
from core.db import get_db
from core.util import AppError

_sem = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)


async def model_for(size: str) -> tuple:
    """(model name, (price_in, price_out) paise per million tokens)."""
    s = await get_db().admin_settings.find_one({"_id": "ai"}) or {}
    if size == "large":
        return s.get("model_large", settings.MODEL_LARGE), tuple(s.get("price_large", settings.PRICE_LARGE))
    return s.get("model_small", settings.MODEL_SMALL), tuple(s.get("price_small", settings.PRICE_SMALL))


def cost_paise(usage: dict, price: tuple) -> int:
    return round(usage.get("input_tokens", 0) * price[0] / 1_000_000 + usage.get("output_tokens", 0) * price[1] / 1_000_000)


async def messages(size, system, msgs, tools=None, max_tokens=2000, fake=None):
    """One model turn. Returns {"content": [blocks], "usage": {...}, "cost_paise": int, "stop_reason": str}.

    `fake` is a function (msgs) -> list of content blocks, used in fake mode.
    """
    model, price = await model_for(size)
    if settings.vendor_mode("ai") != "live" or not settings.ANTHROPIC_API_KEY:
        blocks = fake(msgs) if fake else [{"type": "text", "text": "(fake AI answer)"}]
        usage = {"input_tokens": 600 + 40 * len(msgs), "output_tokens": 180}
        return {"content": blocks, "usage": usage, "cost_paise": cost_paise(usage, price),
                "stop_reason": "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn",
                "model": f"fake:{model}"}
    try:
        await asyncio.wait_for(_sem.acquire(), timeout=settings.LLM_WAIT_SECONDS)
    except asyncio.TimeoutError:
        raise AppError("busy", "Busy, try again in a minute.", 503)
    try:
        body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": msgs}
        if tools:
            body["tools"] = tools
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post("https://api.anthropic.com/v1/messages", json=body,
                             headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"})
        if r.status_code >= 300:
            raise AppError("ai_failed", "The AI could not answer right now. Please try again.", 502)
        j = r.json()
        return {"content": j["content"], "usage": j.get("usage", {}), "cost_paise": cost_paise(j.get("usage", {}), price),
                "stop_reason": j.get("stop_reason"), "model": model}
    finally:
        _sem.release()


async def complete_json(size, system, prompt, fake: dict, max_tokens=2000):
    """Ask for JSON back. Falls back to the fake answer's shape if parsing fails."""
    res = await messages(size, system + "\nAnswer with JSON only.", [{"role": "user", "content": prompt}],
                         max_tokens=max_tokens, fake=lambda m: [{"type": "text", "text": json.dumps(fake)}])
    text = "".join(b.get("text", "") for b in res["content"] if b["type"] == "text").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    try:
        data = json.loads(text)
    except Exception:
        data = fake
    return data, res
