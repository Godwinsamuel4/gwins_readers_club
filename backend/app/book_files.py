"""
Shared book-file storage helpers.

Both the admin panel's book CRUD (admin_router) and the member-facing book
submission flow (library_router's /books/submit) need to: validate a
book-file/cover upload, upload it to Cloudinary, and auto-extract plain text
from it for the online reader. That logic used to live only in admin_router
— it's pulled out here so it's defined once and both routers call the same
code instead of drifting apart over time.

book.file_path / book.cover_image now store Cloudinary secure_urls (not
local filesystem paths) despite the field names — renaming the columns
would mean an extra migration for no functional benefit, so we kept them.
"""
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from . import models
from .file_extract import detect_format, extract_text
from .cloud_storage import upload_bytes, delete_asset, read_upload, looks_like_image, UploadValidationError

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB cap for book files
MAX_COVER_BYTES = 5 * 1024 * 1024

_BOOK_EXTENSIONS = (".txt", ".pdf", ".docx", ".epub")
_COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def attach_book_file(db: Session, book: models.Book, upload: UploadFile) -> None:
    """Validate + upload a book's source file to Cloudinary and extract its
    text into book.content. Raises HTTPException on bad format / oversized
    upload."""
    fmt = detect_format(upload.filename)
    if not fmt:
        raise HTTPException(
            status_code=400,
            detail="Unsupported book file format. Supported formats: txt, pdf, docx, epub",
        )
    raw = read_upload(upload, MAX_UPLOAD_BYTES, _BOOK_EXTENSIONS, field_label="Book file")

    old_url = book.file_path

    # Book files aren't images, so store them as Cloudinary "raw" resources
    # rather than letting resource_type="auto" try to treat a .docx/.epub
    # as an image.
    result = upload_bytes(raw, folder="books", original_filename=upload.filename, resource_type="raw")

    if old_url:
        delete_asset(old_url, resource_type="raw")

    book.file_path = result["secure_url"]
    book.file_format = fmt
    book.file_original_name = upload.filename
    extracted = extract_text(raw, fmt)
    if extracted:
        book.content = extracted


def attach_cover_image(db: Session, book: models.Book, upload: UploadFile) -> None:
    raw = read_upload(upload, MAX_COVER_BYTES, _COVER_EXTENSIONS, field_label="Cover image")
    if not looks_like_image(raw):
        raise UploadValidationError("That file doesn't look like a valid image")

    old_url = book.cover_image

    result = upload_bytes(raw, folder="book_covers", original_filename=upload.filename, resource_type="image")

    if old_url:
        delete_asset(old_url, resource_type="image")

    book.cover_image = result["secure_url"]


def delete_book_files(book: models.Book) -> None:
    if book.file_path:
        delete_asset(book.file_path, resource_type="raw")
    if book.cover_image:
        delete_asset(book.cover_image, resource_type="image")
