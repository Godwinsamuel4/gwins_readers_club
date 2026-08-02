from sqlalchemy.orm import Session
from . import models


def write_audit_log(db: Session, actor_id: int, action: str, target_type: str, target_id: int = None, details: str = None):
    entry = models.AuditLog(
        actor_id=actor_id, action=action, target_type=target_type,
        target_id=target_id, details=details,
    )
    db.add(entry)
    db.commit()
