"""
Profile-picture storage for staff accounts (admin/moderator/mentor).

Members never upload a real photo of themselves here — for child-safety
reasons they instead pick one of a small set of preset illustrated avatars
(see PRESET_AVATARS below), which is enforced in auth_router. Only staff,
who are verified adults running the platform, can upload an actual image.

Uploaded photos live in Cloudinary (not local disk) so they survive
redeploys/restarts on hosts with an ephemeral filesystem. user.profile_picture
stores either a preset key (e.g. "avatar_female_2") or "upload:<cloudinary
secure_url>" for a staff-uploaded photo.
"""
from fastapi import UploadFile
from sqlalchemy.orm import Session

from . import models
from .cloud_storage import upload_bytes, delete_asset, read_upload, looks_like_image, UploadValidationError

MAX_AVATAR_BYTES = 3 * 1024 * 1024  # 3MB
ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

# Illustrated, non-photographic avatars members choose from instead of
# uploading a real picture. Files live at frontend/img/avatars/<key>.svg.
PRESET_AVATARS = [
    "avatar_male_1", "avatar_male_2", "avatar_male_3", "avatar_male_4",
    "avatar_female_1", "avatar_female_2", "avatar_female_3", "avatar_female_4",
]


def attach_staff_avatar(db: Session, user: models.User, upload: UploadFile) -> None:
    raw = read_upload(upload, MAX_AVATAR_BYTES, ALLOWED_EXTENSIONS, field_label="Profile photo")
    if not looks_like_image(raw):
        raise UploadValidationError("That file doesn't look like a valid image")

    # Remove the previous uploaded photo, if any (skip if it was a preset key).
    old_url = None
    if user.profile_picture and user.profile_picture.startswith("upload:"):
        old_url = user.profile_picture.split("upload:", 1)[1]

    result = upload_bytes(raw, folder="avatars", original_filename=upload.filename, resource_type="image")

    if old_url:
        delete_asset(old_url, resource_type="image")

    user.profile_picture = f"upload:{result['secure_url']}"


def avatar_url(profile_picture: str):
    """Returns the Cloudinary URL for an 'upload:<url>' profile_picture value,
    or None if it isn't an uploaded photo (e.g. it's a member's preset key)."""
    if not profile_picture or not profile_picture.startswith("upload:"):
        return None
    return profile_picture.split("upload:", 1)[1]
