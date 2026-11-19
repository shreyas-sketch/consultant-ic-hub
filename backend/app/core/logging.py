"""Structured logging. JSON lines in production (Railway's log explorer parses them),
plain text in QA. Every line carries the request id when there is one."""
import contextvars
import json
import logging
import sys
import time

request_id_var: contextvars.ContextVar = contextvars.ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        for k, v in getattr(record, "fields", {}).items():
            out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record):
        base = f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        extra = getattr(record, "fields", {})
        if extra:
            base += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_configured = False


def setup_logging():
    global _configured
    if _configured:
        return
    from app.core import settings
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if settings.LOG_JSON else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(settings.LOG_LEVEL)
    # uvicorn's access log is replaced by our middleware (it has the request id and timing).
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("apscheduler", "pymongo", "httpx", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_fields(logger, level, msg, **fields):
    logger.log(level, msg, extra={"fields": fields})
