from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff
from ..audit import write_audit_log

router = APIRouter(prefix="/api/reports", tags=["reports"])

VALID_CONTENT_TYPES = {"review", "discussion_post", "discussion_reply", "user", "safety_concern", "message"}


def _snippet(text: str, length: int = 160) -> str:
    text = (text or "").strip()
    return text if len(text) <= length else text[:length].rstrip() + "…"


def _content_lookup(db: Session, content_type: str, content_id: int):
    """Returns (preview_text, author_name, exists) for a reported piece of content,
    so moderators can act on a report without hunting the content down elsewhere."""
    if content_type == "review":
        row = db.query(models.Review).filter(models.Review.id == content_id).first()
        if not row:
            return None, None, False
        author = db.query(models.User).filter(models.User.id == row.user_id).first()
        return _snippet(row.review_text), author.full_name if author else "Unknown", True
    if content_type == "discussion_post":
        row = db.query(models.DiscussionPost).filter(models.DiscussionPost.id == content_id).first()
        if not row:
            return None, None, False
        author = db.query(models.User).filter(models.User.id == row.user_id).first()
        preview = f"{row.title}: {row.content}"
        return _snippet(preview), author.full_name if author else "Unknown", not row.is_removed
    if content_type == "discussion_reply":
        row = db.query(models.DiscussionReply).filter(models.DiscussionReply.id == content_id).first()
        if not row:
            return None, None, False
        author = db.query(models.User).filter(models.User.id == row.user_id).first()
        return _snippet(row.content), author.full_name if author else "Unknown", not row.is_removed
    if content_type == "message":
        row = db.query(models.DirectMessage).filter(models.DirectMessage.id == content_id).first()
        if not row:
            return None, None, False
        author = db.query(models.User).filter(models.User.id == row.sender_id).first()
        return _snippet(row.content), author.full_name if author else "Unknown", True
    if content_type == "user":
        row = db.query(models.User).filter(models.User.id == content_id).first()
        if not row:
            return None, None, False
        return None, row.full_name, row.is_active
    if content_type == "safety_concern":
        # A general safeguarding report with no single piece of content attached
        # (e.g. "someone messaged my child asking to move off-platform").
        return None, None, True
    return None, None, False


def _report_out(db: Session, r: models.ContentReport) -> schemas.ReportOut:
    if r.reporter_id:
        reporter = db.query(models.User).filter(models.User.id == r.reporter_id).first()
        reporter_name = reporter.full_name if reporter else "Unknown"
    else:
        reporter_name = f"Anonymous ({r.reporter_email})" if r.reporter_email else "Anonymous"
    preview, author, exists = _content_lookup(db, r.content_type, r.content_id)
    return schemas.ReportOut(
        id=r.id, reporter_id=r.reporter_id, reporter_name=reporter_name,
        content_type=r.content_type, content_id=r.content_id, reason=r.reason,
        status=r.status, created_at=r.created_at,
        content_preview=preview, content_author=author, content_exists=exists,
    )


@router.post("/safety-concern", response_model=schemas.ReportOut, status_code=201)
def report_safety_concern(payload: schemas.SafetyConcernCreate, db: Session = Depends(get_db)):
    """Public, unauthenticated endpoint — anyone (a worried parent, a visitor,
    a member who'd rather not log in first) can flag a safety concern."""
    report = models.ContentReport(
        reporter_id=None, reporter_email=payload.reporter_email,
        content_type="safety_concern", content_id=None, reason=payload.reason,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _report_out(db, report)


@router.post("", response_model=schemas.ReportOut, status_code=201)
def report_content(
    payload: schemas.ReportCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.content_type not in VALID_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid content type")
    if payload.content_type == "message":
        msg = db.query(models.DirectMessage).filter(models.DirectMessage.id == payload.content_id).first()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        if current_user.id not in (msg.sender_id, msg.recipient_id):
            raise HTTPException(status_code=403, detail="You can only report messages in your own conversations")
    report = models.ContentReport(reporter_id=current_user.id, **payload.model_dump())
    db.add(report)
    db.commit()
    db.refresh(report)
    return _report_out(db, report)


@router.get("", response_model=List[schemas.ReportOut])
def list_reports(
    status: Optional[str] = "pending",
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    q = db.query(models.ContentReport)
    if status and status != "all":
        q = q.filter(models.ContentReport.status == status)
    reports = q.order_by(models.ContentReport.created_at.desc()).all()
    return [_report_out(db, r) for r in reports]


@router.put("/{report_id}/resolve")
def resolve_report(
    report_id: int,
    status: str,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    if status not in ("reviewed", "dismissed"):
        raise HTTPException(status_code=400, detail="Invalid status")
    report = db.query(models.ContentReport).filter(models.ContentReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    report.status = status
    report.reviewed_by = current_user.id
    db.commit()
    write_audit_log(db, current_user.id, f"report.{status}", "content_report", report_id)
    return {"message": f"Report marked {status}"}


@router.post("/{report_id}/remove-content")
def remove_reported_content(
    report_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """One-click moderator action: takes down the reported content (soft-delete for
    discussion posts/replies, hard delete for reviews) and marks the report reviewed,
    so staff don't have to separately hunt down the content in another tab."""
    report = db.query(models.ContentReport).filter(models.ContentReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    removed = False
    if report.content_type == "review":
        row = db.query(models.Review).filter(models.Review.id == report.content_id).first()
        if row:
            db.delete(row)
            removed = True
    elif report.content_type == "discussion_post":
        row = db.query(models.DiscussionPost).filter(models.DiscussionPost.id == report.content_id).first()
        if row:
            row.is_removed = True
            removed = True
    elif report.content_type == "discussion_reply":
        row = db.query(models.DiscussionReply).filter(models.DiscussionReply.id == report.content_id).first()
        if row:
            row.is_removed = True
            removed = True
    elif report.content_type == "message":
        row = db.query(models.DirectMessage).filter(models.DirectMessage.id == report.content_id).first()
        if row:
            db.delete(row)
            removed = True
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    report.status = "reviewed"
    report.reviewed_by = current_user.id
    db.commit()
    write_audit_log(
        db, current_user.id, "report.remove_content", report.content_type, report.content_id,
        f"via report #{report.id}" + ("" if removed else " (content already gone)"),
    )
    return {"message": "Content removed and report marked reviewed" if removed else "Content was already removed; report marked reviewed"}
