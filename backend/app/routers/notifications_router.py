from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=List[schemas.NotificationOut])
def list_notifications(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    ).order_by(models.Notification.created_at.desc()).limit(100).all()


@router.get("/unread-count")
def unread_count(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False,  # noqa: E712
    ).count()
    return {"unread": count}


@router.put("/{notification_id}/read")
def mark_read(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.query(models.Notification).filter(
        models.Notification.id == notification_id, models.Notification.user_id == current_user.id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"message": "Marked as read"}


@router.put("/mark-all-read")
def mark_all_read(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id, models.Notification.is_read == False  # noqa: E712
    ).update({models.Notification.is_read: True})
    db.commit()
    return {"message": "All notifications marked as read"}


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.query(models.Notification).filter(
        models.Notification.id == notification_id, models.Notification.user_id == current_user.id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(n)
    db.commit()
    return {"message": "Notification deleted"}


@router.get("/preferences", response_model=List[schemas.NotificationPreferenceOut])
def get_preferences(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prefs = db.query(models.NotificationPreference).filter(
        models.NotificationPreference.user_id == current_user.id
    ).all()
    return [schemas.NotificationPreferenceOut(category=p.category, muted=p.muted) for p in prefs]


@router.put("/preferences", response_model=schemas.NotificationPreferenceOut)
def set_preference(
    payload: schemas.NotificationPreferenceUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pref = db.query(models.NotificationPreference).filter(
        models.NotificationPreference.user_id == current_user.id,
        models.NotificationPreference.category == payload.category,
    ).first()
    if not pref:
        pref = models.NotificationPreference(user_id=current_user.id, category=payload.category)
        db.add(pref)
    pref.muted = payload.muted
    db.commit()
    return schemas.NotificationPreferenceOut(category=pref.category, muted=pref.muted)


@router.post("/broadcast", status_code=201)
def broadcast_notification(
    payload: schemas.NotificationCreate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    if payload.user_ids:
        target_ids = payload.user_ids
    else:
        target_ids = [u.id for u in db.query(models.User.id).all()]

    muted_user_ids = {
        p.user_id for p in db.query(models.NotificationPreference).filter(
            models.NotificationPreference.category == payload.notif_type,
            models.NotificationPreference.muted == True,  # noqa: E712
        ).all()
    }
    target_ids = [uid for uid in target_ids if uid not in muted_user_ids]

    notifications = [
        models.Notification(user_id=uid, notif_type=payload.notif_type, message=payload.message)
        for uid in target_ids
    ]
    db.bulk_save_objects(notifications)
    db.commit()
    return {"message": f"Notification sent to {len(target_ids)} members"}
