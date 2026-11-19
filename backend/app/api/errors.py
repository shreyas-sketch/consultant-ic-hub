"""One error shape for every endpoint: {"error": {"code", "message", "extra"?}}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var
from app.core.util import AppError

log = logging.getLogger("app.errors")


def _body(code, message, extra=None):
    err = {"code": code, "message": message}
    if extra:
        err["extra"] = extra
    rid = request_id_var.get()
    if rid:
        err["request_id"] = rid
    return {"error": err}


def install(app: FastAPI):
    @app.exception_handler(AppError)
    async def app_error(request: Request, e: AppError):
        return JSONResponse(_body(e.code, e.message, e.extra), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, e: RequestValidationError):
        return JSONResponse(_body("invalid", "Some details are missing or not valid. Please check and try again."), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, e: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return JSONResponse(_body(code, str(e.detail) if e.detail else "Not found."), status_code=e.status_code,
                            headers=getattr(e, "headers", None))

    @app.exception_handler(Exception)
    async def crash(request: Request, e: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_body("server", "Something went wrong on our side. Please try again."), status_code=500)
