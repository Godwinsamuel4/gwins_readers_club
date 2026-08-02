from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_mentor_or_admin

router = APIRouter(prefix="/api/mentors", tags=["mentorship"])


def _rating_stats(db: Session, mentor_id: int):
    row = db.query(
        func.avg(models.MentorRating.rating), func.count(models.MentorRating.id)
    ).filter(models.MentorRating.mentor_id == mentor_id).first()
    avg, count = row
    return (round(avg, 1) if avg else None), (count or 0)


@router.get("", response_model=List[schemas.MentorProfileOut])
def list_mentors(db: Session = Depends(get_db)):
    profiles = db.query(models.MentorProfile).filter(
        models.MentorProfile.is_accepting_mentees == True  # noqa: E712
    ).all()
    out = []
    for p in profiles:
        user = db.query(models.User).filter(models.User.id == p.user_id).first()
        avg_rating, rating_count = _rating_stats(db, p.user_id)
        out.append(schemas.MentorProfileOut(
            user_id=p.user_id, mentor_name=user.full_name if user else "Unknown",
            specialties=p.specialties, bio=p.bio, is_accepting_mentees=p.is_accepting_mentees,
            average_rating=avg_rating, rating_count=rating_count,
        ))
    return out


@router.post("/become-a-mentor", response_model=schemas.MentorProfileOut)
def become_mentor(
    payload: schemas.BecomeMentorPayload,
    current_user: models.User = Depends(require_mentor_or_admin),
    db: Session = Depends(get_db),
):
    profile = db.query(models.MentorProfile).filter(
        models.MentorProfile.user_id == current_user.id
    ).first()
    if not profile:
        profile = models.MentorProfile(user_id=current_user.id)
        db.add(profile)
    profile.specialties = payload.specialties
    profile.bio = payload.bio
    profile.is_accepting_mentees = True
    db.commit()
    db.refresh(profile)
    avg_rating, rating_count = _rating_stats(db, current_user.id)
    return schemas.MentorProfileOut(
        user_id=profile.user_id, mentor_name=current_user.full_name,
        specialties=profile.specialties, bio=profile.bio,
        is_accepting_mentees=profile.is_accepting_mentees,
        average_rating=avg_rating, rating_count=rating_count,
    )


@router.post("/{mentor_id}/request", response_model=schemas.MentorshipRequestOut, status_code=201)
def request_mentorship(
    mentor_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mentor = db.query(models.User).filter(models.User.id == mentor_id, models.User.role == "mentor").first()
    if not mentor:
        raise HTTPException(status_code=404, detail="Mentor not found")
    existing = db.query(models.MentorshipRequest).filter(
        models.MentorshipRequest.mentor_id == mentor_id,
        models.MentorshipRequest.mentee_id == current_user.id,
        models.MentorshipRequest.status.in_(["pending", "accepted"]),
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have an active request with this mentor")
    req = models.MentorshipRequest(mentor_id=mentor_id, mentee_id=current_user.id)
    db.add(req)
    db.commit()
    db.refresh(req)
    return schemas.MentorshipRequestOut(
        id=req.id, mentor_id=mentor_id, mentor_name=mentor.full_name,
        mentee_id=current_user.id, mentee_name=current_user.full_name,
        status=req.status, requested_at=req.requested_at,
    )


@router.get("/requests/mine", response_model=List[schemas.MentorshipRequestOut])
def my_requests(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reqs = db.query(models.MentorshipRequest).filter(
        (models.MentorshipRequest.mentor_id == current_user.id)
        | (models.MentorshipRequest.mentee_id == current_user.id)
    ).order_by(models.MentorshipRequest.requested_at.desc()).all()
    out = []
    for r in reqs:
        mentor = db.query(models.User).filter(models.User.id == r.mentor_id).first()
        mentee = db.query(models.User).filter(models.User.id == r.mentee_id).first()
        out.append(schemas.MentorshipRequestOut(
            id=r.id, mentor_id=r.mentor_id, mentor_name=mentor.full_name if mentor else "Unknown",
            mentee_id=r.mentee_id, mentee_name=mentee.full_name if mentee else "Unknown",
            status=r.status, requested_at=r.requested_at,
        ))
    return out


@router.put("/requests/{request_id}")
def respond_to_request(
    request_id: int,
    status: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if status not in ("accepted", "declined", "ended"):
        raise HTTPException(status_code=400, detail="Invalid status")
    req = db.query(models.MentorshipRequest).filter(models.MentorshipRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if status == "ended":
        # Either party can end an active mentorship; only the mentor can accept/decline.
        if current_user.id not in (req.mentor_id, req.mentee_id) and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not part of this mentorship")
    elif req.mentor_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the mentor can respond to this request")
    req.status = status
    db.commit()
    return {"message": f"Request {status}"}


@router.post("/requests/{request_id}/questions", response_model=schemas.MentorQuestionOut, status_code=201)
def ask_question(
    request_id: int,
    payload: schemas.MentorQuestionCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(models.MentorshipRequest).filter(
        models.MentorshipRequest.id == request_id, models.MentorshipRequest.status == "accepted"
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="No active mentorship found")
    if current_user.id not in (req.mentor_id, req.mentee_id):
        raise HTTPException(status_code=403, detail="Not part of this mentorship")
    q = models.MentorQuestion(mentorship_id=request_id, asked_by=current_user.id, question=payload.question)
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.get("/requests/{request_id}/questions", response_model=List[schemas.MentorQuestionOut])
def list_questions(
    request_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(models.MentorshipRequest).filter(models.MentorshipRequest.id == request_id).first()
    if not req or current_user.id not in (req.mentor_id, req.mentee_id):
        raise HTTPException(status_code=403, detail="Not part of this mentorship")
    return db.query(models.MentorQuestion).filter(
        models.MentorQuestion.mentorship_id == request_id
    ).order_by(models.MentorQuestion.created_at.asc()).all()


@router.put("/questions/{question_id}/answer", response_model=schemas.MentorQuestionOut)
def answer_question(
    question_id: int,
    payload: schemas.AnswerPayload,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(models.MentorQuestion).filter(models.MentorQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    req = db.query(models.MentorshipRequest).filter(models.MentorshipRequest.id == q.mentorship_id).first()
    if not req or req.mentor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the mentor can answer")
    from datetime import datetime
    q.answer = payload.answer
    q.answered_at = datetime.utcnow()
    db.commit()
    db.refresh(q)
    return q


@router.post("/requests/{request_id}/rate", response_model=schemas.MentorRatingOut, status_code=201)
def rate_mentor(
    request_id: int,
    payload: schemas.MentorRatingCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = db.query(models.MentorshipRequest).filter(models.MentorshipRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Mentorship not found")
    if req.mentee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the mentee can rate this mentorship")
    if req.status != "ended":
        raise HTTPException(status_code=400, detail="You can only rate a mentorship after it has ended")
    existing = db.query(models.MentorRating).filter(models.MentorRating.mentorship_id == request_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already rated this mentorship")
    rating = models.MentorRating(
        mentorship_id=request_id, mentor_id=req.mentor_id, mentee_id=current_user.id,
        rating=payload.rating, review_text=payload.review_text,
    )
    db.add(rating)
    db.commit()
    db.refresh(rating)
    return schemas.MentorRatingOut(
        id=rating.id, mentorship_id=rating.mentorship_id, mentor_id=rating.mentor_id,
        mentee_id=rating.mentee_id, mentee_name=current_user.full_name,
        rating=rating.rating, review_text=rating.review_text, created_at=rating.created_at,
    )


@router.get("/{mentor_id}/ratings", response_model=List[schemas.MentorRatingOut])
def get_mentor_ratings(mentor_id: int, db: Session = Depends(get_db)):
    ratings = db.query(models.MentorRating).filter(
        models.MentorRating.mentor_id == mentor_id
    ).order_by(models.MentorRating.created_at.desc()).all()
    out = []
    for r in ratings:
        mentee = db.query(models.User).filter(models.User.id == r.mentee_id).first()
        out.append(schemas.MentorRatingOut(
            id=r.id, mentorship_id=r.mentorship_id, mentor_id=r.mentor_id,
            mentee_id=r.mentee_id, mentee_name=mentee.full_name if mentee else "Unknown",
            rating=r.rating, review_text=r.review_text, created_at=r.created_at,
        ))
    return out
