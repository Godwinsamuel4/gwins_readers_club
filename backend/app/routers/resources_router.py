import os
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, require_staff, require_mentor_or_admin, get_current_user_optional
from ..cloud_storage import upload_bytes, delete_asset, read_upload, looks_like_image, UploadValidationError

router = APIRouter(tags=["resources"])

_MAX_LOGO_BYTES = 5 * 1024 * 1024

RESOURCE_TYPES = {"chapter_summary", "study_guide", "vocabulary_list", "author_bio", "reading_guide", "discussion_guide"}
OPPORTUNITY_TYPES = {"scholarship", "internship", "competition", "essay_contest", "conference", "leadership_program", "volunteer"}


# ---------- Reading Resources ----------

@router.get("/api/resources", response_model=List[schemas.ResourceOut])
def list_resources(
    book_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.ReadingResource)
    if book_id:
        q = q.filter(models.ReadingResource.book_id == book_id)
    if resource_type:
        q = q.filter(models.ReadingResource.resource_type == resource_type)
    resources = q.order_by(models.ReadingResource.created_at.desc()).all()
    out = []
    for r in resources:
        book = db.query(models.Book).filter(models.Book.id == r.book_id).first() if r.book_id else None
        out.append(schemas.ResourceOut(
            id=r.id, book_id=r.book_id, book_title=book.title if book else None,
            resource_type=r.resource_type, title=r.title, content=r.content, created_at=r.created_at,
        ))
    return out


@router.post("/api/resources", response_model=schemas.ResourceOut, status_code=201)
def create_resource(
    payload: schemas.ResourceCreate,
    current_user: models.User = Depends(require_mentor_or_admin),
    db: Session = Depends(get_db),
):
    resource_type = payload.resource_type if payload.resource_type in RESOURCE_TYPES else "study_guide"
    resource = models.ReadingResource(
        book_id=payload.book_id, resource_type=resource_type,
        title=payload.title, content=payload.content, added_by=current_user.id,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    book = db.query(models.Book).filter(models.Book.id == resource.book_id).first() if resource.book_id else None
    return schemas.ResourceOut(
        id=resource.id, book_id=resource.book_id, book_title=book.title if book else None,
        resource_type=resource.resource_type, title=resource.title, content=resource.content,
        created_at=resource.created_at,
    )


@router.put("/api/resources/{resource_id}", response_model=schemas.ResourceOut)
def update_resource(
    resource_id: int,
    payload: schemas.ResourceUpdate,
    current_user: models.User = Depends(require_mentor_or_admin),
    db: Session = Depends(get_db),
):
    resource = db.query(models.ReadingResource).filter(models.ReadingResource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    data = payload.model_dump(exclude_unset=True)
    if "resource_type" in data and data["resource_type"] not in RESOURCE_TYPES:
        data.pop("resource_type")
    for field, value in data.items():
        setattr(resource, field, value)
    db.commit()
    db.refresh(resource)
    book = db.query(models.Book).filter(models.Book.id == resource.book_id).first() if resource.book_id else None
    return schemas.ResourceOut(
        id=resource.id, book_id=resource.book_id, book_title=book.title if book else None,
        resource_type=resource.resource_type, title=resource.title, content=resource.content,
        created_at=resource.created_at,
    )


@router.delete("/api/resources/{resource_id}")
def delete_resource(
    resource_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    r = db.query(models.ReadingResource).filter(models.ReadingResource.id == resource_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Resource not found")
    db.delete(r)
    db.commit()
    return {"message": "Resource deleted"}


# ---------- Opportunities Hub ----------

def _opportunity_out(db: Session, opp: models.Opportunity, viewer_id: Optional[int]) -> schemas.OpportunityOut:
    is_saved = False
    applied = False
    if viewer_id:
        saved = db.query(models.SavedOpportunity).filter(
            models.SavedOpportunity.opportunity_id == opp.id, models.SavedOpportunity.user_id == viewer_id
        ).first()
        if saved:
            is_saved = True
            applied = saved.applied
    return schemas.OpportunityOut(
        id=opp.id, opportunity_type=opp.opportunity_type, title=opp.title, description=opp.description,
        application_url=opp.application_url, deadline=opp.deadline, created_at=opp.created_at,
        is_saved=is_saved, applied=applied, organization=opp.organization,
        logo_url=f"/api/opportunities/{opp.id}/logo" if opp.logo_image else None,
    )


@router.get("/api/opportunities", response_model=List[schemas.OpportunityOut])
def list_opportunities(
    opportunity_type: Optional[str] = None,
    include_expired: bool = False,
    db: Session = Depends(get_db),
    current_user: Optional[models.User] = Depends(get_current_user_optional),
):
    q = db.query(models.Opportunity)
    if opportunity_type:
        q = q.filter(models.Opportunity.opportunity_type == opportunity_type)
    if not include_expired:
        q = q.filter(
            (models.Opportunity.deadline == None) | (models.Opportunity.deadline >= date.today())  # noqa: E711
        )
    opps = q.order_by(models.Opportunity.deadline.asc().nullslast()).all()
    viewer_id = current_user.id if current_user else None
    return [_opportunity_out(db, o, viewer_id) for o in opps]


@router.get("/api/opportunities/saved", response_model=List[schemas.OpportunityOut])
def list_saved_opportunities(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    saved = db.query(models.SavedOpportunity).filter(models.SavedOpportunity.user_id == current_user.id).all()
    out = []
    for s in saved:
        opp = db.query(models.Opportunity).filter(models.Opportunity.id == s.opportunity_id).first()
        if opp:
            out.append(_opportunity_out(db, opp, current_user.id))
    return out


@router.post("/api/opportunities", response_model=schemas.OpportunityOut, status_code=201)
def create_opportunity(
    payload: schemas.OpportunityCreate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    opp_type = payload.opportunity_type if payload.opportunity_type in OPPORTUNITY_TYPES else "competition"
    opp = models.Opportunity(
        opportunity_type=opp_type, title=payload.title, description=payload.description,
        application_url=payload.application_url, deadline=payload.deadline, posted_by=current_user.id,
        organization=payload.organization,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return _opportunity_out(db, opp, current_user.id)


@router.put("/api/opportunities/{opportunity_id}", response_model=schemas.OpportunityOut)
def update_opportunity(
    opportunity_id: int,
    payload: schemas.OpportunityUpdate,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    opp = db.query(models.Opportunity).filter(models.Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    data = payload.model_dump(exclude_unset=True)
    if "opportunity_type" in data and data["opportunity_type"] not in OPPORTUNITY_TYPES:
        data.pop("opportunity_type")
    for field, value in data.items():
        setattr(opp, field, value)
    db.commit()
    db.refresh(opp)
    return _opportunity_out(db, opp, current_user.id)


@router.delete("/api/opportunities/{opportunity_id}")
def delete_opportunity(
    opportunity_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    opp = db.query(models.Opportunity).filter(models.Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if opp.logo_image:
        delete_asset(opp.logo_image, resource_type="image")
    db.query(models.SavedOpportunity).filter(models.SavedOpportunity.opportunity_id == opportunity_id).delete()
    db.delete(opp)
    db.commit()
    return {"message": "Opportunity removed"}


@router.post("/api/opportunities/{opportunity_id}/logo", response_model=schemas.OpportunityOut)
def upload_opportunity_logo(
    opportunity_id: int,
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    opp = db.query(models.Opportunity).filter(models.Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    ext = os.path.splitext(file.filename or "")[1].lower()
    raw = read_upload(file, _MAX_LOGO_BYTES, (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"), field_label="Logo image")
    if ext == ".svg":
        # SVG is XML, not a binary format, so the magic-byte check doesn't
        # apply — instead reject anything that embeds a <script> tag, which
        # is the main way an "image" upload turns into stored XSS if it's
        # ever rendered somewhere other than a plain <img> tag.
        if b"<script" in raw.lower():
            raise UploadValidationError("SVG file contains a <script> tag and can't be accepted")
    elif not looks_like_image(raw):
        raise UploadValidationError("That file doesn't look like a valid image")
    old_url = opp.logo_image
    result = upload_bytes(raw, folder="opportunity_logos", original_filename=file.filename, resource_type="image")
    if old_url:
        delete_asset(old_url, resource_type="image")
    opp.logo_image = result["secure_url"]
    db.commit()
    db.refresh(opp)
    return _opportunity_out(db, opp, current_user.id)


@router.get("/api/opportunities/{opportunity_id}/logo")
def get_opportunity_logo(opportunity_id: int, db: Session = Depends(get_db)):
    opp = db.query(models.Opportunity).filter(models.Opportunity.id == opportunity_id).first()
    if not opp or not opp.logo_image:
        raise HTTPException(status_code=404, detail="No logo for this opportunity")
    return RedirectResponse(opp.logo_image)


@router.post("/api/opportunities/{opportunity_id}/save")
def save_opportunity(
    opportunity_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    opp = db.query(models.Opportunity).filter(models.Opportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    existing = db.query(models.SavedOpportunity).filter(
        models.SavedOpportunity.opportunity_id == opportunity_id, models.SavedOpportunity.user_id == current_user.id
    ).first()
    if existing:
        return {"message": "Already saved"}
    db.add(models.SavedOpportunity(opportunity_id=opportunity_id, user_id=current_user.id))
    db.commit()
    return {"message": "Saved"}


@router.delete("/api/opportunities/{opportunity_id}/save")
def unsave_opportunity(
    opportunity_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(models.SavedOpportunity).filter(
        models.SavedOpportunity.opportunity_id == opportunity_id, models.SavedOpportunity.user_id == current_user.id
    ).delete()
    db.commit()
    return {"message": "Removed from saved"}


@router.put("/api/opportunities/{opportunity_id}/applied")
def mark_applied(
    opportunity_id: int,
    applied: bool = True,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    saved = db.query(models.SavedOpportunity).filter(
        models.SavedOpportunity.opportunity_id == opportunity_id, models.SavedOpportunity.user_id == current_user.id
    ).first()
    if not saved:
        saved = models.SavedOpportunity(opportunity_id=opportunity_id, user_id=current_user.id)
        db.add(saved)
    saved.applied = applied
    db.commit()
    return {"message": "Applied" if applied else "Marked not applied", "applied": applied}
