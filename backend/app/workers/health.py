"""A tiny HTTP liveness endpoint for the worker (optional).

If PORT is set (Railway sets it when the service has networking), the worker
answers GET /health with 200 while the scheduler loop is alive, so a Railway
healthcheck or uptime monitor can watch it. No framework: a raw asyncio server.
"""
import asyncio
import json
import os
import time

_started = time.time()


async def _handle(reader, writer):
    try:
        await asyncio.wait_for(reader.readline(), timeout=5)
        body = json.dumps({"ok": True, "role": "worker", "uptime_s": round(time.time() - _started)}).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def serve_health():
    port = os.getenv("WORKER_HEALTH_PORT") or os.getenv("PORT")
    if not port:
        return None
    return await asyncio.start_server(_handle, "0.0.0.0", int(port))
