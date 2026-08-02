from datetime import date
from typing import List
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff

router = APIRouter(prefix="/api/progress", tags=["progress"])


@router.get("/summary")
def reading_summary(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    completed = db.query(models.ReadingProgress).filter(
        models.ReadingProgress.user_id == current_user.id,
        models.ReadingProgress.status == "completed",
    ).count()
    reading = db.query(models.ReadingProgress).filter(
        models.ReadingProgress.user_id == current_user.id,
        models.ReadingProgress.status == "reading",
    ).count()
    total_pages = db.query(models.Book).join(
        models.ReadingProgress, models.ReadingProgress.book_id == models.Book.id
    ).filter(
        models.ReadingProgress.user_id == current_user.id,
        models.ReadingProgress.status == "completed",
    ).with_entities(models.Book.number_of_pages).all()
    pages_read = sum(p[0] or 0 for p in total_pages)
    streak = db.query(models.ReadingStreak).filter(
        models.ReadingStreak.user_id == current_user.id
    ).first()
    return {
        "books_completed": completed,
        "books_in_progress": reading,
        "pages_read": pages_read,
        "current_streak": streak.current_streak if streak else 0,
        "longest_streak": streak.longest_streak if streak else 0,
    }


@router.get("/streak", response_model=schemas.StreakOut)
def get_streak(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    streak = db.query(models.ReadingStreak).filter(
        models.ReadingStreak.user_id == current_user.id
    ).first()
    if not streak:
        streak = models.ReadingStreak(user_id=current_user.id, current_streak=0, longest_streak=0)
        db.add(streak)
        db.commit()
        db.refresh(streak)
    return streak


# ---------- Goals ----------

@router.get("/goals", response_model=List[schemas.GoalOut])
def list_goals(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.ReadingGoal).filter(
        models.ReadingGoal.user_id == current_user.id
    ).order_by(models.ReadingGoal.created_at.desc()).all()


@router.post("/goals", response_model=schemas.GoalOut, status_code=201)
def create_goal(
    payload: schemas.GoalCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = models.ReadingGoal(user_id=current_user.id, **payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.put("/goals/{goal_id}", response_model=schemas.GoalOut)
def update_goal(
    goal_id: int,
    payload: schemas.GoalUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.query(models.ReadingGoal).filter(
        models.ReadingGoal.id == goal_id, models.ReadingGoal.user_id == current_user.id
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.target_books = payload.target_books
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/goals/{goal_id}")
def delete_goal(
    goal_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    goal = db.query(models.ReadingGoal).filter(
        models.ReadingGoal.id == goal_id, models.ReadingGoal.user_id == current_user.id
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    db.delete(goal)
    db.commit()
    return {"message": "Goal deleted"}


# ---------- Challenges ----------

def _challenge_out(db: Session, c: models.Challenge) -> schemas.ChallengeOut:
    count = db.query(models.ChallengeParticipant).filter(
        models.ChallengeParticipant.challenge_id == c.id
    ).count()
    data = schemas.ChallengeOut.model_validate(c).model_dump()
    data["participant_count"] = count
    return schemas.ChallengeOut(**data)


@router.get("/challenges", response_model=List[schemas.ChallengeOut])
def list_challenges(db: Session = Depends(get_db)):
    challenges = db.query(models.Challenge).order_by(models.Challenge.start_date.desc()).all()
    return [_challenge_out(db, c) for c in challenges]


@router.post("/challenges", response_model=schemas.ChallengeOut, status_code=201)
def create_challenge(
    payload: schemas.ChallengeCreate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    challenge = models.Challenge(**payload.model_dump())
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return _challenge_out(db, challenge)


@router.post("/challenges/{challenge_id}/join")
def join_challenge(
    challenge_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    challenge = db.query(models.Challenge).filter(models.Challenge.id == challenge_id).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    existing = db.query(models.ChallengeParticipant).filter(
        models.ChallengeParticipant.challenge_id == challenge_id,
        models.ChallengeParticipant.user_id == current_user.id,
    ).first()
    if existing:
        return {"message": "Already joined"}
    db.add(models.ChallengeParticipant(challenge_id=challenge_id, user_id=current_user.id))
    db.commit()
    return {"message": "Joined challenge"}


@router.get("/challenges/{challenge_id}/my-status")
def my_challenge_status(
    challenge_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    participant = db.query(models.ChallengeParticipant).filter(
        models.ChallengeParticipant.challenge_id == challenge_id,
        models.ChallengeParticipant.user_id == current_user.id,
    ).first()
    if not participant:
        return {"joined": False}
    return {
        "joined": True,
        "books_completed": participant.books_completed,
        "is_completed": participant.is_completed,
    }


# ---------- Leaderboard ----------

@router.get("/leaderboard", response_model=List[schemas.LeaderboardEntry])
def leaderboard(
    limit: int = 10,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func
    completions = dict(
        db.query(models.ReadingProgress.user_id, func.count(models.ReadingProgress.id))
        .filter(models.ReadingProgress.status == "completed")
        .group_by(models.ReadingProgress.user_id)
        .all()
    )
    streaks = {s.user_id: s.current_streak for s in db.query(models.ReadingStreak).all()}
    users = db.query(models.User).filter(models.User.role == "member").all()

    entries = []
    for u in users:
        entries.append(schemas.LeaderboardEntry(
            user_id=u.id, full_name=u.full_name,
            books_completed=completions.get(u.id, 0), current_streak=streaks.get(u.id, 0),
        ))
    entries.sort(key=lambda e: (e.books_completed, e.current_streak), reverse=True)
    return entries[:limit]


# ---------- Reading History Timeline ----------

@router.get("/history")
def reading_history(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    completed = db.query(models.ReadingProgress).filter(
        models.ReadingProgress.user_id == current_user.id,
        models.ReadingProgress.status == "completed",
    ).order_by(models.ReadingProgress.completed_at.desc()).all()

    timeline = []
    for p in completed:
        book = db.query(models.Book).filter(models.Book.id == p.book_id).first()
        if book:
            timeline.append({
                "type": "book_completed", "book_title": book.title, "book_id": book.id,
                "date": p.completed_at.isoformat() if p.completed_at else None,
            })
    return timeline


@router.get("/history/export")
def export_reading_history_csv(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    completed = db.query(models.ReadingProgress).filter(
        models.ReadingProgress.user_id == current_user.id,
        models.ReadingProgress.status == "completed",
    ).order_by(models.ReadingProgress.completed_at.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Book Title", "Author", "Category", "Completed At"])
    for p in completed:
        book = db.query(models.Book).filter(models.Book.id == p.book_id).first()
        if book:
            writer.writerow([book.title, book.author, book.category, p.completed_at.isoformat() if p.completed_at else ""])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reading_history.csv"},
    )
