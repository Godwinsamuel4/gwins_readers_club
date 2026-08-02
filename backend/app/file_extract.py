"""
Extracts plain text from an uploaded book file so it can be stored in
Book.content and shown in the online reader, regardless of which format
the admin uploaded (txt, pdf, docx, epub). Extraction is best-effort:
if a format-specific library fails on a malformed file, we fall back to
an empty body rather than raising, so the upload itself still succeeds
and the admin can paste/edit the content manually afterward.
"""
import io
import os

SUPPORTED_FORMATS = {"txt", "pdf", "docx", "epub"}


def detect_format(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return ext if ext in SUPPORTED_FORMATS else ""


def extract_text(file_bytes: bytes, file_format: str) -> str:
    if file_format == "txt":
        return _extract_txt(file_bytes)
    if file_format == "pdf":
        return _extract_pdf(file_bytes)
    if file_format == "docx":
        return _extract_docx(file_bytes)
    if file_format == "epub":
        return _extract_epub(file_bytes)
    return ""


def _extract_txt(file_bytes: bytes) -> str:
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return file_bytes.decode("latin-1", errors="ignore")


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n\n".join(pages).strip()
    except Exception:
        return ""


def _extract_docx(file_bytes: bytes) -> str:
    try:
        import docx
        document = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in document.paragraphs).strip()
    except Exception:
        return ""


def _extract_epub(file_bytes: bytes) -> str:
    try:
        import tempfile
        from ebooklib import epub, ITEM_DOCUMENT
        from bs4 import BeautifulSoup

        # ebooklib's reader needs a real file path, not a stream.
        with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            book = epub.read_epub(tmp_path)
            chunks = []
            for item in book.get_items_of_type(ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n").strip()
                if text:
                    chunks.append(text)
            return "\n\n".join(chunks).strip()
        finally:
            os.unlink(tmp_path)
    except Exception:
        return ""
