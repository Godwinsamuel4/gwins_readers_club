from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import require_staff

router = APIRouter(prefix="/api/donations", tags=["donations"])

# Static bank-transfer details shown on the Support page. The app never
# collects or processes card/payment data itself — donors send money
# directly via their own Opay/bank app, entirely outside this platform.
DONATION_DETAILS = {
    "provider": "Opay",
    "account_name": "Samuel Oluwasegun Godwin",
    "account_number": "8149008290",
}


@router.get("/details")
def get_donation_details():
    return DONATION_DETAILS


@router.post("", response_model=schemas.DonationAcknowledgmentOut, status_code=201)
def acknowledge_donation(payload: schemas.DonationAcknowledgmentCreate, db: Session = Depends(get_db)):
    """No login required — a supporter doesn't have to be a member to let the
    club know they've sent a donation. This never touches payment data; it's
    just a courtesy note for staff to say thank you and reconcile."""
    entry = models.DonationAcknowledgment(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("", response_model=List[schemas.DonationAcknowledgmentOut])
def list_donation_acknowledgments(
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.DonationAcknowledgment)
        .order_by(models.DonationAcknowledgment.created_at.desc())
        .all()
    )


@router.put("/{ack_id}/reviewed")
def mark_reviewed(
    ack_id: int,
    current_user: models.User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    entry = db.query(models.DonationAcknowledgment).filter(models.DonationAcknowledgment.id == ack_id).first()
    if not entry:
        return {"message": "Not found"}
    entry.reviewed = True
    db.commit()
    return {"message": "Marked reviewed"}
