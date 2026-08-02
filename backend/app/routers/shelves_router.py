from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user
from .library_router import _book_out

router = APIRouter(prefix="/api/shelves", tags=["shelves"])


@router.get("", response_model=List[schemas.ReadingListOut])
def list_shelves(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lists = db.query(models.ReadingList).filter(models.ReadingList.user_id == current_user.id).all()
    out = []
    for l in lists:
        count = db.query(models.ReadingListItem).filter(models.ReadingListItem.list_id == l.id).count()
        out.append(schemas.ReadingListOut(
            id=l.id, name=l.name, description=l.description, book_count=count, created_at=l.created_at,
        ))
    return out


@router.post("", response_model=schemas.ReadingListOut, status_code=201)
def create_shelf(
    payload: schemas.ReadingListCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shelf = models.ReadingList(user_id=current_user.id, **payload.model_dump())
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return schemas.ReadingListOut(
        id=shelf.id, name=shelf.name, description=shelf.description, book_count=0, created_at=shelf.created_at,
    )


@router.put("/{shelf_id}", response_model=schemas.ReadingListOut)
def rename_shelf(
    shelf_id: int,
    payload: schemas.ReadingListUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shelf = db.query(models.ReadingList).filter(
        models.ReadingList.id == shelf_id, models.ReadingList.user_id == current_user.id
    ).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shelf, field, value)
    db.commit()
    db.refresh(shelf)
    count = db.query(models.ReadingListItem).filter(models.ReadingListItem.list_id == shelf.id).count()
    return schemas.ReadingListOut(
        id=shelf.id, name=shelf.name, description=shelf.description, book_count=count, created_at=shelf.created_at,
    )


@router.delete("/{shelf_id}")
def delete_shelf(
    shelf_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shelf = db.query(models.ReadingList).filter(
        models.ReadingList.id == shelf_id, models.ReadingList.user_id == current_user.id
    ).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")
    db.query(models.ReadingListItem).filter(models.ReadingListItem.list_id == shelf_id).delete()
    db.delete(shelf)
    db.commit()
    return {"message": "Shelf deleted"}


@router.get("/{shelf_id}/books")
def get_shelf_books(
    shelf_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shelf = db.query(models.ReadingList).filter(
        models.ReadingList.id == shelf_id, models.ReadingList.user_id == current_user.id
    ).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")
    items = db.query(models.ReadingListItem).filter(
        models.ReadingListItem.list_id == shelf_id
    ).order_by(models.ReadingListItem.position.asc()).all()
    books = []
    for item in items:
        book = db.query(models.Book).filter(models.Book.id == item.book_id).first()
        if book:
            books.append(_book_out(db, book))
    return books


@router.put("/{shelf_id}/reorder")
def reorder_shelf(
    shelf_id: int,
    payload: schemas.ShelfReorderRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shelf = db.query(models.ReadingList).filter(
        models.ReadingList.id == shelf_id, models.ReadingList.user_id == current_user.id
    ).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")
    items = {
        item.book_id: item for item in db.query(models.ReadingListItem).filter(
            models.ReadingListItem.list_id == shelf_id
        ).all()
    }
    for position, book_id in enumerate(payload.book_ids_in_order):
        if book_id in items:
            items[book_id].position = position
    db.commit()
    return {"message": "Shelf reordered"}


@router.post("/{shelf_id}/books/{book_id}")
def add_book_to_shelf(
    shelf_id: int,
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shelf = db.query(models.ReadingList).filter(
        models.ReadingList.id == shelf_id, models.ReadingList.user_id == current_user.id
    ).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")
    existing = db.query(models.ReadingListItem).filter(
        models.ReadingListItem.list_id == shelf_id, models.ReadingListItem.book_id == book_id
    ).first()
    if existing:
        return {"message": "Already on this shelf"}
    max_position = db.query(models.ReadingListItem).filter(
        models.ReadingListItem.list_id == shelf_id
    ).count()
    db.add(models.ReadingListItem(list_id=shelf_id, book_id=book_id, position=max_position))
    db.commit()
    return {"message": "Added to shelf"}


@router.delete("/{shelf_id}/books/{book_id}")
def remove_book_from_shelf(
    shelf_id: int,
    book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shelf = db.query(models.ReadingList).filter(
        models.ReadingList.id == shelf_id, models.ReadingList.user_id == current_user.id
    ).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="Shelf not found")
    db.query(models.ReadingListItem).filter(
        models.ReadingListItem.list_id == shelf_id, models.ReadingListItem.book_id == book_id
    ).delete()
    db.commit()
    return {"message": "Removed from shelf"}
