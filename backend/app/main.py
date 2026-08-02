import mimetypes
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import engine, Base, SessionLocal
from .rate_limit import RateLimitMiddleware
from .logging_middleware import RequestLoggingMiddleware
from .security_headers import SecurityHeadersMiddleware
from .search_router import router as search_router
from . import models
from .routers import (
    auth_router, library_router, community_router, journal_router,
    progress_router, certificates_router, notifications_router, admin_router,
    clubs_router, mentorship_router, live_router, resources_router,
    shelves_router, reports_router, messages_router, donations_router,
    training_router,
)

Base.metadata.create_all(bind=engine)

# Seed the dynamic categories table from the original static list, once.
# Safe to run on every boot: it's a no-op once any category row exists,
# and admins can rename/delete/add categories afterward via the admin panel.
_DEFAULT_CATEGORIES = [
    "Leadership", "Technology", "Entrepreneurship", "Finance", "Christian",
    "Business", "Health", "Education", "History", "Fiction", "Romance",
    "African Literature", "Children's Books", "Science", "Personal Development",
]
_db = SessionLocal()
try:
    if _db.query(models.Category).count() == 0:
        for _name in _DEFAULT_CATEGORIES:
            _db.add(models.Category(name=_name))
        _db.commit()
finally:
    _db.close()

app = FastAPI(title="Gwin's Readers Club API", version="1.1.0")

# CORS origins are configurable via RC_CORS_ORIGINS (comma-separated). We
# default to common local dev origins rather than "*" because browsers
# reject a wildcard origin combined with allow_credentials=True anyway —
# and shipping that combination to production would be a real security gap.
_cors_env = os.environ.get("RC_CORS_ORIGINS")
if _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _cors_origins = [
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Order matters: rate limiting runs first (rejects abusive requests before
# they're logged), then logging wraps the actual request handling, then
# security headers are stamped onto whatever response comes back.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

app.include_router(auth_router.router)
app.include_router(library_router.router)
app.include_router(community_router.router)
app.include_router(journal_router.router)
app.include_router(progress_router.router)
app.include_router(certificates_router.router)
app.include_router(notifications_router.router)
app.include_router(admin_router.router)
app.include_router(clubs_router.router)
app.include_router(mentorship_router.router)
app.include_router(live_router.router)
app.include_router(resources_router.router)
app.include_router(shelves_router.router)
app.include_router(reports_router.router)
app.include_router(messages_router.router)
app.include_router(donations_router.router)
app.include_router(training_router.router)
app.include_router(search_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "Gwin's Readers Club", "version": "1.1.0"}


# StaticFiles guesses each file's Content-Type from the *operating system's*
# MIME registry (Python's mimetypes module). On many Windows machines that
# registry has no entry (or the wrong one) for .css/.js, so those files get
# served as text/plain. Combined with the X-Content-Type-Options: nosniff
# header set above, browsers then refuse to apply the stylesheet or execute
# the script at all — every browser, since nosniff is a standard, universally
# respected header, not a browser quirk. Registering the types explicitly
# here means the correct Content-Type is always sent, regardless of what (if
# anything) the host OS has configured.
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

# Resolve the frontend directory relative to this file rather than the
# process's current working directory. A plain relative path like
# "../frontend" only works if uvicorn happens to be launched from inside
# backend/ (as the README instructs) — running it from anywhere else (an
# IDE's default run directory, a script, a process manager) makes FastAPI
# fail to find the frontend directory at all. Resolving from __file__ makes
# this work no matter where the server is started from.
_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend")
_FRONTEND_DIR = os.path.normpath(_FRONTEND_DIR)

app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
