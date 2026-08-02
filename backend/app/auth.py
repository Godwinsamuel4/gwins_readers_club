import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from . import models

# In production, set the RC_SECRET_KEY environment variable to a long,
# random value (e.g. `openssl rand -hex 32`) and never commit it. The
# fallback below is only for local/dev use.
SECRET_KEY = os.environ.get("RC_SECRET_KEY", "gwins-readers-club-dev-secret-change-in-production")
if SECRET_KEY == "gwins-readers-club-dev-secret-change-in-production" and os.environ.get("RC_ENV") == "production":
    raise RuntimeError("RC_SECRET_KEY must be set to a real secret in production")
ALGORITHM = "HS256"
# Shorter-lived than a typical app by design: this platform's primary users
# are minors on shared/school devices, so a token that outlives a single
# school day cuts down the window a lost or shared device stays signed in.
# Override via RC_ACCESS_TOKEN_EXPIRE_MINUTES if a longer session is needed.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("RC_ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 12))  # 12 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except PyJWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")
    return user


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """Like get_current_user, but returns None instead of raising when no/invalid token is given.
    Used on public read endpoints that personalize output (e.g. 'did I vote this helpful') when logged in."""
    if token is None:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            return None
    except PyJWTError:
        return None
    return db.query(models.User).filter(models.User.id == int(user_id)).first()


def require_roles(*roles):
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user
    return checker


require_admin = require_roles("admin")
require_staff = require_roles("admin", "moderator")
require_mentor_or_admin = require_roles("admin", "mentor")
