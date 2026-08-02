"""
Adds standard security response headers to every request. This is a
platform used by children, so beyond the usual web-hardening value these
headers also close off some real risk vectors: clickjacking (a malicious
site framing the app to trick a child into clicking something), MIME
sniffing, and unwanted access to the camera/microphone/location from any
page in the app (this app never needs any of those).
"""
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # No camera/mic/geolocation/payment access anywhere in the app.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        # Content-Security-Policy: this build serves its own frontend from the
        # same origin as the API and only loads Bootstrap from cdnjs, so the
        # policy stays tight. 'unsafe-inline' is needed because the frontend
        # uses inline <style>/<script> blocks throughout — a future pass that
        # moves those into external files could drop it for a stricter policy.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://cdnjs.cloudflare.com; "
            "connect-src 'self' https://api.dictionaryapi.dev; "
            "frame-ancestors 'none'; "
            "object-src 'none'; "
            "base-uri 'self'"
        )
        # HSTS only makes sense once this is actually served over HTTPS in
        # production — harmless to send locally, but flagged here so it isn't
        # mistaken for "the app is on HTTPS."
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        # CSS/JS are the files most likely to change between deploys and the
        # most damaging to serve stale (a stale style.css/api.js can make the
        # whole site look broken while HTML loads fine). Forcing revalidation
        # means the browser always checks back with the server instead of
        # silently reusing whatever it cached from a previous, possibly
        # buggy, build.
        if request.url.path.endswith((".css", ".js", ".mjs")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"

        return response
