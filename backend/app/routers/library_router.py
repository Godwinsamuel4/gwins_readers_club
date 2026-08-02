from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import csv
import io

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, get_current_user_optional, require_staff
from ..cache import cache_get, cache_set, cache_invalidate
from ..book_files import attach_book_file, attach_cover_image
from ..cloud_storage import delete_asset

router = APIRouter(prefix="/api/library", tags=["library"])

CATEGORIES = [
    "Leadership", "Technology", "Entrepreneurship", "Finance", "Christian",
    "Business", "Health", "Education", "History", "Fiction", "Romance",
    "African Literature", "Children's Books", "Science", "Personal Development",
]


def _book_out(db: Session, book: models.Book) -> schemas.BookOut:
    agg = db.query(
        func.avg(models.Review.rating), func.count(models.Review.id)
    ).filter(models.Review.book_id == book.id).first()
    avg_rating, count = agg[0], agg[1]
    data = schemas.BookOut.model_validate(book).model_dump()
    data["average_rating"] = round(avg_rating, 1) if avg_rating else None
    data["review_count"] = count or 0
    return schemas.BookOut(**data)


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    rows = db.query(models.Category).order_by(models.Category.name.asc()).all()
    if rows:
        return [r.name for r in rows]
    return CATEGORIES  # fallback until the categories table has been seeded


@router.get("/books", response_model=List[schemas.BookOut])
def browse_books(
    search: Optional[str] = None,
    category: Optional[str] = None,
    author: Optional[str] = None,
    language: Optional[str] = None,
    sort: Optional[str] = Query(default="recent", pattern="^(recent|popular|title)$"),
    limit: int = Query(default=100, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(models.Book).filter(models.Book.status == "approved")
    if search:
        like = f"%{search}%"
        # Expanded full-text-style search across title/author/description/content,
        # not just title/author — with title/author matches ranked first.
        q = q.filter(or_(
            models.Book.title.ilike(like), models.Book.author.ilike(like),
            models.Book.description.ilike(like), models.Book.content.ilike(like),
        ))
    if category:
        q = q.filter(models.Book.category == category)
    if author:
        q = q.filter(models.Book.author.ilike(f"%{author}%"))
    if language:
        q = q.filter(models.Book.language == language)

    if sort == "popular":
        q = q.order_by(models.Book.view_count.desc())
    elif sort == "title":
        q = q.order_by(models.Book.title.asc())
    else:
        q = q.order_by(models.Book.created_at.desc())

    books = q.offset(offset).limit(limit).all()

    if search:
        like_lower = search.lower()
        books.sort(key=lambda b: 0 if like_lower in b.title.lower() else (1 if like_lower in b.author.lower() else 2))

    return [_book_out(db, b) for b in books]


@router.get("/books/{book_id}/related", response_model=List[schemas.BookOut])
def related_books(book_id: int, db: Session = Depends(get_db)):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    related = db.query(models.Book).filter(
        models.Book.category == book.category, models.Book.id != book_id,
        models.Book.status == "approved",
    ).order_by(models.Book.view_count.desc()).limit(6).all()
    return [_book_out(db, b) for b in related]


@router.post("/books/submit", response_model=schemas.BookOut, status_code=201)
def submit_book(
    title: str = Form(...),
    author: str = Form(...),
    category: str = Form(...),
    publisher: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    language: str = Form("English"),
    publication_year: Optional[int] = Form(None),
    cover_color: str = Form("#4b2e83"),
    book_file: UploadFile = File(...),
    cover_image: Optional[UploadFile] = File(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Member-facing book upload — any logged-in member can submit a book
    (txt/pdf/docx/epub) to the library. Text is auto-extracted for the online
    reader, same as an admin upload. Unlike the admin/staff CRUD, submissions
    through this endpoint always land as status='pending': they stay out of
    public browsing, search, and recommendations until a moderator reviews
    and approves them from the admin Books queue."""
    book = models.Book(
        title=title, author=author, category=category, publisher=publisher,
        description=description, language=language, content="",
        cover_color=cover_color, added_by=current_user.id, status="pending",
    )
    db.add(book)
    db.commit()
    db.refresh(book)

    attach_book_file(db, book, book_file)
    if cover_image is not None:
        attach_cover_image(db, book, cover_image)
    if publication_year:
        book.publication_year = publication_year

    try:
        db.commit()
    except Exception:
        db.rollback()
        # The file(s) already landed on Cloudinary before the DB write
        # failed — clean them up rather than leaving orphaned assets that
        # no book row ever points to.
        delete_asset(book.file_path, resource_type="raw")
        if book.cover_image:
            delete_asset(book.cover_image, resource_type="image")
        raise
    db.refresh(book)
    cache_invalidate("admin_stats")
    return _book_out(db, book)


@router.get("/books/mine", response_model=List[schemas.BookOut])
def my_submissions(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A member's own book submissions, whatever their review status —
    lets someone track what they've uploaded and see approve/reject outcomes."""
    books = db.query(models.Book).filter(
        models.Book.added_by == current_user.id
    ).order_by(models.Book.created_at.desc()).all()
    return [_book_out(db, b) for b in books]


@router.post("/books/bulk-import", response_model=schemas.BulkImportResult)
def bulk_import_books(
    payload: schemas.BulkImportRequest,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Admin bulk import via CSV text posted as a JSON body field (not a query
    param — query strings have length limits that a real book catalog CSV
    would blow past). Expected columns:
    title,author,category,publisher,description,number_of_pages,publication_year
    """
    created, skipped, errors = 0, 0, []
    reader = csv.DictReader(io.StringIO(payload.file_content))
    for i, row in enumerate(reader, start=2):
        title = (row.get("title") or "").strip()
        author = (row.get("author") or "").strip()
        category = (row.get("category") or "").strip()
        if not title or not author or not category:
            errors.append(f"Row {i}: missing required field (title/author/category)")
            skipped += 1
            continue
        existing = db.query(models.Book).filter(models.Book.title == title, models.Book.author == author).first()
        if existing:
            skipped += 1
            continue
        book = models.Book(
            title=title, author=author, category=category,
            publisher=(row.get("publisher") or "").strip() or None,
            description=(row.get("description") or "").strip() or None,
            number_of_pages=int(row["number_of_pages"]) if row.get("number_of_pages", "").strip().isdigit() else 0,
            publication_year=int(row["publication_year"]) if row.get("publication_year", "").strip().isdigit() else None,
            added_by=current_user.id,
        )
        db.add(book)
        created += 1
    db.commit()
    return schemas.BulkImportResult(created=created, skipped=skipped, errors=errors[:20])


@router.get("/books/featured", response_model=List[schemas.BookOut])
def featured_books(db: Session = Depends(get_db)):
    books = db.query(models.Book).filter(
        models.Book.is_featured == True, models.Book.status == "approved"  # noqa: E712
    ).all()
    return [_book_out(db, b) for b in books]


@router.get("/books/recommended", response_model=List[schemas.BookOut])
def recommended_books(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    interests = (current_user.reading_interests or "").split(",")
    interests = [i.strip() for i in interests if i.strip()]
    q = db.query(models.Book).filter(models.Book.status == "approved")
    if interests:
        q = q.filter(models.Book.category.in_(interests))
    books = q.order_by(models.Book.view_count.desc()).limit(10).all()
    if not books:
        books = db.query(models.Book).filter(
            models.Book.status == "approved"
        ).order_by(models.Book.view_count.desc()).limit(10).all()
    return [_book_out(db, b) for b in books]


@router.get("/books/continue-reading", response_model=List[schemas.BookOut])
def continue_reading(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    progress = (
        db.query(models.ReadingProgress)
        .filter(
            models.ReadingProgress.user_id == current_user.id,
            models.ReadingProgress.status == "reading",
        )
        .order_by(models.ReadingProgress.last_read_at.desc())
        .all()
    )
    books = []
    for p in progress:
        book = db.query(models.Book).filter(models.Book.id == p.book_id).first()
        if book:
            books.append(_book_out(db, book))
    return books


@router.get("/favorites", response_model=List[schemas.BookOut])
def get_favorites(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    favs = db.query(models.Favorite).filter(models.Favorite.user_id == current_user.id).all()
    out = []
    for f in favs:
        book = db.query(models.Book).filter(models.Book.id == f.book_id).first()
        if book:
            out.append(_book_out(db, book))
    return out


@router.post("/favorites/{book_id}")
def toggle_favorite(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(models.Favorite).filter(
        models.Favorite.user_id == current_user.id, models.Favorite.book_id == book_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"favorited": False}
    db.add(models.Favorite(user_id=current_user.id, book_id=book_id))
    db.commit()
    return {"favorited": True}


REACTION_EMOJIS = {"🔥", "📖", "❤️"}


@router.get("/books/{book_id}/reactions", response_model=schemas.BookReactionsOut)
def get_book_reactions(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.BookReaction).filter(models.BookReaction.book_id == book_id).all()
    counts = {e: 0 for e in REACTION_EMOJIS}
    my_reaction = None
    for r in rows:
        counts[r.emoji] = counts.get(r.emoji, 0) + 1
        if r.user_id == current_user.id:
            my_reaction = r.emoji
    return schemas.BookReactionsOut(counts=counts, my_reaction=my_reaction)


@router.post("/books/{book_id}/reactions", response_model=schemas.BookReactionsOut)
def toggle_book_reaction(
    book_id: int,
    payload: schemas.BookReactionIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.emoji not in REACTION_EMOJIS:
        raise HTTPException(status_code=400, detail="Unsupported reaction")
    existing = db.query(models.BookReaction).filter(
        models.BookReaction.book_id == book_id, models.BookReaction.user_id == current_user.id
    ).first()
    if existing and existing.emoji == payload.emoji:
        db.delete(existing)  # tapping the same reaction again clears it
    elif existing:
        existing.emoji = payload.emoji
    else:
        db.add(models.BookReaction(book_id=book_id, user_id=current_user.id, emoji=payload.emoji))
    db.commit()
    return get_book_reactions(book_id, current_user, db)


@router.get("/books/{book_id}", response_model=schemas.BookDetailOut)
def get_book(
    book_id: int,
    current_user: Optional[models.User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if book.status != "approved":
        is_owner = current_user and book.added_by == current_user.id
        is_staff = current_user and current_user.role in ("admin", "moderator")
        if not (is_owner or is_staff):
            raise HTTPException(status_code=404, detail="Book not found")
    book.view_count = (book.view_count or 0) + 1
    db.commit()
    db.refresh(book)
    out = _book_out(db, book)
    data = out.model_dump()
    data["content"] = book.content
    return schemas.BookDetailOut(**data)


@router.get("/books/{book_id}/search-inside")
def search_inside_book(book_id: int, q: str, db: Session = Depends(get_db)):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book or not book.content:
        raise HTTPException(status_code=404, detail="Book content not found")
    content = book.content
    matches = []
    idx = 0
    lower_content = content.lower()
    lower_q = q.lower()
    while True:
        pos = lower_content.find(lower_q, idx)
        if pos == -1 or len(matches) >= 20:
            break
        start = max(0, pos - 40)
        end = min(len(content), pos + len(q) + 40)
        matches.append({"position": pos, "excerpt": content[start:end]})
        idx = pos + len(q)
    return {"query": q, "matches": matches}


@router.post("/books", response_model=schemas.BookOut, status_code=201)
def create_book(
    payload: schemas.BookCreate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    book = models.Book(**payload.model_dump(), added_by=current_user.id)
    db.add(book)
    db.commit()
    db.refresh(book)
    return _book_out(db, book)


@router.put("/books/{book_id}", response_model=schemas.BookOut)
def update_book(
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
    return _book_out(db, book)


@router.delete("/books/{book_id}")
def delete_book(
    book_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    book = db.query(models.Book).filter(models.Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    db.delete(book)
    db.commit()
    return {"message": "Book deleted"}


# ---------- Reading progress, bookmarks, highlights ----------

def _update_streak(db: Session, user_id: int):
    streak = db.query(models.ReadingStreak).filter(models.ReadingStreak.user_id == user_id).first()
    if not streak:
        streak = models.ReadingStreak(user_id=user_id, current_streak=0, longest_streak=0)
        db.add(streak)
        db.flush()
    today = date.today()
    if streak.last_read_date == today:
        pass
    elif streak.last_read_date and (today - streak.last_read_date).days == 1:
        streak.current_streak += 1
        streak.last_read_date = today
    else:
        streak.current_streak = 1
        streak.last_read_date = today
    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak
    db.commit()


@router.post("/progress", response_model=schemas.ProgressOut)
def update_progress(
    payload: schemas.ProgressUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    progress = db.query(models.ReadingProgress).filter(
        models.ReadingProgress.user_id == current_user.id,
        models.ReadingProgress.book_id == payload.book_id,
    ).first()
    if not progress:
        progress = models.ReadingProgress(user_id=current_user.id, book_id=payload.book_id)
        db.add(progress)

    progress.percent_complete = payload.percent_complete
    progress.current_position = payload.current_position
    progress.last_read_at = datetime.utcnow()
    if payload.percent_complete >= 99.5 and progress.status != "completed":
        progress.status = "completed"
        progress.completed_at = datetime.utcnow()
        goal = db.query(models.ReadingGoal).filter(
            models.ReadingGoal.user_id == current_user.id,
            models.ReadingGoal.year == date.today().year,
        ).order_by(models.ReadingGoal.id.desc()).first()
        if goal:
            goal.books_completed += 1
    db.commit()
    db.refresh(progress)
    _update_streak(db, current_user.id)
    return progress


@router.get("/progress/{book_id}", response_model=schemas.ProgressOut)
def get_progress(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    progress = db.query(models.ReadingProgress).filter(
        models.ReadingProgress.user_id == current_user.id,
        models.ReadingProgress.book_id == book_id,
    ).first()
    if not progress:
        raise HTTPException(status_code=404, detail="No progress yet for this book")
    return progress


@router.get("/progress", response_model=List[schemas.ProgressOut])
def list_progress(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.ReadingProgress).filter(
        models.ReadingProgress.user_id == current_user.id
    ).all()


@router.post("/bookmarks", response_model=schemas.BookmarkOut)
def add_bookmark(
    payload: schemas.BookmarkCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bookmark = models.Bookmark(user_id=current_user.id, **payload.model_dump())
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)
    return bookmark


@router.get("/bookmarks/{book_id}", response_model=List[schemas.BookmarkOut])
def get_bookmarks(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Bookmark).filter(
        models.Bookmark.user_id == current_user.id, models.Bookmark.book_id == book_id
    ).all()


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(
    bookmark_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bm = db.query(models.Bookmark).filter(
        models.Bookmark.id == bookmark_id, models.Bookmark.user_id == current_user.id
    ).first()
    if not bm:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    db.delete(bm)
    db.commit()
    return {"message": "Bookmark removed"}


@router.post("/highlights", response_model=schemas.HighlightOut)
def add_highlight(
    payload: schemas.HighlightCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    highlight = models.Highlight(user_id=current_user.id, **payload.model_dump())
    db.add(highlight)
    db.commit()
    db.refresh(highlight)
    return highlight


@router.get("/highlights/{book_id}", response_model=List[schemas.HighlightOut])
def get_highlights(
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Highlight).filter(
        models.Highlight.user_id == current_user.id, models.Highlight.book_id == book_id
    ).all()


@router.put("/highlights/{highlight_id}", response_model=schemas.HighlightOut)
def update_highlight(
    highlight_id: int,
    payload: schemas.HighlightUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(models.Highlight).filter(
        models.Highlight.id == highlight_id, models.Highlight.user_id == current_user.id
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    h.note = payload.note
    db.commit()
    db.refresh(h)
    return h


@router.delete("/highlights/{highlight_id}")
def delete_highlight(
    highlight_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    h = db.query(models.Highlight).filter(
        models.Highlight.id == highlight_id, models.Highlight.user_id == current_user.id
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    db.delete(h)
    db.commit()
    return {"message": "Highlight removed"}


# ---------- Book of the Month ----------

@router.get("/book-of-month", response_model=Optional[schemas.BookOfMonthOut])
def get_current_book_of_month(db: Session = Depends(get_db)):
    cached = cache_get("book_of_month")
    if cached is not None:
        return cached
    botm = db.query(models.BookOfMonth).filter(
        models.BookOfMonth.is_active == True  # noqa: E712
    ).order_by(models.BookOfMonth.id.desc()).first()
    if not botm:
        return None
    data = schemas.BookOfMonthOut.model_validate(botm).model_dump()
    data["book"] = _book_out(db, botm.book)
    result = schemas.BookOfMonthOut(**data)
    cache_set("book_of_month", result, ttl_seconds=300)
    return result


@router.get("/book-of-month/history", response_model=List[schemas.BookOfMonthOut])
def book_of_month_history(db: Session = Depends(get_db)):
    entries = db.query(models.BookOfMonth).order_by(models.BookOfMonth.id.desc()).all()
    out = []
    for e in entries:
        data = schemas.BookOfMonthOut.model_validate(e).model_dump()
        data["book"] = _book_out(db, e.book)
        out.append(schemas.BookOfMonthOut(**data))
    return out


@router.post("/book-of-month", response_model=schemas.BookOfMonthOut, status_code=201)
def set_book_of_month(
    payload: schemas.BookOfMonthCreate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    # A book_of_month entry is unique per (month, year). Publishing again for a
    # period that already has an entry (e.g. swapping the book picked for the
    # current month) used to hit that DB constraint and crash with an ugly,
    # unhandled 500 error instead of just updating the existing entry.
    existing = db.query(models.BookOfMonth).filter(
        models.BookOfMonth.month == payload.month,
        models.BookOfMonth.year == payload.year,
    ).first()

    db.query(models.BookOfMonth).update({models.BookOfMonth.is_active: False})

    if existing:
        for field, value in payload.model_dump().items():
            setattr(existing, field, value)
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        botm = existing
    else:
        botm = models.BookOfMonth(**payload.model_dump())
        db.add(botm)
        db.commit()
        db.refresh(botm)

    # Automatically open a pinned community discussion thread for this book so
    # members have a ready-made place to discuss it as soon as it's announced.
    months = ["", "January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    existing_thread = db.query(models.DiscussionPost).filter(
        models.DiscussionPost.book_id == botm.book_id,
        models.DiscussionPost.category == "announcement",
        models.DiscussionPost.title.like(f"%Book of the Month%{months[botm.month]} {botm.year}%"),
    ).first()
    if not existing_thread:
        content_lines = [f"📖 **{botm.book.title}** by {botm.book.author} is our Book of the Month for {months[botm.month]} {botm.year}!"]
        if botm.reading_guide:
            content_lines.append(f"\n**Reading Guide:**\n{botm.reading_guide}")
        if botm.discussion_questions:
            questions = [q.strip() for q in botm.discussion_questions.split("\n") if q.strip()]
            if questions:
                content_lines.append("\n**Discussion Questions:**")
                content_lines.extend(f"{i+1}. {q}" for i, q in enumerate(questions))
        content_lines.append("\nJoin in below and share your thoughts as you read along with the community!")
        thread = models.DiscussionPost(
            user_id=current_user.id,
            category="announcement",
            book_id=botm.book_id,
            title=f"📖 Book of the Month — {botm.book.title} ({months[botm.month]} {botm.year})",
            content="\n".join(content_lines),
            is_pinned=True,
        )
        db.add(thread)
        db.commit()

    data = schemas.BookOfMonthOut.model_validate(botm).model_dump()
    data["book"] = _book_out(db, botm.book)
    result = schemas.BookOfMonthOut(**data)
    cache_invalidate("book_of_month")
    from ..audit import write_audit_log
    write_audit_log(db, current_user.id, "book_of_month.publish", "book", botm.book_id, botm.book.title)
    return result


@router.put("/book-of-month/{botm_id}", response_model=schemas.BookOfMonthOut)
def update_book_of_month(
    botm_id: int,
    payload: schemas.BookOfMonthUpdate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    botm = db.query(models.BookOfMonth).filter(models.BookOfMonth.id == botm_id).first()
    if not botm:
        raise HTTPException(status_code=404, detail="Book of the Month entry not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(botm, field, value)
    db.commit()
    db.refresh(botm)
    data = schemas.BookOfMonthOut.model_validate(botm).model_dump()
    data["book"] = _book_out(db, botm.book)
    result = schemas.BookOfMonthOut(**data)
    cache_invalidate("book_of_month")
    from ..audit import write_audit_log
    write_audit_log(db, current_user.id, "book_of_month.edit", "book", botm.book_id, botm.book.title)
    return result
