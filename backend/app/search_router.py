from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import models, schemas
from .database import get_db
from .auth import get_current_user
from .routers.library_router import _book_out
from .routers.community_router import _post_out

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=schemas.SearchResults)
def global_search(
    q: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    like = f"%{q}%"

    books = db.query(models.Book).filter(
        or_(
            models.Book.title.ilike(like),
            models.Book.author.ilike(like),
            models.Book.description.ilike(like),
        )
    ).limit(10).all()

    discussions = db.query(models.DiscussionPost).filter(
        models.DiscussionPost.is_removed == False,  # noqa: E712
        or_(models.DiscussionPost.title.ilike(like), models.DiscussionPost.content.ilike(like)),
    ).limit(10).all()

    resources = db.query(models.ReadingResource).filter(
        or_(models.ReadingResource.title.ilike(like), models.ReadingResource.content.ilike(like))
    ).limit(10).all()

    resource_out = []
    for r in resources:
        book = db.query(models.Book).filter(models.Book.id == r.book_id).first() if r.book_id else None
        resource_out.append(schemas.ResourceOut(
            id=r.id, book_id=r.book_id, book_title=book.title if book else None,
            resource_type=r.resource_type, title=r.title, content=r.content, created_at=r.created_at,
        ))

    return schemas.SearchResults(
        books=[_book_out(db, b) for b in books],
        discussions=[_post_out(db, p) for p in discussions],
        resources=resource_out,
    )
