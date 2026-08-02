from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff

router = APIRouter(prefix="/api/clubs", tags=["clubs"])


def _club_out(db: Session, club: models.ReadingClub, user_id: int) -> schemas.ClubOut:
    member_count = db.query(models.ClubMembership).filter(
        models.ClubMembership.club_id == club.id
    ).count()
    membership = db.query(models.ClubMembership).filter(
        models.ClubMembership.club_id == club.id, models.ClubMembership.user_id == user_id
    ).first()
    return schemas.ClubOut(
        id=club.id, name=club.name, school_or_org=club.school_or_org,
        description=club.description, member_count=member_count,
        is_member=membership is not None, is_leader=bool(membership and membership.is_leader),
    )


def _event_out(db: Session, event: models.ClubEvent, user_id: Optional[int]) -> schemas.ClubEventOut:
    rsvp_count = db.query(models.ClubEventRSVP).filter(models.ClubEventRSVP.event_id == event.id).count()
    is_attending = False
    if user_id:
        is_attending = db.query(models.ClubEventRSVP).filter(
            models.ClubEventRSVP.event_id == event.id, models.ClubEventRSVP.user_id == user_id
        ).first() is not None
    return schemas.ClubEventOut(
        id=event.id, title=event.title, description=event.description, event_date=event.event_date,
        is_cancelled=event.is_cancelled, rsvp_count=rsvp_count, is_attending=is_attending,
        created_at=event.created_at,
    )


def _is_leader_or_staff(db: Session, club_id: int, user: models.User) -> bool:
    if user.role in ("admin", "moderator"):
        return True
    membership = db.query(models.ClubMembership).filter(
        models.ClubMembership.club_id == club_id, models.ClubMembership.user_id == user.id
    ).first()
    return bool(membership and membership.is_leader)


@router.get("", response_model=List[schemas.ClubOut])
def list_clubs(
    school: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(models.ReadingClub)
    if school:
        q = q.filter(models.ReadingClub.school_or_org.ilike(f"%{school}%"))
    clubs = q.order_by(models.ReadingClub.created_at.desc()).all()
    return [_club_out(db, c, current_user.id) for c in clubs]


@router.post("", response_model=schemas.ClubOut, status_code=201)
def create_club(
    payload: schemas.ClubCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "moderator", "mentor"):
        raise HTTPException(status_code=403, detail="Only staff or mentors can start a club")
    club = models.ReadingClub(**payload.model_dump(), created_by=current_user.id)
    db.add(club)
    db.commit()
    db.refresh(club)
    db.add(models.ClubMembership(club_id=club.id, user_id=current_user.id, is_leader=True))
    db.commit()
    return _club_out(db, club, current_user.id)


@router.get("/{club_id}", response_model=schemas.ClubOut)
def get_club(
    club_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    club = db.query(models.ReadingClub).filter(models.ReadingClub.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    return _club_out(db, club, current_user.id)


@router.put("/{club_id}", response_model=schemas.ClubOut)
def update_club(
    club_id: int,
    payload: schemas.ClubUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    club = db.query(models.ReadingClub).filter(models.ReadingClub.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    if not _is_leader_or_staff(db, club_id, current_user):
        raise HTTPException(status_code=403, detail="Only the club leader or staff can edit this club")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(club, field, value)
    db.commit()
    db.refresh(club)
    return _club_out(db, club, current_user.id)


@router.delete("/{club_id}")
def delete_club(
    club_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    club = db.query(models.ReadingClub).filter(models.ReadingClub.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    if not _is_leader_or_staff(db, club_id, current_user):
        raise HTTPException(status_code=403, detail="Only the club leader or staff can delete this club")
    event_ids = [e.id for e in db.query(models.ClubEvent.id).filter(models.ClubEvent.club_id == club_id).all()]
    if event_ids:
        db.query(models.ClubEventRSVP).filter(models.ClubEventRSVP.event_id.in_(event_ids)).delete(synchronize_session=False)
    db.query(models.ClubEvent).filter(models.ClubEvent.club_id == club_id).delete()
    db.query(models.ClubMembership).filter(models.ClubMembership.club_id == club_id).delete()
    db.delete(club)
    db.commit()
    return {"message": "Club deleted"}


@router.post("/{club_id}/join")
def join_club(
    club_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    club = db.query(models.ReadingClub).filter(models.ReadingClub.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    existing = db.query(models.ClubMembership).filter(
        models.ClubMembership.club_id == club_id, models.ClubMembership.user_id == current_user.id
    ).first()
    if existing:
        return {"message": "Already a member"}
    db.add(models.ClubMembership(club_id=club_id, user_id=current_user.id))
    db.commit()
    return {"message": f"Joined {club.name}"}


@router.delete("/{club_id}/leave")
def leave_club(
    club_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = db.query(models.ClubMembership).filter(
        models.ClubMembership.club_id == club_id, models.ClubMembership.user_id == current_user.id
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="You are not a member of this club")
    if membership.is_leader:
        other_leader = db.query(models.ClubMembership).filter(
            models.ClubMembership.club_id == club_id, models.ClubMembership.is_leader == True,  # noqa: E712
            models.ClubMembership.user_id != current_user.id,
        ).first()
        if not other_leader:
            raise HTTPException(
                status_code=400,
                detail="You're the only leader — promote another member or delete the club instead of leaving",
            )
    db.delete(membership)
    db.commit()
    return {"message": "Left the club"}


@router.get("/{club_id}/members")
def list_members(club_id: int, db: Session = Depends(get_db)):
    memberships = db.query(models.ClubMembership).filter(
        models.ClubMembership.club_id == club_id
    ).all()
    out = []
    for m in memberships:
        user = db.query(models.User).filter(models.User.id == m.user_id).first()
        out.append({"user_id": m.user_id, "name": user.full_name if user else "Unknown", "is_leader": m.is_leader})
    return out


@router.delete("/{club_id}/members/{user_id}")
def remove_member(
    club_id: int,
    user_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _is_leader_or_staff(db, club_id, current_user):
        raise HTTPException(status_code=403, detail="Only the club leader or staff can remove members")
    membership = db.query(models.ClubMembership).filter(
        models.ClubMembership.club_id == club_id, models.ClubMembership.user_id == user_id
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this club")
    if membership.is_leader and user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Leaders can't remove themselves — use leave instead")
    db.delete(membership)
    db.commit()
    return {"message": "Member removed"}


@router.get("/{club_id}/events", response_model=List[schemas.ClubEventOut])
def list_events(
    club_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    events = db.query(models.ClubEvent).filter(
        models.ClubEvent.club_id == club_id
    ).order_by(models.ClubEvent.event_date.asc()).all()
    return [_event_out(db, e, current_user.id) for e in events]


@router.post("/{club_id}/events", response_model=schemas.ClubEventOut, status_code=201)
def create_event(
    club_id: int,
    payload: schemas.ClubEventCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not _is_leader_or_staff(db, club_id, current_user):
        raise HTTPException(status_code=403, detail="Only club leaders or staff can add events")
    club = db.query(models.ReadingClub).filter(models.ReadingClub.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    event = models.ClubEvent(club_id=club_id, **payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_out(db, event, current_user.id)


@router.put("/events/{event_id}", response_model=schemas.ClubEventOut)
def update_event(
    event_id: int,
    payload: schemas.ClubEventUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(models.ClubEvent).filter(models.ClubEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not _is_leader_or_staff(db, event.club_id, current_user):
        raise HTTPException(status_code=403, detail="Only club leaders or staff can edit events")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return _event_out(db, event, current_user.id)


@router.delete("/events/{event_id}")
def cancel_event(
    event_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(models.ClubEvent).filter(models.ClubEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not _is_leader_or_staff(db, event.club_id, current_user):
        raise HTTPException(status_code=403, detail="Only club leaders or staff can cancel events")
    event.is_cancelled = True
    db.commit()
    return {"message": "Event cancelled"}


@router.post("/events/{event_id}/rsvp")
def rsvp_event(
    event_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.query(models.ClubEvent).filter(models.ClubEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    existing = db.query(models.ClubEventRSVP).filter(
        models.ClubEventRSVP.event_id == event_id, models.ClubEventRSVP.user_id == current_user.id
    ).first()
    if existing:
        return {"message": "Already RSVP'd"}
    db.add(models.ClubEventRSVP(event_id=event_id, user_id=current_user.id))
    db.commit()
    count = db.query(models.ClubEventRSVP).filter(models.ClubEventRSVP.event_id == event_id).count()
    return {"message": "RSVP'd", "rsvp_count": count}


@router.delete("/events/{event_id}/rsvp")
def cancel_rsvp(
    event_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(models.ClubEventRSVP).filter(
        models.ClubEventRSVP.event_id == event_id, models.ClubEventRSVP.user_id == current_user.id
    ).delete()
    db.commit()
    count = db.query(models.ClubEventRSVP).filter(models.ClubEventRSVP.event_id == event_id).count()
    return {"message": "RSVP cancelled", "rsvp_count": count}
