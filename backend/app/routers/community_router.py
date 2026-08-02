from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff, get_current_user_optional
from ..audit import write_audit_log

router = APIRouter(prefix="/api/community", tags=["community"])


# ---------- Reviews ----------

def _review_out(db: Session, review: models.Review, viewer_id: Optional[int] = None) -> schemas.ReviewOut:
    comment_count = db.query(models.ReviewComment).filter(
        models.ReviewComment.review_id == review.id
    ).count()
    helpful_count = db.query(models.ReviewHelpfulVote).filter(
        models.ReviewHelpfulVote.review_id == review.id
    ).count()
    marked_helpful_by_me = False
    if viewer_id:
        marked_helpful_by_me = db.query(models.ReviewHelpfulVote).filter(
            models.ReviewHelpfulVote.review_id == review.id,
            models.ReviewHelpfulVote.user_id == viewer_id,
        ).first() is not None
    return schemas.ReviewOut(
        id=review.id,
        book_id=review.book_id,
        user_id=review.user_id,
        reviewer_name=review.user.full_name,
        rating=review.rating,
        lessons_learned=review.lessons_learned,
        review_text=review.review_text,
        created_at=review.created_at,
        comment_count=comment_count,
        helpful_count=helpful_count,
        marked_helpful_by_me=marked_helpful_by_me,
    )


@router.get("/reviews/{book_id}", response_model=List[schemas.ReviewOut])
def get_book_reviews(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    reviews = db.query(models.Review).filter(
        models.Review.book_id == book_id, models.Review.is_approved == True  # noqa: E712
    ).order_by(models.Review.created_at.desc()).all()
    viewer_id = current_user.id if current_user else None
    return [_review_out(db, r, viewer_id) for r in reviews]


@router.post("/reviews/{review_id}/helpful")
def toggle_helpful(
    review_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Toggle a 'this review was helpful' vote for the current user (one vote per user per review)."""
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    existing = db.query(models.ReviewHelpfulVote).filter(
        models.ReviewHelpfulVote.review_id == review_id, models.ReviewHelpfulVote.user_id == current_user.id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        marked = False
    else:
        db.add(models.ReviewHelpfulVote(review_id=review_id, user_id=current_user.id))
        db.commit()
        marked = True
    count = db.query(models.ReviewHelpfulVote).filter(models.ReviewHelpfulVote.review_id == review_id).count()
    return {"marked_helpful_by_me": marked, "helpful_count": count}


@router.post("/reviews", response_model=schemas.ReviewOut, status_code=201)
def create_review(
    payload: schemas.ReviewCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(models.Review).filter(
        models.Review.user_id == current_user.id, models.Review.book_id == payload.book_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already reviewed this book. Edit your existing review instead.")
    review = models.Review(user_id=current_user.id, **payload.model_dump())
    db.add(review)
    db.commit()
    db.refresh(review)
    return _review_out(db, review)


@router.put("/reviews/{review_id}", response_model=schemas.ReviewOut)
def update_review(
    review_id: int,
    payload: schemas.ReviewCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.user_id != current_user.id and current_user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="You can only edit your own review")
    review.rating = payload.rating
    review.lessons_learned = payload.lessons_learned
    review.review_text = payload.review_text
    db.commit()
    db.refresh(review)
    return _review_out(db, review)


@router.delete("/reviews/{review_id}")
def delete_review(
    review_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.user_id != current_user.id and current_user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="You can only delete your own review")
    db.delete(review)
    db.commit()
    return {"message": "Review deleted"}


@router.post("/reviews/{review_id}/comments", response_model=schemas.ReviewCommentOut)
def comment_on_review(
    review_id: int,
    payload: schemas.ReviewCommentCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = db.query(models.Review).filter(models.Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    comment = models.ReviewComment(review_id=review_id, user_id=current_user.id, content=payload.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return schemas.ReviewCommentOut(
        id=comment.id, user_id=comment.user_id, commenter_name=current_user.full_name,
        content=comment.content, created_at=comment.created_at,
    )


@router.get("/reviews/{review_id}/comments", response_model=List[schemas.ReviewCommentOut])
def get_review_comments(review_id: int, db: Session = Depends(get_db)):
    comments = db.query(models.ReviewComment).filter(
        models.ReviewComment.review_id == review_id
    ).order_by(models.ReviewComment.created_at.asc()).all()
    return [
        schemas.ReviewCommentOut(
            id=c.id, user_id=c.user_id, commenter_name=c.user.full_name if hasattr(c, "user") else "",
            content=c.content, created_at=c.created_at,
        ) if False else schemas.ReviewCommentOut(
            id=c.id, user_id=c.user_id,
            commenter_name=db.query(models.User).filter(models.User.id == c.user_id).first().full_name,
            content=c.content, created_at=c.created_at,
        )
        for c in comments
    ]


@router.delete("/reviews/comments/{comment_id}")
def delete_review_comment(
    comment_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = db.query(models.ReviewComment).filter(models.ReviewComment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != current_user.id and current_user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="You can only delete your own comment")
    db.delete(comment)
    db.commit()
    return {"message": "Comment deleted"}


# ---------- Discussions ----------

VALID_CATEGORIES = {"general", "book", "topic", "qna", "announcement"}


def _post_out(db: Session, post: models.DiscussionPost) -> schemas.DiscussionPostOut:
    reply_count = db.query(models.DiscussionReply).filter(
        models.DiscussionReply.post_id == post.id, models.DiscussionReply.is_removed == False  # noqa: E712
    ).count()
    author = db.query(models.User).filter(models.User.id == post.user_id).first()
    return schemas.DiscussionPostOut(
        id=post.id, user_id=post.user_id, author_name=author.full_name if author else "Unknown",
        category=post.category, book_id=post.book_id, title=post.title, content=post.content,
        is_pinned=post.is_pinned, created_at=post.created_at, reply_count=reply_count,
    )


@router.get("/discussions", response_model=List[schemas.DiscussionPostOut])
def list_discussions(
    category: Optional[str] = None,
    book_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.DiscussionPost).filter(models.DiscussionPost.is_removed == False)  # noqa: E712
    if category:
        q = q.filter(models.DiscussionPost.category == category)
    if book_id:
        q = q.filter(models.DiscussionPost.book_id == book_id)
    posts = q.order_by(models.DiscussionPost.is_pinned.desc(), models.DiscussionPost.created_at.desc()).all()
    return [_post_out(db, p) for p in posts]


@router.post("/discussions", response_model=schemas.DiscussionPostOut, status_code=201)
def create_discussion(
    payload: schemas.DiscussionPostCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category = payload.category if payload.category in VALID_CATEGORIES else "general"
    if category == "announcement" and current_user.role not in ("admin", "moderator"):
        category = "general"
    post = models.DiscussionPost(
        user_id=current_user.id, category=category, book_id=payload.book_id,
        title=payload.title, content=payload.content,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return _post_out(db, post)


@router.get("/discussions/{post_id}", response_model=schemas.DiscussionPostOut)
def get_discussion(post_id: int, db: Session = Depends(get_db)):
    post = db.query(models.DiscussionPost).filter(models.DiscussionPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Discussion not found")
    return _post_out(db, post)


@router.delete("/discussions/{post_id}")
def remove_discussion(
    post_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    post = db.query(models.DiscussionPost).filter(models.DiscussionPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Discussion not found")
    post.is_removed = True
    db.commit()
    write_audit_log(db, current_user.id, "discussion.remove", "discussion_post", post_id, post.title)
    return {"message": "Discussion removed"}


@router.put("/discussions/{post_id}/pin")
def pin_discussion(
    post_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    post = db.query(models.DiscussionPost).filter(models.DiscussionPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Discussion not found")
    post.is_pinned = not post.is_pinned
    db.commit()
    return {"is_pinned": post.is_pinned}


@router.get("/discussions/{post_id}/replies", response_model=List[schemas.DiscussionReplyOut])
def get_replies(post_id: int, db: Session = Depends(get_db)):
    replies = db.query(models.DiscussionReply).filter(
        models.DiscussionReply.post_id == post_id, models.DiscussionReply.is_removed == False  # noqa: E712
    ).order_by(models.DiscussionReply.created_at.asc()).all()
    out = []
    for r in replies:
        author = db.query(models.User).filter(models.User.id == r.user_id).first()
        out.append(schemas.DiscussionReplyOut(
            id=r.id, user_id=r.user_id, author_name=author.full_name if author else "Unknown",
            parent_reply_id=r.parent_reply_id, content=r.content, is_edited=r.is_edited,
            created_at=r.created_at,
        ))
    return out


@router.post("/discussions/{post_id}/replies", response_model=schemas.DiscussionReplyOut, status_code=201)
def add_reply(
    post_id: int,
    payload: schemas.DiscussionReplyCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(models.DiscussionPost).filter(models.DiscussionPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Discussion not found")
    if payload.parent_reply_id:
        parent = db.query(models.DiscussionReply).filter(
            models.DiscussionReply.id == payload.parent_reply_id, models.DiscussionReply.post_id == post_id
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent reply not found on this post")
    reply = models.DiscussionReply(
        post_id=post_id, user_id=current_user.id, content=payload.content,
        parent_reply_id=payload.parent_reply_id,
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)
    return schemas.DiscussionReplyOut(
        id=reply.id, user_id=reply.user_id, author_name=current_user.full_name,
        parent_reply_id=reply.parent_reply_id, content=reply.content, is_edited=False,
        created_at=reply.created_at,
    )


@router.put("/replies/{reply_id}", response_model=schemas.DiscussionReplyOut)
def edit_reply(
    reply_id: int,
    payload: schemas.DiscussionReplyUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reply = db.query(models.DiscussionReply).filter(models.DiscussionReply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    if reply.user_id != current_user.id and current_user.role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="You can only edit your own reply")
    reply.content = payload.content
    reply.is_edited = True
    db.commit()
    db.refresh(reply)
    author = db.query(models.User).filter(models.User.id == reply.user_id).first()
    return schemas.DiscussionReplyOut(
        id=reply.id, user_id=reply.user_id, author_name=author.full_name if author else "Unknown",
        parent_reply_id=reply.parent_reply_id, content=reply.content, is_edited=reply.is_edited,
        created_at=reply.created_at,
    )


@router.delete("/replies/{reply_id}")
def remove_reply(
    reply_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    reply = db.query(models.DiscussionReply).filter(models.DiscussionReply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    reply.is_removed = True
    db.commit()
    write_audit_log(db, current_user.id, "reply.remove", "discussion_reply", reply_id)
    return {"message": "Reply removed"}
