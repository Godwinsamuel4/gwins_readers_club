import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("readersclub")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

SLOW_REQUEST_THRESHOLD_MS = 500


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 1)

        response.headers["X-Request-ID"] = request_id

        log_line = f"[{request_id}] {request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)"
        if duration_ms > SLOW_REQUEST_THRESHOLD_MS:
            logger.warning(f"SLOW {log_line}")
        elif response.status_code >= 500:
            logger.error(log_line)
        else:
            logger.info(log_line)

        return response
