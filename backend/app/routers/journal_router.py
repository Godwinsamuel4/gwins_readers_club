from datetime import datetime
from typing import List, Optional
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user

router = APIRouter(prefix="/api/journal", tags=["journal"])

VALID_TYPES = {"reflection", "note", "quote", "prayer", "action_plan", "weekly_reflection"}

WEEKLY_QUESTIONS = [
    "What did you learn this week?",
    "Which chapter inspired you most?",
    "What action will you take?",
    "What's your favorite quote from this week's reading?",
]


@router.get("/questions/weekly")
def get_weekly_questions():
    return WEEKLY_QUESTIONS


@router.get("", response_model=List[schemas.JournalEntryOut])
def list_entries(
    entry_type: Optional[str] = None,
    book_id: Optional[int] = None,
    keyword: Optional[str] = None,
    date_from: Optional[date_type] = None,
    date_to: Optional[date_type] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(models.JournalEntry).filter(models.JournalEntry.user_id == current_user.id)
    if entry_type:
        q = q.filter(models.JournalEntry.entry_type == entry_type)
    if book_id:
        q = q.filter(models.JournalEntry.book_id == book_id)
    if keyword:
        q = q.filter(models.JournalEntry.content.ilike(f"%{keyword}%"))
    if date_from:
        q = q.filter(models.JournalEntry.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(models.JournalEntry.created_at <= datetime.combine(date_to, datetime.max.time()))
    return q.order_by(models.JournalEntry.created_at.desc()).all()


@router.post("", response_model=schemas.JournalEntryOut, status_code=201)
def create_entry(
    payload: schemas.JournalEntryCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry_type = payload.entry_type if payload.entry_type in VALID_TYPES else "reflection"
    entry = models.JournalEntry(
        user_id=current_user.id, book_id=payload.book_id,
        entry_type=entry_type, content=payload.content,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=schemas.JournalEntryOut)
def update_entry(
    entry_id: int,
    payload: schemas.JournalEntryUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.JournalEntry).filter(
        models.JournalEntry.id == entry_id, models.JournalEntry.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    entry.content = payload.content
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_entry(
    entry_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.JournalEntry).filter(
        models.JournalEntry.id == entry_id, models.JournalEntry.user_id == current_user.id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    db.delete(entry)
    db.commit()
    return {"message": "Entry deleted"}
