"""
Training Groups — standalone cohorts for pulling specific students together
for focused training (public speaking, debate, exam prep, etc.), independent
of Reading Club membership. Unlike reading clubs (which members join
themselves), training groups are curated: a trainer/staff member explicitly
adds the students they want in the group.
"""
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff
from ..cloud_storage import upload_bytes, delete_asset, read_upload

router = APIRouter(prefix="/api/training-groups", tags=["training-groups"])

MAX_RESOURCE_BYTES = 20 * 1024 * 1024  # 20MB
# Session materials are typically documents/slides/handouts — not arbitrary
# executables. This used to be unvalidated (any extension, any content
# accepted); scoping it to the formats trainers actually share closes that
# gap without being so narrow it blocks a legitimate handout.
ALLOWED_RESOURCE_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".txt", ".csv", ".jpg", ".jpeg", ".png", ".zip",
)

TRAINER_ROLES = ("admin", "moderator", "mentor")


def _is_trainer_or_staff(db: Session, group_id: int, user: models.User) -> bool:
    if user.role in ("admin", "moderator"):
        return True
    membership = db.query(models.TrainingGroupMember).filter(
        models.TrainingGroupMember.group_id == group_id,
        models.TrainingGroupMember.user_id == user.id,
    ).first()
    return bool(membership and membership.is_trainer)


def _require_can_create(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role not in TRAINER_ROLES:
        raise HTTPException(status_code=403, detail="Only staff or mentors can create a training group")
    return user


def _group_out(db: Session, group: models.TrainingGroup, user_id: int) -> schemas.TrainingGroupOut:
    member_count = db.query(models.TrainingGroupMember).filter(
        models.TrainingGroupMember.group_id == group.id
    ).count()
    session_count = db.query(models.TrainingSession).filter(
        models.TrainingSession.group_id == group.id, models.TrainingSession.is_cancelled == False  # noqa: E712
    ).count()
    membership = db.query(models.TrainingGroupMember).filter(
        models.TrainingGroupMember.group_id == group.id,
        models.TrainingGroupMember.user_id == user_id,
    ).first()
    return schemas.TrainingGroupOut(
        id=group.id, name=group.name, focus_area=group.focus_area, description=group.description,
        is_active=group.is_active, member_count=member_count, session_count=session_count,
        is_member=membership is not None, is_trainer=bool(membership and membership.is_trainer),
        created_at=group.created_at,
    )


def _session_out(db: Session, session: models.TrainingSession, user_id: Optional[int]) -> schemas.TrainingSessionOut:
    resource_count = db.query(models.TrainingSessionResource).filter(
        models.TrainingSessionResource.session_id == session.id
    ).count()
    breakout_count = db.query(models.TrainingBreakoutGroup).filter(
        models.TrainingBreakoutGroup.session_id == session.id
    ).count()
    present_count = db.query(models.TrainingSessionAttendance).filter(
        models.TrainingSessionAttendance.session_id == session.id,
        models.TrainingSessionAttendance.status == "present",
    ).count()
    my_attendance = None
    if user_id:
        att = db.query(models.TrainingSessionAttendance).filter(
            models.TrainingSessionAttendance.session_id == session.id,
            models.TrainingSessionAttendance.user_id == user_id,
        ).first()
        my_attendance = att.status if att else None
    return schemas.TrainingSessionOut(
        id=session.id, group_id=session.group_id, title=session.title, description=session.description,
        session_date=session.session_date, duration_minutes=session.duration_minutes, location=session.location,
        is_cancelled=session.is_cancelled, resource_count=resource_count, breakout_count=breakout_count,
        present_count=present_count, my_attendance=my_attendance, created_at=session.created_at,
    )


def _resource_out(r: models.TrainingSessionResource) -> schemas.TrainingSessionResourceOut:
    return schemas.TrainingSessionResourceOut(
        id=r.id, session_id=r.session_id, title=r.title,
        file_url=f"/api/training-groups/resources/{r.id}/file" if r.file_path else None,
        file_original_name=r.file_original_name, url=r.url, created_at=r.created_at,
    )


# ---------- Groups ----------

@router.get("", response_model=List[schemas.TrainingGroupOut])
def list_groups(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admins/moderators see every group (to manage them); everyone else
    only sees the training groups they've actually been added to."""
    groups = db.query(models.TrainingGroup).filter(
        models.TrainingGroup.is_active == True  # noqa: E712
    ).order_by(models.TrainingGroup.created_at.desc()).all()
    out = [_group_out(db, g, current_user.id) for g in groups]
    if current_user.role not in ("admin", "moderator"):
        out = [g for g in out if g.is_member]
    return out


@router.post("", response_model=schemas.TrainingGroupOut, status_code=201)
def create_group(
    payload: schemas.TrainingGroupCreate,
    current_user: models.User = Depends(_require_can_create),
    db: Session = Depends(get_db),
):
    group = models.TrainingGroup(**payload.model_dump(), created_by=current_user.id)
    db.add(group)
    db.commit()
    db.refresh(group)
    db.add(models.TrainingGroupMember(group_id=group.id, user_id=current_user.id, is_trainer=True))
    db.commit()
    return _group_out(db, group, current_user.id)


@router.get("/search-users")
def search_users(
    q: str = "",
    current_user: models.User = Depends(_require_can_create),
    db: Session = Depends(get_db),
):
    """Lightweight user lookup for trainers building a group roster."""
    query = db.query(models.User).filter(models.User.is_active == True)  # noqa: E712
    if q:
        like = f"%{q}%"
        query = query.filter((models.User.full_name.ilike(like)) | (models.User.email.ilike(like)))
    users = query.order_by(models.User.full_name.asc()).limit(20).all()
    return [{"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role} for u in users]


@router.get("/{group_id}", response_model=schemas.TrainingGroupOut)
def get_group(group_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = db.query(models.TrainingGroup).filter(models.TrainingGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Training group not found")
    return _group_out(db, group, current_user.id)


@router.put("/{group_id}", response_model=schemas.TrainingGroupOut)
def update_group(
    group_id: int, payload: schemas.TrainingGroupUpdate,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    group = db.query(models.TrainingGroup).filter(models.TrainingGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Training group not found")
    if not _is_trainer_or_staff(db, group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can edit it")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    db.commit()
    db.refresh(group)
    return _group_out(db, group, current_user.id)


@router.delete("/{group_id}")
def delete_group(group_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = db.query(models.TrainingGroup).filter(models.TrainingGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Training group not found")
    if not _is_trainer_or_staff(db, group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can delete it")
    session_ids = [s.id for s in db.query(models.TrainingSession.id).filter(models.TrainingSession.group_id == group_id).all()]
    if session_ids:
        breakout_ids = [b.id for b in db.query(models.TrainingBreakoutGroup.id).filter(models.TrainingBreakoutGroup.session_id.in_(session_ids)).all()]
        if breakout_ids:
            db.query(models.TrainingBreakoutMember).filter(models.TrainingBreakoutMember.breakout_group_id.in_(breakout_ids)).delete(synchronize_session=False)
        db.query(models.TrainingBreakoutGroup).filter(models.TrainingBreakoutGroup.session_id.in_(session_ids)).delete(synchronize_session=False)
        resources = db.query(models.TrainingSessionResource).filter(models.TrainingSessionResource.session_id.in_(session_ids)).all()
        for r in resources:
            if r.file_path:
                delete_asset(r.file_path, resource_type="raw")
        db.query(models.TrainingSessionResource).filter(models.TrainingSessionResource.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(models.TrainingSessionAttendance).filter(models.TrainingSessionAttendance.session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(models.TrainingSession).filter(models.TrainingSession.group_id == group_id).delete()
    db.query(models.TrainingGroupMember).filter(models.TrainingGroupMember.group_id == group_id).delete()
    db.delete(group)
    db.commit()
    return {"message": "Training group deleted"}


# ---------- Members ----------

@router.get("/{group_id}/members", response_model=List[schemas.TrainingGroupMemberOut])
def list_members(group_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    memberships = db.query(models.TrainingGroupMember).filter(models.TrainingGroupMember.group_id == group_id).all()
    out = []
    for m in memberships:
        user = db.query(models.User).filter(models.User.id == m.user_id).first()
        out.append(schemas.TrainingGroupMemberOut(user_id=m.user_id, name=user.full_name if user else "Unknown", is_trainer=m.is_trainer))
    return out


@router.post("/{group_id}/members/{user_id}")
def add_member(
    group_id: int, user_id: int, is_trainer: bool = False,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    if not _is_trainer_or_staff(db, group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can add members")
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.query(models.TrainingGroupMember).filter(
        models.TrainingGroupMember.group_id == group_id, models.TrainingGroupMember.user_id == user_id
    ).first()
    if existing:
        return {"message": "Already in this group"}
    db.add(models.TrainingGroupMember(group_id=group_id, user_id=user_id, is_trainer=is_trainer))
    db.commit()
    return {"message": f"Added {target.full_name} to the group"}


@router.delete("/{group_id}/members/{user_id}")
def remove_member(
    group_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    if not _is_trainer_or_staff(db, group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can remove members")
    membership = db.query(models.TrainingGroupMember).filter(
        models.TrainingGroupMember.group_id == group_id, models.TrainingGroupMember.user_id == user_id
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found in this group")
    db.delete(membership)
    db.commit()
    return {"message": "Member removed"}


# ---------- Sessions ----------

@router.get("/{group_id}/sessions", response_model=List[schemas.TrainingSessionOut])
def list_sessions(
    group_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    sessions = db.query(models.TrainingSession).filter(
        models.TrainingSession.group_id == group_id
    ).order_by(models.TrainingSession.session_date.asc()).all()
    return [_session_out(db, s, current_user.id) for s in sessions]


@router.post("/{group_id}/sessions", response_model=schemas.TrainingSessionOut, status_code=201)
def create_session(
    group_id: int, payload: schemas.TrainingSessionCreate,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    if not _is_trainer_or_staff(db, group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can add sessions")
    group = db.query(models.TrainingGroup).filter(models.TrainingGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Training group not found")
    session = models.TrainingSession(group_id=group_id, created_by=current_user.id, **payload.model_dump())
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_out(db, session, current_user.id)


@router.put("/sessions/{session_id}", response_model=schemas.TrainingSessionOut)
def update_session(
    session_id: int, payload: schemas.TrainingSessionUpdate,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can edit sessions")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(session, field, value)
    db.commit()
    db.refresh(session)
    return _session_out(db, session, current_user.id)


@router.delete("/sessions/{session_id}")
def cancel_session(session_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can cancel sessions")
    session.is_cancelled = True
    db.commit()
    return {"message": "Session cancelled"}


# ---------- Attendance ----------

@router.get("/sessions/{session_id}/attendance")
def list_attendance(session_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    records = db.query(models.TrainingSessionAttendance).filter(
        models.TrainingSessionAttendance.session_id == session_id
    ).all()
    out = []
    for a in records:
        user = db.query(models.User).filter(models.User.id == a.user_id).first()
        out.append({"user_id": a.user_id, "name": user.full_name if user else "Unknown", "status": a.status})
    return out


@router.post("/sessions/{session_id}/attendance")
def mark_attendance(
    session_id: int, payload: schemas.TrainingAttendanceMark,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can mark attendance")
    record = db.query(models.TrainingSessionAttendance).filter(
        models.TrainingSessionAttendance.session_id == session_id,
        models.TrainingSessionAttendance.user_id == payload.user_id,
    ).first()
    if not record:
        record = models.TrainingSessionAttendance(session_id=session_id, user_id=payload.user_id)
        db.add(record)
    record.status = payload.status
    record.marked_by = current_user.id
    db.commit()
    return {"message": "Attendance recorded"}


# ---------- Resources / materials ----------

@router.get("/sessions/{session_id}/resources", response_model=List[schemas.TrainingSessionResourceOut])
def list_resources(session_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    resources = db.query(models.TrainingSessionResource).filter(
        models.TrainingSessionResource.session_id == session_id
    ).order_by(models.TrainingSessionResource.created_at.desc()).all()
    return [_resource_out(r) for r in resources]


@router.post("/sessions/{session_id}/resources", response_model=schemas.TrainingSessionResourceOut, status_code=201)
def add_resource(
    session_id: int,
    title: str = Form(...),
    url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can add materials")
    if not file and not url:
        raise HTTPException(status_code=400, detail="Provide a file upload or a link")

    resource = models.TrainingSessionResource(session_id=session_id, title=title, url=url or None, added_by=current_user.id)
    if file and file.filename:
        raw = read_upload(file, MAX_RESOURCE_BYTES, ALLOWED_RESOURCE_EXTENSIONS, field_label="Session file")
        result = upload_bytes(raw, folder="session_resources", original_filename=file.filename, resource_type="raw")
        resource.file_path = result["secure_url"]
        resource.file_original_name = file.filename

    db.add(resource)
    db.commit()
    db.refresh(resource)
    return _resource_out(resource)


@router.get("/resources/{resource_id}/file")
def download_resource(resource_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    resource = db.query(models.TrainingSessionResource).filter(models.TrainingSessionResource.id == resource_id).first()
    if not resource or not resource.file_path:
        raise HTTPException(status_code=404, detail="File not found")
    return RedirectResponse(resource.file_path)


@router.delete("/resources/{resource_id}")
def delete_resource(resource_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    resource = db.query(models.TrainingSessionResource).filter(models.TrainingSessionResource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == resource.session_id).first()
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can remove materials")
    if resource.file_path:
        delete_asset(resource.file_path, resource_type="raw")
    db.delete(resource)
    db.commit()
    return {"message": "Material removed"}


# ---------- Breakout groups ----------

@router.get("/sessions/{session_id}/breakouts", response_model=List[schemas.TrainingBreakoutGroupOut])
def list_breakouts(session_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    groups = db.query(models.TrainingBreakoutGroup).filter(
        models.TrainingBreakoutGroup.session_id == session_id
    ).all()
    out = []
    for g in groups:
        members = db.query(models.TrainingBreakoutMember).filter(
            models.TrainingBreakoutMember.breakout_group_id == g.id
        ).all()
        member_out = []
        for m in members:
            user = db.query(models.User).filter(models.User.id == m.user_id).first()
            member_out.append(schemas.TrainingGroupMemberOut(user_id=m.user_id, name=user.full_name if user else "Unknown"))
        out.append(schemas.TrainingBreakoutGroupOut(id=g.id, session_id=g.session_id, name=g.name, notes=g.notes, members=member_out))
    return out


@router.post("/sessions/{session_id}/breakouts", response_model=schemas.TrainingBreakoutGroupOut, status_code=201)
def create_breakout(
    session_id: int, payload: schemas.TrainingBreakoutGroupCreate,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can create breakout groups")
    breakout = models.TrainingBreakoutGroup(session_id=session_id, name=payload.name, notes=payload.notes)
    db.add(breakout)
    db.commit()
    db.refresh(breakout)
    member_out = []
    for uid in payload.member_ids:
        db.add(models.TrainingBreakoutMember(breakout_group_id=breakout.id, user_id=uid))
        user = db.query(models.User).filter(models.User.id == uid).first()
        if user:
            member_out.append(schemas.TrainingGroupMemberOut(user_id=uid, name=user.full_name))
    db.commit()
    return schemas.TrainingBreakoutGroupOut(id=breakout.id, session_id=breakout.session_id, name=breakout.name, notes=breakout.notes, members=member_out)


@router.delete("/breakouts/{breakout_id}")
def delete_breakout(breakout_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    breakout = db.query(models.TrainingBreakoutGroup).filter(models.TrainingBreakoutGroup.id == breakout_id).first()
    if not breakout:
        raise HTTPException(status_code=404, detail="Breakout group not found")
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == breakout.session_id).first()
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can delete breakout groups")
    db.query(models.TrainingBreakoutMember).filter(models.TrainingBreakoutMember.breakout_group_id == breakout_id).delete()
    db.delete(breakout)
    db.commit()
    return {"message": "Breakout group deleted"}


@router.post("/breakouts/{breakout_id}/members/{user_id}")
def add_breakout_member(
    breakout_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    breakout = db.query(models.TrainingBreakoutGroup).filter(models.TrainingBreakoutGroup.id == breakout_id).first()
    if not breakout:
        raise HTTPException(status_code=404, detail="Breakout group not found")
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == breakout.session_id).first()
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can manage breakout groups")
    existing = db.query(models.TrainingBreakoutMember).filter(
        models.TrainingBreakoutMember.breakout_group_id == breakout_id,
        models.TrainingBreakoutMember.user_id == user_id,
    ).first()
    if not existing:
        db.add(models.TrainingBreakoutMember(breakout_group_id=breakout_id, user_id=user_id))
        db.commit()
    return {"message": "Added to breakout group"}


@router.delete("/breakouts/{breakout_id}/members/{user_id}")
def remove_breakout_member(
    breakout_id: int, user_id: int,
    current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    breakout = db.query(models.TrainingBreakoutGroup).filter(models.TrainingBreakoutGroup.id == breakout_id).first()
    if not breakout:
        raise HTTPException(status_code=404, detail="Breakout group not found")
    session = db.query(models.TrainingSession).filter(models.TrainingSession.id == breakout.session_id).first()
    if not _is_trainer_or_staff(db, session.group_id, current_user):
        raise HTTPException(status_code=403, detail="Only a trainer for this group or staff can manage breakout groups")
    db.query(models.TrainingBreakoutMember).filter(
        models.TrainingBreakoutMember.breakout_group_id == breakout_id,
        models.TrainingBreakoutMember.user_id == user_id,
    ).delete()
    db.commit()
    return {"message": "Removed from breakout group"}
