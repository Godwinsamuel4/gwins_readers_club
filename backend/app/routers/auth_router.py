import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import (
    hash_password, verify_password, create_access_token, get_current_user
)
from ..avatars import attach_staff_avatar, avatar_url, PRESET_AVATARS

router = APIRouter(prefix="/api/auth", tags=["auth"])

MINOR_AGE_BRACKETS = ("Under 13", "13-15", "16-17")
STAFF_ROLES = ("admin", "moderator", "mentor")


@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserRegister, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    if payload.age_bracket not in ("Under 13", "13-15", "16-17", "18+"):
        raise HTTPException(status_code=400, detail="Please select a valid age range")

    if not payload.accepted_terms:
        raise HTTPException(status_code=400, detail="You must accept the Privacy & Child Safety Policy to join")

    is_minor = payload.age_bracket in MINOR_AGE_BRACKETS
    if is_minor:
        if not (payload.guardian_name and payload.guardian_email and payload.guardian_consent):
            raise HTTPException(
                status_code=400,
                detail="A parent or guardian's name, email, and consent are required for members under 18",
            )

    user = models.User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        phone_number=payload.phone_number,
        school=payload.school,
        department=payload.department,
        state=payload.state,
        country=payload.country or "Nigeria",
        reading_interests=payload.reading_interests,
        role="member",
        age_bracket=payload.age_bracket,
        guardian_name=payload.guardian_name if is_minor else None,
        guardian_email=payload.guardian_email if is_minor else None,
        guardian_consent=bool(is_minor and payload.guardian_consent),
        guardian_consent_at=datetime.utcnow() if (is_minor and payload.guardian_consent) else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    streak = models.ReadingStreak(user_id=user.id, current_streak=0, longest_streak=0)
    db.add(streak)
    db.commit()

    token = create_access_token({"sub": str(user.id)})
    return schemas.Token(access_token=token, user=user)


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="This account is deactivated. Use 'Reactivate account' with your email and password to log back in.",
        )

    token = create_access_token({"sub": str(user.id)})
    return schemas.Token(access_token=token, user=user)


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=schemas.UserOut)
def update_me(
    payload: schemas.UserUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/avatar", response_model=schemas.UserOut)
def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Staff-only (admin/moderator/mentor): upload a real profile photo.
    Members pick a preset avatar instead — see PUT /me/avatar-preset — so no
    child on the platform is prompted to upload a photo of themselves."""
    if current_user.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Members choose one of the preset avatars instead of uploading a photo. Use the avatar picker on your profile.",
        )
    attach_staff_avatar(db, current_user, file)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/me/avatar-preset", response_model=schemas.UserOut)
def choose_preset_avatar(
    payload: schemas.AvatarPresetChoice,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.preset not in PRESET_AVATARS:
        raise HTTPException(status_code=400, detail="Not a valid preset avatar")
    current_user.profile_picture = payload.preset
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/avatar/{user_id}")
def get_user_avatar(user_id: int, db: Session = Depends(get_db)):
    """Serves a staff member's uploaded photo. Returns 404 for members (who use
    a client-rendered preset avatar, not a stored image) or staff with none set."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    url = avatar_url(user.profile_picture)
    if not url:
        raise HTTPException(status_code=404, detail="No uploaded photo for this user")
    return RedirectResponse(url)


@router.post("/change-password")
def change_password(
    payload: schemas.PasswordChange,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password updated successfully"}


@router.post("/deactivate")
def deactivate_account(
    payload: schemas.DeactivateAccountRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service deactivation: hides the account and blocks login until reactivated.
    Distinct from an admin removing a member outright."""
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")
    current_user.is_active = False
    db.commit()
    return {"message": "Your account has been deactivated. You can reactivate it any time by logging in again."}


@router.post("/reactivate", response_model=schemas.Token)
def reactivate_account(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user.is_active = True
    db.commit()
    token = create_access_token({"sub": str(user.id)})
    return schemas.Token(access_token=token, user=user)


# ---------- Password Reset ----------
# Dev-mode: no SMTP is configured, so the reset token is returned in the
# response and logged server-side rather than emailed. In production this
# response would drop the token field and only send it via email.

@router.post("/password-reset")
def request_password_reset(payload: schemas.PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    # Always return 200 regardless of whether the email exists, to avoid
    # leaking which emails are registered (anti-enumeration).
    if not user:
        return {"message": "If that email is registered, a reset link has been sent."}

    token = secrets.token_urlsafe(32)
    db.add(models.AuthToken(
        user_id=user.id, token=token, token_type="password_reset",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    ))
    db.commit()
    print(f"[DEV MODE] Password reset token for {user.email}: {token}")
    return {"message": "If that email is registered, a reset link has been sent.", "dev_token": token}


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: schemas.PasswordResetConfirm, db: Session = Depends(get_db)):
    token_row = db.query(models.AuthToken).filter(
        models.AuthToken.token == payload.token, models.AuthToken.token_type == "password_reset",
        models.AuthToken.used == False,  # noqa: E712
    ).first()
    if not token_row or token_row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")

    user = db.query(models.User).filter(models.User.id == token_row.user_id).first()
    user.password_hash = hash_password(payload.new_password)
    token_row.used = True
    db.commit()
    return {"message": "Password reset successfully — you can now log in"}


# ---------- Email Verification ----------

@router.post("/send-verification")
def send_verification(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.email_verified:
        return {"message": "Your email is already verified"}
    token = secrets.token_urlsafe(32)
    db.add(models.AuthToken(
        user_id=current_user.id, token=token, token_type="email_verification",
        expires_at=datetime.utcnow() + timedelta(hours=24),
    ))
    db.commit()
    print(f"[DEV MODE] Email verification token for {current_user.email}: {token}")
    return {"message": "Verification link sent", "dev_token": token}


@router.post("/verify-email")
def verify_email(payload: schemas.EmailVerificationConfirm, db: Session = Depends(get_db)):
    token_row = db.query(models.AuthToken).filter(
        models.AuthToken.token == payload.token, models.AuthToken.token_type == "email_verification",
        models.AuthToken.used == False,  # noqa: E712
    ).first()
    if not token_row or token_row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired")
    user = db.query(models.User).filter(models.User.id == token_row.user_id).first()
    user.email_verified = True
    token_row.used = True
    db.commit()
    return {"message": "Email verified successfully"}
