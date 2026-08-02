import csv
import io
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_mentor_or_admin, get_current_user_optional

router = APIRouter(prefix="/api/live", tags=["live"])

# Note: implemented as short-poll chat (client re-fetches every few seconds)
# rather than true WebSockets, to keep this a single-process FastAPI app
# with no extra infrastructure. See Part 1/5 architecture notes for the
# WebSocket upgrade path if real-time push becomes a requirement.
#
# This router now backs 40 chat + broadcast features on top of that
# original polling foundation:
#   Chat (1-14): edit, soft-delete, staff-delete, reactions, threaded replies,
#     @mention support (frontend-rendered), pin/unpin, typing indicator,
#     message search, slow mode, mute, auto system messages, character-limit
#     enforcement, transcript export.
#   Broadcast/session (15-40): recurring sessions, book/category tagging,
#     capacity + waitlist w/ auto-promotion, co-hosts, RSVP-reminder
#     notifications, computed live/upcoming/ended status, post-session
#     recording notes, live polls, Q&A queue with upvotes, resource links,
#     featured sessions, advanced search/filter, public/private attendee
#     list, early session end, post-session ratings, .ics export, session
#     duplication, CSV attendee export, live viewer presence, announcement-
#     only mode, ban, capacity/waitlist status on output, auto-ended sweep,
#     host stats dashboard, session detail-change notifications.

PRESENCE_WINDOW_SECONDS = 30  # a user counts as "viewing" if seen in the last 30s
TYPING_WINDOW_SECONDS = 8

MAX_MESSAGE_LENGTH = 2000
EDIT_WINDOW_MINUTES = 10


# ---------------------------------------------------------------- helpers

def _get_session_or_404(db: Session, session_id: int) -> models.LiveSession:
    session = db.query(models.LiveSession).filter(models.LiveSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _is_staff(user: models.User) -> bool:
    return user.role in ("admin", "moderator")


def _is_cohost(db: Session, session_id: int, user_id: int) -> bool:
    return db.query(models.LiveSessionCoHost).filter(
        models.LiveSessionCoHost.session_id == session_id,
        models.LiveSessionCoHost.user_id == user_id,
    ).first() is not None


def _can_manage(db: Session, session: models.LiveSession, user: models.User) -> bool:
    return session.host_id == user.id or _is_staff(user) or _is_cohost(db, session.id, user.id)


def _require_can_manage(db: Session, session: models.LiveSession, user: models.User):
    if not _can_manage(db, session, user):
        raise HTTPException(status_code=403, detail="Only the host, a co-host, or staff can do this")


def _is_muted(db: Session, session_id: int, user_id: int) -> bool:
    return db.query(models.LiveSessionMute).filter(
        models.LiveSessionMute.session_id == session_id,
        models.LiveSessionMute.user_id == user_id,
    ).first() is not None


def _is_banned(db: Session, session_id: int, user_id: int) -> bool:
    return db.query(models.LiveSessionBan).filter(
        models.LiveSessionBan.session_id == session_id,
        models.LiveSessionBan.user_id == user_id,
    ).first() is not None


def _compute_status(session: models.LiveSession) -> str:
    if session.is_cancelled:
        return "cancelled"
    if session.ended_at or not session.is_active:
        return "ended"
    now = datetime.utcnow()
    end = session.scheduled_at + timedelta(minutes=session.duration_minutes or 60)
    if now < session.scheduled_at:
        return "upcoming"
    if session.scheduled_at <= now <= end:
        return "live"
    return "ended"


def _sweep_ended_sessions(db: Session):
    """Auto-mark sessions inactive once their scheduled window has passed."""
    now = datetime.utcnow()
    candidates = db.query(models.LiveSession).filter(
        models.LiveSession.is_active == True,  # noqa: E712
        models.LiveSession.is_cancelled == False,  # noqa: E712
        models.LiveSession.ended_at.is_(None),
    ).all()
    changed = False
    for s in candidates:
        end = s.scheduled_at + timedelta(minutes=s.duration_minutes or 60)
        if now > end:
            s.is_active = False
            s.ended_at = end
            changed = True
    if changed:
        db.commit()


def _viewer_count(db: Session, session_id: int) -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=PRESENCE_WINDOW_SECONDS)
    return db.query(models.LiveSessionPresence).filter(
        models.LiveSessionPresence.session_id == session_id,
        models.LiveSessionPresence.last_seen >= cutoff,
    ).count()


def _rating_stats(db: Session, session_id: int):
    ratings = db.query(models.LiveSessionRating).filter(
        models.LiveSessionRating.session_id == session_id
    ).all()
    if not ratings:
        return None, 0
    avg = round(sum(r.rating for r in ratings) / len(ratings), 2)
    return avg, len(ratings)


def _add_system_message(db: Session, session_id: int, content: str):
    db.add(models.LiveMessage(session_id=session_id, user_id=None, content=content, is_system=True))


def _session_out(db: Session, s: models.LiveSession, viewer_id: Optional[int] = None) -> schemas.LiveSessionOut:
    host = db.query(models.User).filter(models.User.id == s.host_id).first() if s.host_id else None
    rsvp_count = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == s.id).count()
    waitlist_count = db.query(models.LiveSessionWaitlist).filter(models.LiveSessionWaitlist.session_id == s.id).count()
    is_attending = False
    is_waitlisted = False
    if viewer_id:
        is_attending = db.query(models.LiveSessionRSVP).filter(
            models.LiveSessionRSVP.session_id == s.id, models.LiveSessionRSVP.user_id == viewer_id
        ).first() is not None
        is_waitlisted = db.query(models.LiveSessionWaitlist).filter(
            models.LiveSessionWaitlist.session_id == s.id, models.LiveSessionWaitlist.user_id == viewer_id
        ).first() is not None

    cohost_ids = [c.user_id for c in db.query(models.LiveSessionCoHost).filter(
        models.LiveSessionCoHost.session_id == s.id).all()]
    cohost_names = []
    if cohost_ids:
        cohost_names = [u.full_name for u in db.query(models.User).filter(models.User.id.in_(cohost_ids)).all()]

    book_title = None
    if s.book_id:
        book = db.query(models.Book).filter(models.Book.id == s.book_id).first()
        book_title = book.title if book else None

    avg_rating, rating_count = _rating_stats(db, s.id)

    return schemas.LiveSessionOut(
        id=s.id, title=s.title, session_type=s.session_type, host_id=s.host_id,
        host_name=host.full_name if host else None, co_host_names=cohost_names,
        description=s.description,
        scheduled_at=s.scheduled_at, duration_minutes=s.duration_minutes, is_active=s.is_active,
        is_cancelled=s.is_cancelled, rsvp_count=rsvp_count, is_attending=is_attending,
        category=s.category, book_id=s.book_id, book_title=book_title,
        max_capacity=s.max_capacity, waitlist_count=waitlist_count, is_waitlisted=is_waitlisted,
        recurrence=s.recurrence, slow_mode_seconds=s.slow_mode_seconds or 0,
        announcement_only=s.announcement_only, attendee_list_public=s.attendee_list_public,
        recording_notes=s.recording_notes, is_featured=s.is_featured,
        status=_compute_status(s), viewer_count=_viewer_count(db, s.id),
        average_rating=avg_rating, rating_count=rating_count,
    )


def _message_out(db: Session, m: models.LiveMessage, viewer_id: Optional[int] = None) -> schemas.LiveMessageOut:
    author = db.query(models.User).filter(models.User.id == m.user_id).first() if m.user_id else None
    reply_author_name = None
    reply_snippet = None
    if m.reply_to_id:
        parent = db.query(models.LiveMessage).filter(models.LiveMessage.id == m.reply_to_id).first()
        if parent:
            parent_author = db.query(models.User).filter(models.User.id == parent.user_id).first()
            reply_author_name = parent_author.full_name if parent_author else "Unknown"
            reply_snippet = (parent.content[:80] + "…") if parent.content and len(parent.content) > 80 else parent.content

    reactions_q = db.query(models.LiveMessageReaction).filter(models.LiveMessageReaction.message_id == m.id).all()
    grouped = {}
    for r in reactions_q:
        grouped.setdefault(r.emoji, {"count": 0, "mine": False})
        grouped[r.emoji]["count"] += 1
        if viewer_id and r.user_id == viewer_id:
            grouped[r.emoji]["mine"] = True
    reactions = [
        schemas.LiveMessageReactionOut(emoji=e, count=v["count"], reacted_by_me=v["mine"])
        for e, v in grouped.items()
    ]

    return schemas.LiveMessageOut(
        id=m.id, user_id=m.user_id or 0,
        author_name="Announcement" if m.is_system else (author.full_name if author else "Unknown"),
        content="[message deleted]" if m.is_deleted else m.content,
        created_at=m.created_at, reply_to_id=m.reply_to_id,
        reply_to_author=reply_author_name, reply_to_snippet=reply_snippet,
        is_pinned=m.is_pinned, is_deleted=m.is_deleted, is_system=m.is_system,
        edited_at=m.edited_at, reactions=reactions,
    )


# ---------------------------------------------------------------- sessions

@router.get("/sessions", response_model=List[schemas.LiveSessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    _sweep_ended_sessions(db)
    sessions = db.query(models.LiveSession).order_by(models.LiveSession.scheduled_at.desc()).all()
    viewer_id = current_user.id if current_user else None
    return [_session_out(db, s, viewer_id) for s in sessions]


@router.get("/sessions/search", response_model=List[schemas.LiveSessionOut])
def search_sessions(
    q: Optional[str] = None,
    session_type: Optional[str] = None,
    category: Optional[str] = None,
    when: Optional[str] = Query(None, description="upcoming, live, ended, or all"),
    host_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """Feature 26: advanced session search & filter."""
    _sweep_ended_sessions(db)
    query = db.query(models.LiveSession)
    if q:
        like = f"%{q}%"
        query = query.filter(models.LiveSession.title.ilike(like))
    if session_type:
        query = query.filter(models.LiveSession.session_type == session_type)
    if category:
        query = query.filter(models.LiveSession.category == category)
    if host_id:
        query = query.filter(models.LiveSession.host_id == host_id)
    sessions = query.order_by(models.LiveSession.scheduled_at.desc()).all()
    viewer_id = current_user.id if current_user else None
    out = [_session_out(db, s, viewer_id) for s in sessions]
    if when and when != "all":
        out = [s for s in out if s.status == when]
    return out


@router.post("/sessions", response_model=schemas.LiveSessionOut, status_code=201)
def create_session(
    payload: schemas.LiveSessionCreate,
    current_user: models.User = Depends(require_mentor_or_admin),
    db: Session = Depends(get_db),
):
    session = models.LiveSession(**payload.model_dump(), host_id=current_user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    _add_system_message(db, session.id, f"{current_user.full_name} scheduled this session.")
    db.commit()
    return _session_out(db, session, current_user.id)


@router.get("/sessions/{session_id}", response_model=schemas.LiveSessionOut)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    _sweep_ended_sessions(db)
    session = _get_session_or_404(db, session_id)
    return _session_out(db, session, current_user.id if current_user else None)


@router.put("/sessions/{session_id}", response_model=schemas.LiveSessionOut)
def update_session(
    session_id: int,
    payload: schemas.LiveSessionUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(session, field, value)
    db.commit()
    db.refresh(session)

    # Feature 40: notify RSVP'd attendees when session details change.
    if changes:
        rsvps = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == session.id).all()
        for r in rsvps:
            if r.user_id != current_user.id:
                db.add(models.Notification(
                    user_id=r.user_id, notif_type="live_session_updated",
                    message=f"'{session.title}' was updated by the host.",
                ))
        db.commit()
    return _session_out(db, session, current_user.id)


@router.delete("/sessions/{session_id}")
def cancel_session(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    session.is_cancelled = True
    session.is_active = False
    db.commit()
    return {"message": "Session cancelled"}


@router.put("/sessions/{session_id}/end")
def end_session_early(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 28: host/co-host/staff can end a live session early."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    session.is_active = False
    session.ended_at = datetime.utcnow()
    db.commit()
    _add_system_message(db, session_id, "This session has ended. Thanks for joining!")
    db.commit()
    return {"message": "Session ended"}


@router.put("/sessions/{session_id}/feature")
def toggle_featured(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 25: admin-curated featured/highlighted sessions."""
    if not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Staff only")
    session = _get_session_or_404(db, session_id)
    session.is_featured = not session.is_featured
    db.commit()
    return {"message": "Updated", "is_featured": session.is_featured}


@router.put("/sessions/{session_id}/notes")
def set_recording_notes(
    session_id: int,
    payload: schemas.LiveSessionUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 21: post-session recording notes / summary."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    session.recording_notes = payload.recording_notes
    db.commit()
    return {"message": "Notes saved"}


@router.post("/sessions/{session_id}/duplicate", response_model=schemas.LiveSessionOut, status_code=201)
def duplicate_session(
    session_id: int,
    payload: schemas.LiveSessionDuplicateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 31: clone a past session into a freshly scheduled one."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    clone = models.LiveSession(
        title=session.title, session_type=session.session_type, host_id=current_user.id,
        description=session.description, scheduled_at=payload.scheduled_at,
        duration_minutes=session.duration_minutes, category=session.category,
        book_id=session.book_id, max_capacity=session.max_capacity,
        recurrence=session.recurrence, slow_mode_seconds=session.slow_mode_seconds,
        announcement_only=session.announcement_only, parent_session_id=session.id,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _session_out(db, clone, current_user.id)


@router.get("/sessions/{session_id}/ics")
def export_ics(session_id: int, db: Session = Depends(get_db)):
    """Feature 30: .ics calendar export for a session."""
    s = _get_session_or_404(db, session_id)
    start = s.scheduled_at.strftime("%Y%m%dT%H%M%SZ")
    end = (s.scheduled_at + timedelta(minutes=s.duration_minutes or 60)).strftime("%Y%m%dT%H%M%SZ")
    ics = "\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Gwin's Readers Club//Live Sessions//EN",
        "BEGIN:VEVENT", f"UID:live-session-{s.id}@readersclub.ng",
        f"DTSTART:{start}", f"DTEND:{end}",
        f"SUMMARY:{s.title}", f"DESCRIPTION:{(s.description or '').replace(chr(10), ' ')}",
        "END:VEVENT", "END:VCALENDAR",
    ])
    return PlainTextResponse(ics, media_type="text/calendar", headers={
        "Content-Disposition": f'attachment; filename="session-{s.id}.ics"'
    })


# ---------------------------------------------------------------- rsvp / waitlist / capacity

@router.post("/sessions/{session_id}/rsvp")
def rsvp_session(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    if _is_banned(db, session_id, current_user.id):
        raise HTTPException(status_code=403, detail="You have been removed from this session")
    existing = db.query(models.LiveSessionRSVP).filter(
        models.LiveSessionRSVP.session_id == session_id, models.LiveSessionRSVP.user_id == current_user.id
    ).first()
    if existing:
        return {"message": "Already RSVP'd"}

    # Feature 17: max capacity + waitlist.
    if session.max_capacity:
        count = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == session_id).count()
        if count >= session.max_capacity:
            already_waitlisted = db.query(models.LiveSessionWaitlist).filter(
                models.LiveSessionWaitlist.session_id == session_id,
                models.LiveSessionWaitlist.user_id == current_user.id,
            ).first()
            if not already_waitlisted:
                db.add(models.LiveSessionWaitlist(session_id=session_id, user_id=current_user.id))
                db.commit()
            return {"message": "Session is full — added to waitlist", "waitlisted": True}

    db.add(models.LiveSessionRSVP(session_id=session_id, user_id=current_user.id))
    db.commit()
    count = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == session_id).count()
    return {"message": "RSVP'd", "rsvp_count": count}


@router.delete("/sessions/{session_id}/rsvp")
def cancel_session_rsvp(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(models.LiveSessionRSVP).filter(
        models.LiveSessionRSVP.session_id == session_id, models.LiveSessionRSVP.user_id == current_user.id
    ).delete()
    db.commit()

    # Feature 34 (auto-promotion): move the longest-waiting waitlisted user into the RSVP list.
    next_waiting = db.query(models.LiveSessionWaitlist).filter(
        models.LiveSessionWaitlist.session_id == session_id
    ).order_by(models.LiveSessionWaitlist.created_at.asc()).first()
    if next_waiting:
        db.add(models.LiveSessionRSVP(session_id=session_id, user_id=next_waiting.user_id))
        db.add(models.Notification(
            user_id=next_waiting.user_id, notif_type="live_session_waitlist",
            message="A spot opened up in a live session you were waitlisted for — you're in!",
        ))
        db.delete(next_waiting)
        db.commit()

    count = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == session_id).count()
    return {"message": "RSVP cancelled", "rsvp_count": count}


@router.delete("/sessions/{session_id}/waitlist")
def leave_waitlist(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(models.LiveSessionWaitlist).filter(
        models.LiveSessionWaitlist.session_id == session_id, models.LiveSessionWaitlist.user_id == current_user.id
    ).delete()
    db.commit()
    return {"message": "Removed from waitlist"}


@router.get("/sessions/{session_id}/attendees")
def list_attendees(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    session = _get_session_or_404(db, session_id)
    # Feature 27: public/private attendee list.
    if not session.attendee_list_public:
        if not current_user or not _can_manage(db, session, current_user):
            raise HTTPException(status_code=403, detail="The attendee list for this session is private")
    rsvps = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == session_id).all()
    out = []
    for r in rsvps:
        user = db.query(models.User).filter(models.User.id == r.user_id).first()
        out.append({"user_id": r.user_id, "name": user.full_name if user else "Unknown"})
    return out


@router.get("/sessions/{session_id}/attendees/export")
def export_attendees_csv(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 32: export attendee list as CSV."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    rsvps = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == session_id).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["user_id", "name", "email", "rsvp_at"])
    for r in rsvps:
        user = db.query(models.User).filter(models.User.id == r.user_id).first()
        writer.writerow([r.user_id, user.full_name if user else "Unknown", user.email if user else "", r.created_at])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="session-{session_id}-attendees.csv"'
    })


# ---------------------------------------------------------------- co-hosts / mute / ban

@router.post("/sessions/{session_id}/cohosts/{user_id}")
def add_cohost(
    session_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 18: co-hosts."""
    session = _get_session_or_404(db, session_id)
    if session.host_id != current_user.id and not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Only the primary host or staff can add co-hosts")
    if not db.query(models.LiveSessionCoHost).filter(
        models.LiveSessionCoHost.session_id == session_id, models.LiveSessionCoHost.user_id == user_id
    ).first():
        db.add(models.LiveSessionCoHost(session_id=session_id, user_id=user_id))
        db.commit()
    return {"message": "Co-host added"}


@router.delete("/sessions/{session_id}/cohosts/{user_id}")
def remove_cohost(
    session_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    if session.host_id != current_user.id and not _is_staff(current_user):
        raise HTTPException(status_code=403, detail="Only the primary host or staff can remove co-hosts")
    db.query(models.LiveSessionCoHost).filter(
        models.LiveSessionCoHost.session_id == session_id, models.LiveSessionCoHost.user_id == user_id
    ).delete()
    db.commit()
    return {"message": "Co-host removed"}


@router.post("/sessions/{session_id}/mute/{user_id}")
def mute_user(
    session_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 11: temporarily mute a disruptive participant."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    if not _is_muted(db, session_id, user_id):
        db.add(models.LiveSessionMute(session_id=session_id, user_id=user_id, muted_by=current_user.id))
        db.commit()
    return {"message": "User muted"}


@router.delete("/sessions/{session_id}/mute/{user_id}")
def unmute_user(
    session_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    db.query(models.LiveSessionMute).filter(
        models.LiveSessionMute.session_id == session_id, models.LiveSessionMute.user_id == user_id
    ).delete()
    db.commit()
    return {"message": "User unmuted"}


@router.post("/sessions/{session_id}/ban/{user_id}")
def ban_user(
    session_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 35: permanently remove a participant from a session."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    if not _is_banned(db, session_id, user_id):
        db.add(models.LiveSessionBan(session_id=session_id, user_id=user_id, banned_by=current_user.id))
    db.query(models.LiveSessionRSVP).filter(
        models.LiveSessionRSVP.session_id == session_id, models.LiveSessionRSVP.user_id == user_id
    ).delete()
    db.commit()
    return {"message": "User banned from this session"}


@router.delete("/sessions/{session_id}/ban/{user_id}")
def unban_user(
    session_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    db.query(models.LiveSessionBan).filter(
        models.LiveSessionBan.session_id == session_id, models.LiveSessionBan.user_id == user_id
    ).delete()
    db.commit()
    return {"message": "User unbanned"}


# ---------------------------------------------------------------- reminders / stats

@router.post("/sessions/{session_id}/notify-reminder")
def send_reminder(
    session_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 19: host-triggered reminder notification to all RSVP'd attendees."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    rsvps = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == session_id).all()
    for r in rsvps:
        db.add(models.Notification(
            user_id=r.user_id, notif_type="live_session_reminder",
            message=f"Reminder: '{session.title}' starts at {session.scheduled_at.strftime('%b %d, %I:%M %p')} UTC.",
        ))
    db.commit()
    return {"message": f"Reminder sent to {len(rsvps)} attendees"}


@router.get("/my-sessions/stats", response_model=List[schemas.LiveSessionHostStats])
def host_stats(
    current_user: models.User = Depends(require_mentor_or_admin),
    db: Session = Depends(get_db),
):
    """Feature 38: host dashboard — quick stats across sessions a user hosts."""
    _sweep_ended_sessions(db)
    sessions = db.query(models.LiveSession).filter(models.LiveSession.host_id == current_user.id).order_by(
        models.LiveSession.scheduled_at.desc()
    ).all()
    out = []
    for s in sessions:
        rsvp_count = db.query(models.LiveSessionRSVP).filter(models.LiveSessionRSVP.session_id == s.id).count()
        message_count = db.query(models.LiveMessage).filter(
            models.LiveMessage.session_id == s.id, models.LiveMessage.is_system == False  # noqa: E712
        ).count()
        avg_rating, rating_count = _rating_stats(db, s.id)
        out.append(schemas.LiveSessionHostStats(
            id=s.id, title=s.title, scheduled_at=s.scheduled_at, status=_compute_status(s),
            rsvp_count=rsvp_count, message_count=message_count,
            average_rating=avg_rating, rating_count=rating_count,
        ))
    return out


# ---------------------------------------------------------------- ratings

@router.post("/sessions/{session_id}/rating", response_model=schemas.LiveSessionRatingOut, status_code=201)
def rate_session(
    session_id: int,
    payload: schemas.LiveSessionRatingCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 29: post-session rating & review."""
    _get_session_or_404(db, session_id)
    if not (1 <= payload.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    existing = db.query(models.LiveSessionRating).filter(
        models.LiveSessionRating.session_id == session_id, models.LiveSessionRating.user_id == current_user.id
    ).first()
    if existing:
        existing.rating = payload.rating
        existing.comment = payload.comment
        db.commit()
        db.refresh(existing)
        rating = existing
    else:
        rating = models.LiveSessionRating(
            session_id=session_id, user_id=current_user.id, rating=payload.rating, comment=payload.comment
        )
        db.add(rating)
        db.commit()
        db.refresh(rating)
    return schemas.LiveSessionRatingOut(
        id=rating.id, user_id=rating.user_id, author_name=current_user.full_name,
        rating=rating.rating, comment=rating.comment, created_at=rating.created_at,
    )


@router.get("/sessions/{session_id}/ratings", response_model=List[schemas.LiveSessionRatingOut])
def list_ratings(session_id: int, db: Session = Depends(get_db)):
    """Feature 39: session reviews visible after the session ends."""
    ratings = db.query(models.LiveSessionRating).filter(
        models.LiveSessionRating.session_id == session_id
    ).order_by(models.LiveSessionRating.created_at.desc()).all()
    out = []
    for r in ratings:
        author = db.query(models.User).filter(models.User.id == r.user_id).first()
        out.append(schemas.LiveSessionRatingOut(
            id=r.id, user_id=r.user_id, author_name=author.full_name if author else "Unknown",
            rating=r.rating, comment=r.comment, created_at=r.created_at,
        ))
    return out


# ---------------------------------------------------------------- resources

@router.post("/sessions/{session_id}/resources", response_model=schemas.LiveSessionResourceOut, status_code=201)
def add_resource(
    session_id: int,
    payload: schemas.LiveSessionResourceCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 24: attach reading materials/links to a session."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    resource = models.LiveSessionResource(
        session_id=session_id, title=payload.title, url=payload.url, added_by=current_user.id
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.get("/sessions/{session_id}/resources", response_model=List[schemas.LiveSessionResourceOut])
def list_resources(session_id: int, db: Session = Depends(get_db)):
    return db.query(models.LiveSessionResource).filter(
        models.LiveSessionResource.session_id == session_id
    ).order_by(models.LiveSessionResource.created_at.asc()).all()


@router.delete("/resources/{resource_id}")
def delete_resource(
    resource_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resource = db.query(models.LiveSessionResource).filter(models.LiveSessionResource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    session = _get_session_or_404(db, resource.session_id)
    _require_can_manage(db, session, current_user)
    db.delete(resource)
    db.commit()
    return {"message": "Resource removed"}


# ---------------------------------------------------------------- polls

@router.post("/sessions/{session_id}/polls", response_model=schemas.LiveSessionPollOut, status_code=201)
def create_poll(
    session_id: int,
    payload: schemas.LiveSessionPollCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 22: live polls during a session."""
    session = _get_session_or_404(db, session_id)
    _require_can_manage(db, session, current_user)
    if len(payload.options) < 2:
        raise HTTPException(status_code=400, detail="A poll needs at least 2 options")
    poll = models.LiveSessionPoll(session_id=session_id, question=payload.question, created_by=current_user.id)
    db.add(poll)
    db.commit()
    db.refresh(poll)
    for i, text in enumerate(payload.options):
        db.add(models.LiveSessionPollOption(poll_id=poll.id, text=text, order=i))
    db.commit()
    return _poll_out(db, poll, current_user.id)


def _poll_out(db: Session, poll: models.LiveSessionPoll, viewer_id: Optional[int] = None) -> schemas.LiveSessionPollOut:
    options = db.query(models.LiveSessionPollOption).filter(
        models.LiveSessionPollOption.poll_id == poll.id
    ).order_by(models.LiveSessionPollOption.order.asc()).all()
    votes = db.query(models.LiveSessionPollVote).filter(models.LiveSessionPollVote.poll_id == poll.id).all()
    my_vote = None
    option_outs = []
    for o in options:
        count = sum(1 for v in votes if v.option_id == o.id)
        option_outs.append(schemas.LiveSessionPollOptionOut(id=o.id, text=o.text, vote_count=count))
    if viewer_id:
        mine = next((v for v in votes if v.user_id == viewer_id), None)
        my_vote = mine.option_id if mine else None
    return schemas.LiveSessionPollOut(
        id=poll.id, question=poll.question, is_closed=poll.is_closed,
        options=option_outs, total_votes=len(votes), my_vote_option_id=my_vote,
    )


@router.get("/sessions/{session_id}/polls", response_model=List[schemas.LiveSessionPollOut])
def list_polls(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    polls = db.query(models.LiveSessionPoll).filter(
        models.LiveSessionPoll.session_id == session_id
    ).order_by(models.LiveSessionPoll.created_at.desc()).all()
    viewer_id = current_user.id if current_user else None
    return [_poll_out(db, p, viewer_id) for p in polls]


@router.post("/polls/{poll_id}/vote", response_model=schemas.LiveSessionPollOut)
def vote_poll(
    poll_id: int,
    payload: schemas.LiveSessionPollVoteCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    poll = db.query(models.LiveSessionPoll).filter(models.LiveSessionPoll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    if poll.is_closed:
        raise HTTPException(status_code=400, detail="This poll is closed")
    option = db.query(models.LiveSessionPollOption).filter(
        models.LiveSessionPollOption.id == payload.option_id, models.LiveSessionPollOption.poll_id == poll_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")
    existing = db.query(models.LiveSessionPollVote).filter(
        models.LiveSessionPollVote.poll_id == poll_id, models.LiveSessionPollVote.user_id == current_user.id
    ).first()
    if existing:
        existing.option_id = payload.option_id
    else:
        db.add(models.LiveSessionPollVote(poll_id=poll_id, option_id=payload.option_id, user_id=current_user.id))
    db.commit()
    return _poll_out(db, poll, current_user.id)


@router.put("/polls/{poll_id}/close")
def close_poll(
    poll_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    poll = db.query(models.LiveSessionPoll).filter(models.LiveSessionPoll.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    session = _get_session_or_404(db, poll.session_id)
    _require_can_manage(db, session, current_user)
    poll.is_closed = True
    db.commit()
    return {"message": "Poll closed"}


# ---------------------------------------------------------------- Q&A queue

@router.post("/sessions/{session_id}/questions", response_model=schemas.LiveSessionQuestionOut, status_code=201)
def ask_question(
    session_id: int,
    payload: schemas.LiveSessionQuestionCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 23: structured Q&A queue, separate from free-flowing chat."""
    _get_session_or_404(db, session_id)
    if _is_banned(db, session_id, current_user.id):
        raise HTTPException(status_code=403, detail="You have been removed from this session")
    question = models.LiveSessionQuestion(session_id=session_id, user_id=current_user.id, question=payload.question)
    db.add(question)
    db.commit()
    db.refresh(question)
    return schemas.LiveSessionQuestionOut(
        id=question.id, user_id=current_user.id, author_name=current_user.full_name,
        question=question.question, answer=None, is_answered=False,
        upvote_count=0, upvoted_by_me=False, created_at=question.created_at,
    )


@router.get("/sessions/{session_id}/questions", response_model=List[schemas.LiveSessionQuestionOut])
def list_questions(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    questions = db.query(models.LiveSessionQuestion).filter(
        models.LiveSessionQuestion.session_id == session_id
    ).all()
    upvotes = db.query(models.LiveSessionQuestionUpvote).filter(
        models.LiveSessionQuestionUpvote.question_id.in_([q.id for q in questions] or [-1])
    ).all()
    out = []
    for q in questions:
        author = db.query(models.User).filter(models.User.id == q.user_id).first()
        q_upvotes = [u for u in upvotes if u.question_id == q.id]
        out.append(schemas.LiveSessionQuestionOut(
            id=q.id, user_id=q.user_id, author_name=author.full_name if author else "Unknown",
            question=q.question, answer=q.answer, is_answered=q.is_answered,
            upvote_count=len(q_upvotes),
            upvoted_by_me=bool(current_user and any(u.user_id == current_user.id for u in q_upvotes)),
            created_at=q.created_at,
        ))
    # Most-upvoted, unanswered questions first.
    out.sort(key=lambda x: (x.is_answered, -x.upvote_count))
    return out


@router.post("/questions/{question_id}/upvote")
def upvote_question(
    question_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    question = db.query(models.LiveSessionQuestion).filter(models.LiveSessionQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    existing = db.query(models.LiveSessionQuestionUpvote).filter(
        models.LiveSessionQuestionUpvote.question_id == question_id,
        models.LiveSessionQuestionUpvote.user_id == current_user.id,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"message": "Upvote removed"}
    db.add(models.LiveSessionQuestionUpvote(question_id=question_id, user_id=current_user.id))
    db.commit()
    return {"message": "Upvoted"}


@router.put("/questions/{question_id}/answer")
def answer_question(
    question_id: int,
    payload: schemas.LiveSessionQuestionAnswer,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    question = db.query(models.LiveSessionQuestion).filter(models.LiveSessionQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    session = _get_session_or_404(db, question.session_id)
    _require_can_manage(db, session, current_user)
    question.answer = payload.answer
    question.is_answered = True
    db.commit()
    return {"message": "Answered"}


# ---------------------------------------------------------------- presence / typing

@router.post("/sessions/{session_id}/presence", response_model=schemas.LiveSessionPresenceOut)
def ping_presence(
    session_id: int,
    payload: schemas.LiveSessionTypingPing,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 8 + 33: typing indicator heartbeat and live viewer count."""
    row = db.query(models.LiveSessionPresence).filter(
        models.LiveSessionPresence.session_id == session_id,
        models.LiveSessionPresence.user_id == current_user.id,
    ).first()
    now = datetime.utcnow()
    if row:
        row.is_typing = payload.is_typing
        row.last_seen = now
    else:
        db.add(models.LiveSessionPresence(
            session_id=session_id, user_id=current_user.id, is_typing=payload.is_typing, last_seen=now
        ))
    db.commit()
    return _presence_out(db, session_id, current_user.id)


@router.get("/sessions/{session_id}/presence", response_model=schemas.LiveSessionPresenceOut)
def get_presence(session_id: int, db: Session = Depends(get_db)):
    return _presence_out(db, session_id, None)


def _presence_out(db: Session, session_id: int, exclude_user_id: Optional[int]) -> schemas.LiveSessionPresenceOut:
    typing_cutoff = datetime.utcnow() - timedelta(seconds=TYPING_WINDOW_SECONDS)
    typing_rows = db.query(models.LiveSessionPresence).filter(
        models.LiveSessionPresence.session_id == session_id,
        models.LiveSessionPresence.is_typing == True,  # noqa: E712
        models.LiveSessionPresence.last_seen >= typing_cutoff,
    ).all()
    typing_names = []
    for row in typing_rows:
        if exclude_user_id and row.user_id == exclude_user_id:
            continue
        user = db.query(models.User).filter(models.User.id == row.user_id).first()
        if user:
            typing_names.append(user.full_name)
    return schemas.LiveSessionPresenceOut(viewer_count=_viewer_count(db, session_id), typing_names=typing_names)


# ---------------------------------------------------------------- messages

@router.get("/sessions/{session_id}/messages", response_model=List[schemas.LiveMessageOut])
def get_messages(
    session_id: int,
    after_id: int = 0,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """Client polls this every few seconds, passing the last message id it has."""
    messages = db.query(models.LiveMessage).filter(
        models.LiveMessage.session_id == session_id, models.LiveMessage.id > after_id
    ).order_by(models.LiveMessage.created_at.asc()).limit(100).all()
    viewer_id = current_user.id if current_user else None
    return [_message_out(db, m, viewer_id) for m in messages]


@router.get("/sessions/{session_id}/messages/search", response_model=List[schemas.LiveMessageOut])
def search_messages(
    session_id: int,
    q: str,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    """Feature 9: search messages within a session."""
    messages = db.query(models.LiveMessage).filter(
        models.LiveMessage.session_id == session_id,
        models.LiveMessage.is_deleted == False,  # noqa: E712
        models.LiveMessage.content.ilike(f"%{q}%"),
    ).order_by(models.LiveMessage.created_at.asc()).limit(100).all()
    viewer_id = current_user.id if current_user else None
    return [_message_out(db, m, viewer_id) for m in messages]


@router.get("/sessions/{session_id}/transcript")
def export_transcript(session_id: int, db: Session = Depends(get_db)):
    """Feature 14: export chat transcript as plain text."""
    session = _get_session_or_404(db, session_id)
    messages = db.query(models.LiveMessage).filter(
        models.LiveMessage.session_id == session_id
    ).order_by(models.LiveMessage.created_at.asc()).all()
    lines = [f"Transcript — {session.title}", "=" * 40, ""]
    for m in messages:
        if m.is_system:
            lines.append(f"[{m.created_at.strftime('%Y-%m-%d %H:%M')}] *** {m.content} ***")
            continue
        author = db.query(models.User).filter(models.User.id == m.user_id).first()
        content = "[message deleted]" if m.is_deleted else m.content
        lines.append(f"[{m.created_at.strftime('%Y-%m-%d %H:%M')}] {author.full_name if author else 'Unknown'}: {content}")
    return PlainTextResponse("\n".join(lines), media_type="text/plain", headers={
        "Content-Disposition": f'attachment; filename="session-{session_id}-transcript.txt"'
    })


@router.post("/sessions/{session_id}/messages", response_model=schemas.LiveMessageOut, status_code=201)
def post_message(
    session_id: int,
    payload: schemas.LiveMessageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_session_or_404(db, session_id)

    if _is_banned(db, session_id, current_user.id):
        raise HTTPException(status_code=403, detail="You have been removed from this session")
    if _is_muted(db, session_id, current_user.id):
        raise HTTPException(status_code=403, detail="You have been muted in this session")

    # Feature 34: announcement-only mode — only host/co-hosts/staff may post.
    if session.announcement_only and not _can_manage(db, session, current_user):
        raise HTTPException(status_code=403, detail="This session is in announcement-only mode")

    # Feature 13: character limit.
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(content) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail=f"Messages are limited to {MAX_MESSAGE_LENGTH} characters")

    # Feature 10: slow mode.
    if session.slow_mode_seconds and not _can_manage(db, session, current_user):
        last = db.query(models.LiveMessage).filter(
            models.LiveMessage.session_id == session_id, models.LiveMessage.user_id == current_user.id,
        ).order_by(models.LiveMessage.created_at.desc()).first()
        if last:
            elapsed = (datetime.utcnow() - last.created_at).total_seconds()
            if elapsed < session.slow_mode_seconds:
                wait = int(session.slow_mode_seconds - elapsed)
                raise HTTPException(status_code=429, detail=f"Slow mode is on — wait {wait}s before sending another message")

    if payload.reply_to_id:
        parent = db.query(models.LiveMessage).filter(
            models.LiveMessage.id == payload.reply_to_id, models.LiveMessage.session_id == session_id
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="The message you're replying to was not found")

    msg = models.LiveMessage(
        session_id=session_id, user_id=current_user.id, content=content, reply_to_id=payload.reply_to_id
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return _message_out(db, msg, current_user.id)


@router.put("/messages/{message_id}", response_model=schemas.LiveMessageOut)
def edit_message(
    message_id: int,
    payload: schemas.LiveMessageEdit,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 1: edit own message within a short window."""
    msg = db.query(models.LiveMessage).filter(models.LiveMessage.id == message_id).first()
    if not msg or msg.is_deleted:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")
    if (datetime.utcnow() - msg.created_at).total_seconds() > EDIT_WINDOW_MINUTES * 60:
        raise HTTPException(status_code=400, detail=f"Messages can only be edited within {EDIT_WINDOW_MINUTES} minutes")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(content) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail=f"Messages are limited to {MAX_MESSAGE_LENGTH} characters")
    msg.content = content
    msg.edited_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)
    return _message_out(db, msg, current_user.id)


@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Features 2 & 3: soft-delete own message, or staff/host delete any message."""
    msg = db.query(models.LiveMessage).filter(models.LiveMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    session = _get_session_or_404(db, msg.session_id)
    if msg.user_id != current_user.id and not _can_manage(db, session, current_user):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this message")
    msg.is_deleted = True
    db.commit()
    return {"message": "Message deleted"}


@router.put("/messages/{message_id}/pin")
def toggle_pin(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 7: pin/unpin an important message."""
    msg = db.query(models.LiveMessage).filter(models.LiveMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    session = _get_session_or_404(db, msg.session_id)
    _require_can_manage(db, session, current_user)
    msg.is_pinned = not msg.is_pinned
    db.commit()
    return {"message": "Updated", "is_pinned": msg.is_pinned}


@router.post("/messages/{message_id}/reactions")
def toggle_reaction(
    message_id: int,
    payload: schemas.LiveMessageReactionToggle,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feature 4: emoji reactions on messages (toggle add/remove)."""
    msg = db.query(models.LiveMessage).filter(models.LiveMessage.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    existing = db.query(models.LiveMessageReaction).filter(
        models.LiveMessageReaction.message_id == message_id,
        models.LiveMessageReaction.user_id == current_user.id,
        models.LiveMessageReaction.emoji == payload.emoji,
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"message": "Reaction removed"}
    db.add(models.LiveMessageReaction(message_id=message_id, user_id=current_user.id, emoji=payload.emoji))
    db.commit()
    return {"message": "Reaction added"}
