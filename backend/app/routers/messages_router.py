from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user

router = APIRouter(prefix="/api/messages", tags=["messages"])

STAFF_ROLES = ("admin", "moderator")


def _can_message(db: Session, sender: models.User, recipient: models.User) -> bool:
    """Whether `sender` is allowed to direct-message `recipient`.

    Child-safety gate: members should only be able to reach people they
    already have a legitimate connection to on the platform, not any
    registered user. Allowed if:
      - either party is staff (admin/moderator) - staff must stay reachable
        for moderation/support, or
      - there's an active, accepted mentorship between them, or
      - they're both members of at least one of the same reading club.
    """
    if sender.role in STAFF_ROLES or recipient.role in STAFF_ROLES:
        return True

    mentorship = db.query(models.MentorshipRequest).filter(
        models.MentorshipRequest.status == "accepted",
        or_(
            and_(models.MentorshipRequest.mentor_id == sender.id, models.MentorshipRequest.mentee_id == recipient.id),
            and_(models.MentorshipRequest.mentor_id == recipient.id, models.MentorshipRequest.mentee_id == sender.id),
        ),
    ).first()
    if mentorship:
        return True

    sender_club_ids = {
        row[0] for row in db.query(models.ClubMembership.club_id).filter(
            models.ClubMembership.user_id == sender.id
        ).all()
    }
    if sender_club_ids:
        shared = db.query(models.ClubMembership).filter(
            models.ClubMembership.user_id == recipient.id,
            models.ClubMembership.club_id.in_(sender_club_ids),
        ).first()
        if shared:
            return True

    return False


@router.get("/conversations", response_model=List[schemas.ConversationOut])
def list_conversations(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages = db.query(models.DirectMessage).filter(
        or_(
            and_(models.DirectMessage.sender_id == current_user.id, models.DirectMessage.deleted_by_sender == False),  # noqa: E712
            and_(models.DirectMessage.recipient_id == current_user.id, models.DirectMessage.deleted_by_recipient == False),  # noqa: E712
        )
    ).order_by(models.DirectMessage.created_at.desc()).all()

    seen = {}
    for m in messages:
        other_id = m.recipient_id if m.sender_id == current_user.id else m.sender_id
        if other_id not in seen:
            seen[other_id] = {"last_message": m.content, "last_message_at": m.created_at, "unread_count": 0}
        if m.recipient_id == current_user.id and not m.is_read:
            seen[other_id]["unread_count"] += 1

    out = []
    for other_id, data in seen.items():
        other = db.query(models.User).filter(models.User.id == other_id).first()
        out.append(schemas.ConversationOut(
            other_user_id=other_id, other_user_name=other.full_name if other else "Unknown",
            last_message=data["last_message"], last_message_at=data["last_message_at"],
            unread_count=data["unread_count"],
        ))
    return out


@router.get("/contacts", response_model=List[schemas.ContactOut])
def list_contacts(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """People the current user is actually allowed to start a conversation with,
    per `_can_message` — staff, accepted mentors/mentees, and fellow club members.
    Used by the frontend's "start a new conversation" picker so it doesn't leak
    the full user directory to members."""
    candidate_ids = set()

    # Staff are reachable by everyone (moderation/support).
    for row in db.query(models.User.id).filter(models.User.role.in_(STAFF_ROLES), models.User.id != current_user.id).all():
        candidate_ids.add(row[0])

    # Accepted mentorships, either direction.
    for row in db.query(models.MentorshipRequest).filter(
        models.MentorshipRequest.status == "accepted",
        or_(models.MentorshipRequest.mentor_id == current_user.id, models.MentorshipRequest.mentee_id == current_user.id),
    ).all():
        other_id = row.mentee_id if row.mentor_id == current_user.id else row.mentor_id
        candidate_ids.add(other_id)

    # Fellow members of any club the current user belongs to.
    my_club_ids = [row[0] for row in db.query(models.ClubMembership.club_id).filter(
        models.ClubMembership.user_id == current_user.id
    ).all()]
    if my_club_ids:
        for row in db.query(models.ClubMembership.user_id).filter(
            models.ClubMembership.club_id.in_(my_club_ids),
            models.ClubMembership.user_id != current_user.id,
        ).all():
            candidate_ids.add(row[0])

    if not candidate_ids:
        return []
    return db.query(models.User).filter(models.User.id.in_(candidate_ids)).order_by(models.User.full_name).all()


@router.get("/with/{other_user_id}", response_model=List[schemas.MessageOut])
def get_thread(
    other_user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages = db.query(models.DirectMessage).filter(
        or_(
            and_(
                models.DirectMessage.sender_id == current_user.id,
                models.DirectMessage.recipient_id == other_user_id,
                models.DirectMessage.deleted_by_sender == False,  # noqa: E712
            ),
            and_(
                models.DirectMessage.sender_id == other_user_id,
                models.DirectMessage.recipient_id == current_user.id,
                models.DirectMessage.deleted_by_recipient == False,  # noqa: E712
            ),
        )
    ).order_by(models.DirectMessage.created_at.asc()).all()

    db.query(models.DirectMessage).filter(
        models.DirectMessage.sender_id == other_user_id,
        models.DirectMessage.recipient_id == current_user.id,
        models.DirectMessage.is_read == False,  # noqa: E712
    ).update({models.DirectMessage.is_read: True})
    db.commit()

    out = []
    for m in messages:
        sender = db.query(models.User).filter(models.User.id == m.sender_id).first()
        out.append(schemas.MessageOut(
            id=m.id, sender_id=m.sender_id, sender_name=sender.full_name if sender else "Unknown",
            recipient_id=m.recipient_id, content=m.content, is_read=m.is_read, created_at=m.created_at,
        ))
    return out


@router.delete("/{message_id}")
def delete_message(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a message on the current user's side only — the other party still sees it."""
    msg = db.query(models.DirectMessage).filter(models.DirectMessage.id == message_id).first()
    if not msg or current_user.id not in (msg.sender_id, msg.recipient_id):
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id == current_user.id:
        msg.deleted_by_sender = True
    else:
        msg.deleted_by_recipient = True
    if msg.deleted_by_sender and msg.deleted_by_recipient:
        db.delete(msg)
    db.commit()
    return {"message": "Message deleted"}


@router.post("", response_model=schemas.MessageOut, status_code=201)
def send_message(
    payload: schemas.MessageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipient = db.query(models.User).filter(models.User.id == payload.recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if payload.recipient_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't message yourself")
    if not _can_message(db, current_user, recipient):
        raise HTTPException(
            status_code=403,
            detail="You can only message members of your book clubs or mentors you're connected with",
        )
    msg = models.DirectMessage(sender_id=current_user.id, recipient_id=payload.recipient_id, content=payload.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return schemas.MessageOut(
        id=msg.id, sender_id=current_user.id, sender_name=current_user.full_name,
        recipient_id=msg.recipient_id, content=msg.content, is_read=msg.is_read, created_at=msg.created_at,
    )


@router.get("/unread-count")
def unread_count(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = db.query(models.DirectMessage).filter(
        models.DirectMessage.recipient_id == current_user.id, models.DirectMessage.is_read == False  # noqa: E712
    ).count()
    return {"unread": count}
