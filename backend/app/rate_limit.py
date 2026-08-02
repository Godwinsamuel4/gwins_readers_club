"""
Simple in-memory rate limiter. Per-process, per-IP — fine for a single
uvicorn instance at this scale. If this app ever runs multiple instances
behind a load balancer, this needs to move to a shared store (Redis) so
limits are enforced across instances rather than per-instance.
"""
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# path prefix -> (max requests, window seconds)
RATE_LIMITS = {
    "/api/auth/login": (10, 900),      # 10 FAILED attempts / 15 min / IP
    "/api/auth/register": (10, 900),
    "/api/auth/password-reset": (5, 3600),
    "__default__": (300, 60),          # generous abuse backstop for everything else
}

# Paths where only failed responses count against the limit — this is the
# standard pattern for auth endpoints: a user who logs into several accounts
# in a row (or an admin testing multiple role accounts) should never be
# blocked just for succeeding repeatedly. What the limit actually needs to
# stop is repeated *failures* — that's the brute-force signal.
FAILURE_ONLY_PATHS = {"/api/auth/login", "/api/auth/register", "/api/auth/password-reset"}

_request_log: dict[str, deque] = defaultdict(deque)


def _limit_for(path: str):
    for prefix, limit in RATE_LIMITS.items():
        if prefix != "__default__" and path.startswith(prefix):
            return limit
    return RATE_LIMITS["__default__"]


def _matched_prefix(path: str) -> str:
    for prefix in RATE_LIMITS:
        if prefix != "__default__" and path.startswith(prefix):
            return prefix
    return "__default__"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        prefix = _matched_prefix(path)
        max_requests, window = RATE_LIMITS[prefix]
        key = f"{client_ip}:{prefix}"

        now = time.time()
        log = _request_log[key]
        while log and log[0] < now - window:
            log.popleft()

        if len(log) >= max_requests:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Too many failed attempts — please wait a bit before trying again."}},
            )

        response = await call_next(request)

        # Only count this request against quota if it should. For auth
        # endpoints, a successful (< 400) response never counts — only
        # failures do, so legitimate repeated logins are never blocked.
        should_count = True
        if prefix in FAILURE_ONLY_PATHS and response.status_code < 400:
            should_count = False

        if should_count:
            log.append(now)

        return response
