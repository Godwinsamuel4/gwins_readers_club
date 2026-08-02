import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff, get_current_user_optional

router = APIRouter(prefix="/api/certificates", tags=["certificates"])

CERT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "generated_certificates")
os.makedirs(CERT_DIR, exist_ok=True)

# .../readers-club/backend/app/routers/certificates_router.py -> .../readers-club
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
LOGO_PATH = os.path.join(_PROJECT_ROOT, "frontend", "img", "logo.png")

# Base URL the QR code points to. Set RC_PUBLIC_URL in production (e.g.
# https://readersclub.example.org); defaults to local dev.
PUBLIC_URL = os.environ.get("RC_PUBLIC_URL", "http://localhost:8000").rstrip("/")

GOLD = HexColor("#D79A3B")
PURPLE = HexColor("#17223D")
PURPLE_DARK = HexColor("#0F1729")
WHITE = HexColor("#F2ECDC")


def _draw_qr(c: canvas.Canvas, url: str, x: float, y: float, size: float):
    widget = QrCodeWidget(url)
    b = widget.getBounds()
    w, h = b[2] - b[0], b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    renderPDF.draw(d, c, x, y)


def _render_certificate_pdf(cert: models.Certificate, user_name: str) -> str:
    filename = f"certificate_{cert.id}.pdf"
    path = os.path.join(CERT_DIR, filename)
    c = canvas.Canvas(path, pagesize=landscape(A4))
    width, height = landscape(A4)

    # ---- Background + double border (authenticity framing) ----
    c.setFillColor(PURPLE)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setStrokeColor(GOLD)
    c.setLineWidth(3)
    c.rect(22, 22, width - 44, height - 44, fill=0)
    c.setLineWidth(0.75)
    c.rect(32, 32, width - 64, height - 64, fill=0)

    # ---- Brand logo ----
    if os.path.exists(LOGO_PATH):
        try:
            img = ImageReader(LOGO_PATH)
            logo_h = 62
            iw, ih = img.getSize()
            logo_w = logo_h * (iw / ih)
            c.drawImage(img, width / 2 - logo_w / 2, height - 105, width=logo_w, height=logo_h,
                        mask="auto", preserveAspectRatio=True)
        except Exception:
            pass

    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(width / 2, height - 128, "GWIN'S READERS CLUB")

    c.setFillColor(WHITE)
    c.setFont("Helvetica", 15)
    c.drawCentredString(width / 2, height - 155, "Certificate of Achievement")

    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(width / 2 - 90, height - 165, width / 2 + 90, height - 165)

    c.setFont("Helvetica", 13)
    c.drawCentredString(width / 2, height - 205, "This certificate is proudly presented to")

    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(width / 2, height - 245, user_name)

    c.setFillColor(WHITE)
    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, height - 278, cert.title)

    # ---- Signature block ----
    sig_y = 118
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.75)
    c.line(width / 2 - 160, sig_y, width / 2 - 40, sig_y)
    c.line(width / 2 + 40, sig_y, width / 2 + 160, sig_y)
    c.setFont("Helvetica-Oblique", 16)
    c.setFillColor(WHITE)
    c.drawCentredString(width / 2 - 100, sig_y + 6, "Gwin's Readers Club")
    c.drawCentredString(width / 2 + 100, sig_y + 6, cert.issued_at.strftime("%d %b %Y"))
    c.setFont("Helvetica", 9)
    c.drawCentredString(width / 2 - 100, sig_y - 12, "Program Director")
    c.drawCentredString(width / 2 + 100, sig_y - 12, "Date Issued")

    # ---- Gold seal (bottom-right) ----
    seal_x, seal_y, seal_r = width - 100, 95, 34
    c.setFillColor(GOLD)
    c.circle(seal_x, seal_y, seal_r, fill=1, stroke=0)
    c.setFillColor(PURPLE_DARK)
    c.circle(seal_x, seal_y, seal_r - 5, fill=1, stroke=0)
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(seal_x, seal_y + 8, "OFFICIAL")
    c.drawCentredString(seal_x, seal_y - 2, "GWIN'S")
    c.drawCentredString(seal_x, seal_y - 12, "READERS CLUB")

    # ---- QR verification (bottom-left) + footer text ----
    verify_url = f"{PUBLIC_URL}/verify.html?code={cert.verification_code}"
    _draw_qr(c, verify_url, 55, 55, 55)

    c.setFillColor(WHITE)
    c.setFont("Helvetica", 8.5)
    c.drawString(
        120, 80,
        f"Certificate ID: {cert.id}   •   Verification Code: {cert.verification_code}"
    )
    c.drawString(120, 68, "Scan the QR code or visit the link below to confirm this certificate is genuine.")
    c.setFillColor(GOLD)
    c.drawString(120, 56, verify_url)

    c.showPage()
    c.save()
    return path


def _issue(db: Session, user_id: int, certificate_type: str, title: str, related_id: int = None):
    existing = db.query(models.Certificate).filter(
        models.Certificate.user_id == user_id,
        models.Certificate.certificate_type == certificate_type,
        models.Certificate.related_id == related_id,
    ).first()
    if existing:
        return existing
    cert = models.Certificate(
        user_id=user_id, certificate_type=certificate_type, title=title, related_id=related_id,
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)
    return cert


@router.get("/verify/{code}", response_model=schemas.CertificateVerifyOut)
def verify_certificate(code: str, db: Session = Depends(get_db)):
    """Public endpoint (no auth) behind the QR code / verify.html page.
    Deliberately returns only what's needed to confirm authenticity —
    no email, no internal user ID."""
    cert = db.query(models.Certificate).filter(models.Certificate.verification_code == code.strip().upper()).first()
    if not cert:
        return schemas.CertificateVerifyOut(valid=False, message="No certificate found with this verification code.")
    user = db.query(models.User).filter(models.User.id == cert.user_id).first()
    if cert.revoked:
        return schemas.CertificateVerifyOut(
            valid=False, recipient_name=user.full_name if user else None, title=cert.title,
            certificate_type=cert.certificate_type, issued_at=cert.issued_at, revoked=True,
            message="This certificate has been revoked and is no longer valid.",
        )
    return schemas.CertificateVerifyOut(
        valid=True, recipient_name=user.full_name if user else None, title=cert.title,
        certificate_type=cert.certificate_type, issued_at=cert.issued_at, revoked=False,
        message="This is a genuine certificate issued by Gwin's Readers Club.",
    )
@router.get("", response_model=List[schemas.CertificateOut])
def list_my_certificates(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Certificate).filter(
        models.Certificate.user_id == current_user.id
    ).order_by(models.Certificate.issued_at.desc()).all()


@router.post("/issue", response_model=schemas.CertificateOut, status_code=201)
def issue_certificate_manual(
    user_id: int,
    certificate_type: str,
    title: str,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Admin/moderator manually issues a certificate (e.g., discussion participation)."""
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return _issue(db, user_id, certificate_type, title)


@router.get("/{certificate_id}/download")
def download_certificate(
    certificate_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cert = db.query(models.Certificate).filter(models.Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not your certificate")
    if cert.revoked:
        raise HTTPException(status_code=410, detail="This certificate has been revoked")

    user = db.query(models.User).filter(models.User.id == cert.user_id).first()
    path = _render_certificate_pdf(cert, user.full_name)
    return FileResponse(path, media_type="application/pdf", filename=f"ReadersClub_Certificate_{cert.id}.pdf")


@router.put("/{certificate_id}/revoke", response_model=schemas.CertificateOut)
def revoke_certificate(
    certificate_id: int,
    reason: str = "",
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    cert = db.query(models.Certificate).filter(models.Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    cert.revoked = True
    cert.revoked_reason = reason or None
    db.commit()
    db.refresh(cert)
    return cert


@router.put("/{certificate_id}/reinstate", response_model=schemas.CertificateOut)
def reinstate_certificate(
    certificate_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    cert = db.query(models.Certificate).filter(models.Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    cert.revoked = False
    cert.revoked_reason = None
    db.commit()
    db.refresh(cert)
    return cert
