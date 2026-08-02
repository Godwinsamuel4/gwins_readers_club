"""
Shared Cloudinary storage helpers.

Every feature that used to write an uploaded file to local disk under
app/uploads/... (avatars, book files, book covers, opportunity logos,
training-session materials) now calls through here instead. Centralizing it
means there's exactly one place that talks to Cloudinary, one place that
knows the folder-naming convention, and one place to change if we ever swap
providers again.

Configuration (backend/.env or real environment variables):
  CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>
or, equivalently, the three separate variables:
  CLOUDINARY_CLOUD_NAME=...
  CLOUDINARY_API_KEY=...
  CLOUDINARY_API_SECRET=...
"""
import logging
import os
import re
import time
import uuid

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile

load_dotenv()

logger = logging.getLogger("readers_club.cloud_storage")

_CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL")
if _CLOUDINARY_URL:
    # cloudinary.config() picks up CLOUDINARY_URL from the environment
    # automatically, but we call it explicitly so a missing/blank value
    # fails loudly at startup instead of silently at first upload.
    cloudinary.config(cloudinary_url=_CLOUDINARY_URL, secure=True)
else:
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
        api_key=os.environ.get("CLOUDINARY_API_KEY"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        secure=True,
    )

# Folder prefix so everything from this app is grouped together in the
# Cloudinary media library rather than mixed in with other projects on the
# same account.
_ROOT_FOLDER = os.environ.get("CLOUDINARY_ROOT_FOLDER", "gwins_readers_club")

# How long to wait on a single Cloudinary call, and how many times to retry
# a failed upload before giving up. destroy() gets the same timeout — it's
# idempotent, so a retry there is harmless even if the first call actually
# succeeded server-side but timed out on our end.
_UPLOAD_TIMEOUT_SECONDS = 30
_MAX_UPLOAD_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.5


def _is_configured() -> bool:
    cfg = cloudinary.config()
    return bool(cfg.cloud_name and cfg.api_key and cfg.api_secret)


if not _is_configured():
    # Don't crash the whole app on import — plenty of endpoints don't touch
    # media storage — but make sure a missing/blank credential shows up
    # loudly in the server logs instead of only surfacing the first time a
    # user tries to upload something.
    logger.warning(
        "Cloudinary is not configured (missing CLOUDINARY_URL or "
        "CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET). File uploads will fail "
        "with a 500 until this is set."
    )


class UploadValidationError(HTTPException):
    """A bad/oversized/empty upload. Subclasses HTTPException so a router
    that doesn't catch it explicitly still returns a sensible 400 instead
    of bubbling up as a 500."""

    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=detail)


def read_upload(
    upload: UploadFile,
    max_bytes: int,
    allowed_extensions: tuple[str, ...] | None = None,
    field_label: str = "File",
) -> bytes:
    """Reads an UploadFile into memory with the validation every uploader in
    this app needs: non-empty, under the size cap, and (optionally) an
    allowed extension. Centralized so no upload path can accidentally skip
    one of these checks — the training-session resource upload used to
    accept any file type/size at all before this existed.

    Reads in chunks and bails out as soon as the size cap is exceeded,
    rather than reading the whole body first and checking after, so an
    oversized upload doesn't get fully buffered in memory before we notice.
    """
    if allowed_extensions is not None:
        ext = os.path.splitext(upload.filename or "")[1].lower()
        if ext not in allowed_extensions:
            allowed = ", ".join(e.lstrip(".") for e in allowed_extensions)
            raise UploadValidationError(f"{field_label} must be one of: {allowed}")

    chunks = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = upload.file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadValidationError(
                f"{field_label} is too large ({max_bytes // (1024 * 1024)}MB max)"
            )
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise UploadValidationError(f"{field_label} is empty")
    return raw


# Minimal magic-byte signatures for the image formats we accept. This is a
# cheap sanity check, not a full content-type sniffer — it stops the common
# "renamed a .exe to .jpg" case without pulling in a heavier dependency.
_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # WEBP is RIFF....WEBP; good enough as a first filter
}


def looks_like_image(raw: bytes) -> bool:
    if not raw:
        return False
    return any(raw.startswith(sig) for sig in _IMAGE_SIGNATURES)


def upload_bytes(
    raw: bytes,
    folder: str,
    original_filename: str = "",
    resource_type: str = "auto",
) -> dict:
    """Uploads raw bytes to Cloudinary under <root>/<folder>/<random-name>.

    resource_type="auto" lets Cloudinary detect image/video/raw, which is
    what we want for arbitrary book files (pdf/docx/epub/txt) as well as
    images. Returns the Cloudinary response dict (we mainly care about
    "secure_url" and "public_id").

    Transient failures (network blips, momentary 5xxs from Cloudinary) are
    retried a couple of times with a short backoff before giving up, since
    a user's upload failing because of a one-second network hiccup is a
    worse experience than a slightly slower successful upload.
    """
    if not _is_configured():
        raise HTTPException(
            status_code=500,
            detail="Media storage isn't configured. Set CLOUDINARY_URL (or "
                   "CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET) on the server.",
        )
    ext = os.path.splitext(original_filename or "")[1].lstrip(".")
    public_id = uuid.uuid4().hex

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_UPLOAD_ATTEMPTS + 1):
        try:
            result = cloudinary.uploader.upload(
                raw,
                folder=f"{_ROOT_FOLDER}/{folder}",
                public_id=public_id,
                resource_type=resource_type,
                # Keep the original extension in the delivered URL/filename
                # where Cloudinary supports it (mainly matters for "raw"
                # files like .docx/.epub so downloads keep a sane filename).
                format=ext or None,
                use_filename=False,
                unique_filename=False,
                overwrite=False,
                timeout=_UPLOAD_TIMEOUT_SECONDS,
            )
            if attempt > 1:
                logger.info("Cloudinary upload to %s succeeded on attempt %d", folder, attempt)
            return result
        except Exception as exc:  # cloudinary.exceptions.Error, network errors, etc.
            last_exc = exc
            logger.warning("Cloudinary upload to %s failed (attempt %d/%d): %s",
                            folder, attempt, _MAX_UPLOAD_ATTEMPTS, exc)
            if attempt < _MAX_UPLOAD_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    raise HTTPException(status_code=502, detail=f"Upload to media storage failed: {last_exc}")


# Matches the public_id segment of a Cloudinary delivery URL, tolerating an
# optional transformation segment right after /upload/ (e.g.
# c_fill,w_200,h_200/) and an optional version segment (v12345/), so URLs
# that picked up transformation params still resolve to the right
# public_id instead of silently failing to delete.
_PUBLIC_ID_RE = re.compile(
    r"/upload/(?:[a-z]_[^/]+/)?(?:v\d+/)?(.+?)(?:\.[a-zA-Z0-9]+)?(?:\?.*)?$"
)


def public_id_from_url(url: str) -> str | None:
    """Best-effort extraction of a Cloudinary public_id from a secure_url,
    used so we can delete the old asset when a file is replaced/removed."""
    if not url:
        return None
    match = _PUBLIC_ID_RE.search(url)
    if not match:
        logger.warning("Could not extract a Cloudinary public_id from URL: %s", url)
        return None
    return match.group(1)


def delete_asset(url: str, resource_type: str = "image") -> None:
    """Best-effort delete — failures are swallowed so a broken/expired
    Cloudinary credential never blocks the user's actual request (e.g.
    replacing a cover image should still succeed even if cleanup fails).
    Failures are still logged so orphaned assets are debuggable instead of
    silently piling up."""
    if not is_cloudinary_url(url):
        # Not a Cloudinary asset (empty, or a leftover local path from
        # before the migration to cloud storage) — nothing to delete.
        return
    public_id = public_id_from_url(url)
    if not public_id or not _is_configured():
        return
    try:
        result = cloudinary.uploader.destroy(
            public_id, resource_type=resource_type, timeout=_UPLOAD_TIMEOUT_SECONDS
        )
        if result.get("result") not in ("ok", "not found"):
            logger.warning("Cloudinary destroy(%s) returned unexpected result: %s", public_id, result)
    except Exception as exc:
        logger.warning("Cloudinary destroy(%s) failed: %s", public_id, exc)


def is_cloudinary_url(value: str) -> bool:
    return bool(value) and "res.cloudinary.com" in value
