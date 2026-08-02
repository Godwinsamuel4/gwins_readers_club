from datetime import datetime, timedelta, date
from io import StringIO
import csv
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import require_admin, require_staff
from ..audit import write_audit_log
from ..cache import cache_get, cache_set, cache_invalidate
from ..book_files import (
    attach_book_file as _attach_book_file,
    attach_cover_image as _attach_cover_image,
    delete_book_files as _delete_book_files,
)
from ..cloud_storage import delete_asset as _delete_asset

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _book_out(db: Session, book: models.Book) -> schemas.BookOut:
    agg = db.query(
        func.avg(models.Review.rating), func.count(models.Review.id)
    ).filter(models.Review.book_id == book.id).first()
    avg_rating, count = agg[0], agg[1]
    data = schemas.BookOut.model_validate(book).model_dump()
    data["average_rating"] = round(avg_rating, 1) if avg_rating else None
    data["review_count"] = count or 0
    return schemas.BookOut(**data)


@router.get("/stats", response_model=schemas.AdminStats)
def dashboard_stats(
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    cached_stats = cache_get("admin_stats")
    if cached_stats is not None:
        return cached_stats

    total_members = db.query(models.User).filter(models.User.role == "member").count()
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    active_readers = db.query(models.ReadingProgress.user_id).filter(
        models.ReadingProgress.last_read_at >= thirty_days_ago
    ).distinct().count()
    books_uploaded = db.query(models.Book).count()
    books_completed_total = db.query(models.ReadingProgress).filter(
        models.ReadingProgress.status == "completed"
    ).count()
    reviews_total = db.query(models.Review).count()
    discussion_posts_total = db.query(models.DiscussionPost).filter(
        models.DiscussionPost.is_removed == False  # noqa: E712
    ).count()
    pending_reports = db.query(models.ContentReport).filter(
        models.ContentReport.status == "pending"
    ).count()
    pending_book_submissions = db.query(models.Book).filter(
        models.Book.status == "pending"
    ).count()
    active_clubs = db.query(models.ReadingClub).count()
    today = date.today()
    upcoming_live_sessions = db.query(models.LiveSession).filter(
        models.LiveSession.is_cancelled == False,  # noqa: E712
        models.LiveSession.scheduled_at >= datetime.utcnow(),
    ).count()
    active_mentors = db.query(models.MentorProfile).filter(
        models.MentorProfile.is_accepting_mentees == True  # noqa: E712
    ).count()
    open_challenges = db.query(models.Challenge).filter(
        models.Challenge.end_date >= today
    ).count()
    certificates_issued = db.query(models.Certificate).filter(
        models.Certificate.revoked == False  # noqa: E712
    ).count()

    result = schemas.AdminStats(
        total_members=total_members,
        active_readers=active_readers,
        books_uploaded=books_uploaded,
        books_completed_total=books_completed_total,
        reviews_total=reviews_total,
        discussion_posts_total=discussion_posts_total,
        pending_reports=pending_reports,
        pending_book_submissions=pending_book_submissions,
        active_clubs=active_clubs,
        upcoming_live_sessions=upcoming_live_sessions,
        active_mentors=active_mentors,
        open_challenges=open_challenges,
        certificates_issued=certificates_issued,
    )
    cache_set("admin_stats", result, ttl_seconds=30)
    return result


@router.get("/users", response_model=List[schemas.UserOut])
def list_users(
    role: Optional[str] = None,
    search: Optional[str] = None,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    q = db.query(models.User)
    if role:
        q = q.filter(models.User.role == role)
    if search:
        like = f"%{search}%"
        q = q.filter((models.User.full_name.ilike(like)) | (models.User.email.ilike(like)))
    return q.order_by(models.User.created_at.desc()).all()


@router.get("/users/export")
def export_users_csv(
    role: Optional[str] = None,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    q = db.query(models.User)
    if role:
        q = q.filter(models.User.role == role)
    users = q.order_by(models.User.created_at.asc()).all()

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "full_name", "email", "role", "is_active", "created_at"])
    for u in users:
        writer.writerow([u.id, u.full_name, u.email, u.role, u.is_active, u.created_at.isoformat()])
    buffer.seek(0)

    write_audit_log(db, current_user.id, "user.export", "user", None, f"{len(users)} members exported")
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=readers_club_members.csv"},
    )


@router.put("/users/{user_id}/role")
def change_user_role(
    user_id: int,
    role: str,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if role not in ("admin", "moderator", "mentor", "member"):
        raise HTTPException(status_code=400, detail="Invalid role")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role
    user.role = role
    db.commit()
    write_audit_log(db, current_user.id, "user.role_change", "user", user_id, f"{old_role} -> {role}")
    return {"message": f"{user.full_name} is now {role}"}


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: int,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot remove your own account")
    removed_name = user.full_name
    db.delete(user)
    db.commit()
    write_audit_log(db, current_user.id, "user.remove", "user", user_id, removed_name)
    return {"message": "User removed"}


@router.put("/users/{user_id}/reactivate")
def reactivate_user(
    user_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Reactivate a member's self-deactivated account (distinct from restoring an admin-removed one)."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    db.commit()
    write_audit_log(db, current_user.id, "user.reactivate", "user", user_id, user.full_name)
    return {"message": f"{user.full_name}'s account has been reactivated"}


@router.get("/audit-logs", response_model=List[schemas.AuditLogOut])
def list_audit_logs(
    action: Optional[str] = None,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    # Staff (admins and moderators) can view the audit trail — moderators mostly
    # generate entries here themselves via content/report actions, and shared
    # visibility makes moderation more accountable and coordinated.
    q = db.query(models.AuditLog)
    if action:
        q = q.filter(models.AuditLog.action == action)
    logs = q.order_by(models.AuditLog.created_at.desc()).limit(200).all()
    out = []
    for l in logs:
        actor = db.query(models.User).filter(models.User.id == l.actor_id).first() if l.actor_id else None
        out.append(schemas.AuditLogOut(
            id=l.id, actor_id=l.actor_id, actor_name=actor.full_name if actor else "System",
            action=l.action, target_type=l.target_type, target_id=l.target_id,
            details=l.details, created_at=l.created_at,
        ))
    return out


# =====================================================================
# Book management: full CRUD + multi-format file upload (txt/pdf/docx/epub)
# =====================================================================

@router.get("/books", response_model=List[schemas.BookOut])
def admin_list_books(
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    q = db.query(models.Book)
    if search:
        like = f"%{search}%"
        q = q.filter((models.Book.title.ilike(like)) | (models.Book.author.ilike(like)))
    if category:
        q = q.filter(models.Book.category == category)
    if status:
        q = q.filter(models.Book.status == status)
    books = q.order_by(models.Book.created_at.desc()).offset(offset).limit(min(limit, 200)).all()
    return [_book_out(db, b) for b in books]


@router.post("/books", response_model=schemas.BookOut, status_code=201)
def admin_create_book(
    title: str = Form(...),
    author: str = Form(...),
    category: str = Form(...),
    publisher: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    language: str = Form("English"),
    number_of_pages: int = Form(0),
    reading_time_minutes: int = Form(0),
    publication_year: Optional[int] = Form(None),
    cover_color: str = Form("#4b2e83"),
    content: Optional[str] = Form(""),
    is_featured: bool = Form(False),
    book_file: Optional[UploadFile] = File(None),
    cover_image: Optional[UploadFile] = File(None),
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Create a book. If book_file is attached (txt/pdf/docx/epub), its text is
    auto-extracted into `content` for the online reader, and the original file
    is kept on disk for download. A separate cover_image can also be attached."""
    book = models.Book(
        title=title, author=author, category=category, publisher=publisher,
        description=description, language=language, number_of_pages=number_of_pages,
        reading_time_minutes=reading_time_minutes, publication_year=publication_year,
        cover_color=cover_color, content=content or "", is_featured=is_featured,
        added_by=current_user.id,
    )
    db.add(book)
    db.commit()
    db.refresh(book)

    if book_file is not None:
        _attach_book_file(db, book, book_file)
    if cover_image is not None:
        _attach_cover_image(db, book, cover_image)

    try:
        db.commit()
    except Exception:
        db.rollback()
        if book_file is not None:
            _delete_asset(book.file_path, resource_type="raw")
        if cover_image is not None:
            _delete_asset(book.cover_image, resource_type="image")
        raise
    db.refresh(book)
    cache_invalidate("admin_stats")
    write_audit_log(db, current_user.id, "book.create", "book", book.id, book.title)
    return _book_out(db, book)


@router.put("/books/{book_id}", response_model=schemas.BookOut)
def admin_update_book(
    book_id: int,
    payload: schemas.BookUpdate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(book, field, value)
    db.commit()
    db.refresh(book)
    cache_invalidate("admin_stats")
    write_audit_log(db, current_user.id, "book.update", "book", book.id, book.title)
    return _book_out(db, book)


@router.delete("/books/{book_id}")
def admin_delete_book(
    book_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    title = book.title
    _delete_book_files(book)
    db.delete(book)
    db.commit()
    cache_invalidate("admin_stats")
    write_audit_log(db, current_user.id, "book.delete", "book", book_id, title)
    return {"message": "Book deleted"}


@router.post("/books/bulk-delete")
def admin_bulk_delete_books(
    payload: schemas.BulkDeleteRequest,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    deleted = 0
    for book_id in payload.ids:
        book = db.query(models.Book).filter(models.Book.id == book_id).first()
        if book:
            _delete_book_files(book)
            db.delete(book)
            deleted += 1
    db.commit()
    cache_invalidate("admin_stats")
    write_audit_log(db, current_user.id, "book.bulk_delete", "book", None, f"{deleted} books removed")
    return {"message": f"{deleted} book(s) deleted"}


@router.post("/books/{book_id}/approve", response_model=schemas.BookOut)
def admin_approve_book(
    book_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Approve a pending member book submission — it becomes visible in
    public browsing/search and the submitter is notified."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    book.status = "approved"
    book.rejection_reason = None
    db.commit()
    db.refresh(book)
    cache_invalidate("admin_stats")
    write_audit_log(db, current_user.id, "book.approve", "book", book.id, book.title)
    if book.added_by:
        db.add(models.Notification(
            user_id=book.added_by,
            notif_type="library",
            message=f'Your book submission "{book.title}" was approved and is now live in the library! 🎉',
        ))
        db.commit()
    return _book_out(db, book)


@router.post("/books/{book_id}/reject", response_model=schemas.BookOut)
def admin_reject_book(
    book_id: int,
    payload: schemas.BookRejectRequest,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Reject a pending member book submission with a reason — it stays out
    of the public library and the submitter is notified why."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    book.status = "rejected"
    book.rejection_reason = payload.reason
    db.commit()
    db.refresh(book)
    cache_invalidate("admin_stats")
    write_audit_log(db, current_user.id, "book.reject", "book", book.id, f"{book.title}: {payload.reason}")
    if book.added_by:
        db.add(models.Notification(
            user_id=book.added_by,
            notif_type="library",
            message=f'Your book submission "{book.title}" wasn\'t approved: {payload.reason}',
        ))
        db.commit()
    return _book_out(db, book)


@router.post("/books/{book_id}/file", response_model=schemas.BookOut)
def admin_upload_book_file(
    book_id: int,
    book_file: UploadFile = File(...),
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Upload or replace a book's source file (txt/pdf/docx/epub). Text is
    re-extracted into the online reader content automatically."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    _attach_book_file(db, book, book_file)
    try:
        db.commit()
    except Exception:
        db.rollback()
        _delete_asset(book.file_path, resource_type="raw")
        raise
    db.refresh(book)
    write_audit_log(db, current_user.id, "book.file_upload", "book", book.id, book.file_original_name)
    return _book_out(db, book)


@router.post("/books/{book_id}/cover", response_model=schemas.BookOut)
def admin_upload_book_cover(
    book_id: int,
    cover_image: UploadFile = File(...),
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    _attach_cover_image(db, book, cover_image)
    try:
        db.commit()
    except Exception:
        db.rollback()
        _delete_asset(book.cover_image, resource_type="image")
        raise
    db.refresh(book)
    write_audit_log(db, current_user.id, "book.cover_upload", "book", book.id, book.title)
    return _book_out(db, book)


@router.get("/books/{book_id}/file")
def admin_download_book_file(
    book_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book or not book.file_path:
        raise HTTPException(status_code=404, detail="No source file uploaded for this book")
    return RedirectResponse(book.file_path)


@router.get("/books/{book_id}/cover")
def get_book_cover(book_id: int, db: Session = Depends(get_db)):
    """Public — used to render admin/library cover thumbnails."""
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book or not book.cover_image:
        raise HTTPException(status_code=404, detail="No cover image for this book")
    return RedirectResponse(book.cover_image)


# =====================================================================
# Dynamic category management
# =====================================================================

@router.get("/categories", response_model=List[schemas.CategoryOut])
def admin_list_categories(
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return db.query(models.Category).order_by(models.Category.name.asc()).all()


@router.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def admin_create_category(
    payload: schemas.CategoryCreate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    existing = db.query(models.Category).filter(models.Category.name.ilike(name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="That category already exists")
    cat = models.Category(name=name)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    write_audit_log(db, current_user.id, "category.create", "category", cat.id, cat.name)
    return cat


@router.put("/categories/{category_id}", response_model=schemas.CategoryOut)
def admin_update_category(
    category_id: int,
    payload: schemas.CategoryCreate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    cat = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    old_name = cat.name
    cat.name = payload.name.strip()
    db.commit()
    db.refresh(cat)
    write_audit_log(db, current_user.id, "category.rename", "category", cat.id, f"{old_name} -> {cat.name}")
    return cat


@router.delete("/categories/{category_id}")
def admin_delete_category(
    category_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    cat = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(cat)
    db.commit()
    write_audit_log(db, current_user.id, "category.delete", "category", category_id, cat.name)
    return {"message": "Category deleted"}


# =====================================================================
# Challenge management (list/update/delete — create already existed)
# =====================================================================

def _challenge_admin_out(db: Session, c: models.Challenge) -> schemas.ChallengeOut:
    count = db.query(models.ChallengeParticipant).filter(
        models.ChallengeParticipant.challenge_id == c.id
    ).count()
    data = schemas.ChallengeOut.model_validate(c).model_dump()
    data["participant_count"] = count
    return schemas.ChallengeOut(**data)


@router.get("/challenges", response_model=List[schemas.ChallengeOut])
def admin_list_challenges(
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    challenges = db.query(models.Challenge).order_by(models.Challenge.start_date.desc()).all()
    return [_challenge_admin_out(db, c) for c in challenges]


@router.put("/challenges/{challenge_id}", response_model=schemas.ChallengeOut)
def admin_update_challenge(
    challenge_id: int,
    payload: schemas.ChallengeUpdate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    challenge = db.query(models.Challenge).filter(models.Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(challenge, field, value)
    db.commit()
    db.refresh(challenge)
    write_audit_log(db, current_user.id, "challenge.update", "challenge", challenge.id, challenge.name)
    return _challenge_admin_out(db, challenge)


@router.delete("/challenges/{challenge_id}")
def admin_delete_challenge(
    challenge_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    challenge = db.query(models.Challenge).filter(models.Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    name = challenge.name
    db.query(models.ChallengeParticipant).filter(
        models.ChallengeParticipant.challenge_id == challenge_id
    ).delete()
    db.delete(challenge)
    db.commit()
    write_audit_log(db, current_user.id, "challenge.delete", "challenge", challenge_id, name)
    return {"message": "Challenge deleted"}


# =====================================================================
# Mentor profile management
# =====================================================================

@router.get("/mentors", response_model=List[schemas.MentorProfileOut])
def admin_list_mentors(
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Lists every mentor profile (accepting or not), unlike the public
    /api/mentors endpoint which only shows those currently accepting mentees."""
    profiles = db.query(models.MentorProfile).all()
    out = []
    for p in profiles:
        user = db.query(models.User).filter(models.User.id == p.user_id).first()
        agg = db.query(
            func.avg(models.MentorRating.rating), func.count(models.MentorRating.id)
        ).filter(models.MentorRating.mentor_id == p.user_id).first()
        out.append(schemas.MentorProfileOut(
            user_id=p.user_id, mentor_name=user.full_name if user else "Unknown",
            specialties=p.specialties, bio=p.bio, is_accepting_mentees=p.is_accepting_mentees,
            average_rating=round(agg[0], 1) if agg[0] else None, rating_count=agg[1] or 0,
        ))
    return out


@router.put("/mentors/{user_id}", response_model=schemas.MentorProfileOut)
def admin_update_mentor(
    user_id: int,
    specialties: Optional[str] = None,
    bio: Optional[str] = None,
    is_accepting_mentees: Optional[bool] = None,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    # Unlike the mentor's own become-a-mentor endpoint, staff can also use this to
    # CREATE a profile on a mentor's behalf, so a promoted member's listing can go
    # live immediately instead of waiting on the member to self-apply.
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != "mentor":
        raise HTTPException(
            status_code=400,
            detail="This user's account role is not 'mentor' yet - set their role first in the Members tab",
        )
    profile = db.query(models.MentorProfile).filter(models.MentorProfile.user_id == user_id).first()
    created = False
    if not profile:
        profile = models.MentorProfile(user_id=user_id, is_accepting_mentees=True)
        db.add(profile)
        created = True
    if specialties is not None:
        profile.specialties = specialties
    if bio is not None:
        profile.bio = bio
    if is_accepting_mentees is not None:
        profile.is_accepting_mentees = is_accepting_mentees
    db.commit()
    db.refresh(profile)
    write_audit_log(
        db, current_user.id, "mentor.create" if created else "mentor.update",
        "mentor_profile", user_id, user.full_name,
    )
    agg = db.query(
        func.avg(models.MentorRating.rating), func.count(models.MentorRating.id)
    ).filter(models.MentorRating.mentor_id == user_id).first()
    return schemas.MentorProfileOut(
        user_id=profile.user_id, mentor_name=user.full_name,
        specialties=profile.specialties, bio=profile.bio,
        is_accepting_mentees=profile.is_accepting_mentees,
        average_rating=round(agg[0], 1) if agg[0] else None, rating_count=agg[1] or 0,
    )


@router.delete("/mentors/{user_id}")
def admin_remove_mentor_profile(
    user_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Removes the mentor profile (bio/specialties/listing). Does not change
    the user's account role — use the Members tab for that."""
    profile = db.query(models.MentorProfile).filter(models.MentorProfile.user_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Mentor profile not found")
    db.delete(profile)
    db.commit()
    write_audit_log(db, current_user.id, "mentor.remove_profile", "mentor_profile", user_id, "")
    return {"message": "Mentor profile removed"}


# =====================================================================
# Mentorship pairing oversight (list/force-end requests across all mentors)
# =====================================================================

def _mentorship_out(db: Session, r: models.MentorshipRequest) -> schemas.MentorshipRequestOut:
    mentor = db.query(models.User).filter(models.User.id == r.mentor_id).first()
    mentee = db.query(models.User).filter(models.User.id == r.mentee_id).first()
    return schemas.MentorshipRequestOut(
        id=r.id, mentor_id=r.mentor_id, mentor_name=mentor.full_name if mentor else "Unknown",
        mentee_id=r.mentee_id, mentee_name=mentee.full_name if mentee else "Unknown",
        status=r.status, requested_at=r.requested_at,
    )


@router.get("/mentorship-requests", response_model=List[schemas.MentorshipRequestOut])
def admin_list_mentorship_requests(
    status: Optional[str] = None,
    mentor_id: Optional[int] = None,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    # Site-wide view of every mentor/mentee pairing, unlike /api/mentors/requests/mine
    # which only shows a single user's own requests. Lets staff spot mentors who never
    # respond to requests, or step in on a pairing that's gone quiet.
    q = db.query(models.MentorshipRequest)
    if status:
        q = q.filter(models.MentorshipRequest.status == status)
    if mentor_id:
        q = q.filter(models.MentorshipRequest.mentor_id == mentor_id)
    reqs = q.order_by(models.MentorshipRequest.requested_at.desc()).limit(300).all()
    return [_mentorship_out(db, r) for r in reqs]


@router.put("/mentorship-requests/{request_id}/end")
def admin_end_mentorship(
    request_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    # Staff override to end a mentorship pairing directly (e.g. in response to a
    # complaint), without needing either party to end it themselves.
    req = db.query(models.MentorshipRequest).filter(models.MentorshipRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Mentorship request not found")
    req.status = "ended"
    db.commit()
    write_audit_log(db, current_user.id, "mentorship.staff_end", "mentorship_request", request_id)
    return {"message": "Mentorship ended"}


# =====================================================================
# Reviews moderation (site-wide list; edit/delete reuse /api/community)
# =====================================================================

@router.get("/reviews", response_model=List[schemas.ReviewOut])
def admin_list_reviews(
    limit: int = 100,
    offset: int = 0,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reviews = db.query(models.Review).order_by(
        models.Review.created_at.desc()
    ).offset(offset).limit(min(limit, 200)).all()
    out = []
    for r in reviews:
        user = db.query(models.User).filter(models.User.id == r.user_id).first()
        book = db.query(models.Book).filter(models.Book.id == r.book_id).first()
        helpful_count = db.query(models.ReviewHelpfulVote).filter(
            models.ReviewHelpfulVote.review_id == r.id
        ).count()
        out.append(schemas.ReviewOut(
            id=r.id, user_id=r.user_id, reviewer_name=user.full_name if user else "Unknown",
            book_id=r.book_id, book_title=book.title if book else "Unknown book",
            rating=r.rating, lessons_learned=r.lessons_learned, review_text=r.review_text,
            helpful_count=helpful_count, created_at=r.created_at,
        ))
    return out


# =====================================================================
# Discussion moderation (site-wide list including removed posts)
# =====================================================================

@router.get("/discussions", response_model=List[schemas.DiscussionPostOut])
def admin_list_discussions(
    include_removed: bool = True,
    limit: int = 100,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    q = db.query(models.DiscussionPost)
    if not include_removed:
        q = q.filter(models.DiscussionPost.is_removed == False)  # noqa: E712
    posts = q.order_by(models.DiscussionPost.created_at.desc()).limit(min(limit, 200)).all()
    out = []
    for p in posts:
        author = db.query(models.User).filter(models.User.id == p.user_id).first()
        reply_count = db.query(models.DiscussionReply).filter(
            models.DiscussionReply.post_id == p.id
        ).count()
        out.append(schemas.DiscussionPostOut(
            id=p.id, user_id=p.user_id, author_name=author.full_name if author else "Unknown",
            category=p.category, book_id=p.book_id, title=p.title, content=p.content,
            is_pinned=p.is_pinned, is_removed=p.is_removed, created_at=p.created_at, reply_count=reply_count,
        ))
    return out


# =====================================================================
# Certificates — site-wide list (issue/revoke/reinstate already existed)
# =====================================================================

@router.get("/certificates", response_model=List[schemas.CertificateOut])
def admin_list_certificates(
    limit: int = 100,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    certs = db.query(models.Certificate).order_by(
        models.Certificate.issued_at.desc()
    ).limit(min(limit, 300)).all()
    out = []
    for c in certs:
        user = db.query(models.User).filter(models.User.id == c.user_id).first()
        data = schemas.CertificateOut.model_validate(c).model_dump()
        data["user_name"] = user.full_name if user else "Unknown"
        out.append(schemas.CertificateOut(**data))
    return out
