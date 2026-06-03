"""
Email / password authentication (active)
─────────────────────────────────────────
POST /api/auth/register  → create account, return JWT
POST /api/auth/login     → verify password, return JWT
GET  /api/auth/me        → return current user (JWT required)
PUT  /api/auth/me        → update profile fields (JWT required)

Google OAuth 2.0 (commented out — restore after product is live)
─────────────────────────────────────────────────────────────────
See the commented block below. Re-enable by uncommenting and setting
GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in the environment.
"""
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from auth_utils import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter()

FRONTEND_LOGIN = "/pages/login.html"


# ── Pydantic schemas ───────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    company: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    company: Optional[str]
    phone: Optional[str]
    photo_url: Optional[str]
    license_number: Optional[str]
    territory: Optional[str]
    is_admin: bool

    class Config:
        from_attributes = True


# ── Email / password routes ────────────────────────────────────────────────
@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=req.email.lower(),
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        company=req.company,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.id})
    return {"access_token": token, "token_type": "bearer",
            "user": UserResponse.model_validate(user)}


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower()).first()
    if not user or not user.hashed_password or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account suspended")
    token = create_access_token({"sub": user.id})
    return {"access_token": token, "token_type": "bearer",
            "user": UserResponse.model_validate(user)}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserResponse)
def update_me(
    updates: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = ["full_name", "company", "phone", "photo_url", "license_number", "territory"]
    for key, val in updates.items():
        if key in allowed:
            setattr(current_user, key, val)
    db.commit()
    db.refresh(current_user)
    return current_user


# ── Google OAuth 2.0 (commented out — restore after product is live) ────────
#
# To re-enable:
#   1. pip install authlib requests  (already in requirements.txt)
#   2. Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in .env / Render dashboard
#   3. Add authorised redirect URI in Google Cloud Console:
#        http://localhost:8000/api/auth/google/callback
#        https://YOUR-APP.onrender.com/api/auth/google/callback
#   4. Uncomment the block below
#
# from authlib.integrations.requests_client import OAuth2Session
#
# GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
# GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
# _base        = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000").rstrip("/")
# CALLBACK_URL = os.getenv("CALLBACK_URL", f"{_base}/api/auth/google/callback")
# GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
# GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"
#
# @router.get("/google")
# def google_login():
#     if not GOOGLE_CLIENT_ID:
#         return RedirectResponse(f"{FRONTEND_LOGIN}?error=no_credentials")
#     client = OAuth2Session(client_id=GOOGLE_CLIENT_ID, redirect_uri=CALLBACK_URL,
#                            scope="openid email profile")
#     url, _ = client.create_authorization_url(GOOGLE_AUTH_URL, access_type="offline",
#                                               prompt="select_account")
#     return RedirectResponse(url)
#
# @router.get("/google/callback")
# def google_callback(code: str = Query(None), state: str = Query(None),
#                     error: str = Query(None), db: Session = Depends(get_db)):
#     if error or not code:
#         return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_cancelled")
#     client = OAuth2Session(client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET,
#                            redirect_uri=CALLBACK_URL)
#     try:
#         client.fetch_token(GOOGLE_TOKEN_URL, code=code)
#     except Exception:
#         return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_failed")
#     try:
#         info = client.get(GOOGLE_USERINFO).json()
#     except Exception:
#         return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_failed")
#     google_id = info.get("sub", "")
#     email     = (info.get("email") or "").strip().lower()
#     name      = (info.get("name") or "").strip()
#     picture   = info.get("picture")
#     if not google_id or not email:
#         return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_failed")
#     user = (db.query(User).filter(User.google_id == google_id).first()
#             or db.query(User).filter(User.email == email).first())
#     is_new = user is None
#     if is_new:
#         parts = name.split(" ", 1)
#         user = User(email=email, google_id=google_id,
#                     full_name=f"{parts[0]} {parts[1] if len(parts)>1 else ''}".strip(),
#                     company="", photo_url=picture, hashed_password=None)
#         db.add(user)
#     else:
#         if not user.google_id: user.google_id = google_id
#         if not user.photo_url and picture: user.photo_url = picture
#     db.commit()
#     db.refresh(user)
#     jwt_token = create_access_token({"sub": user.id})
#     user_data = {"id": user.id, "email": user.email, "full_name": user.full_name,
#                  "company": user.company, "phone": user.phone, "photo_url": user.photo_url,
#                  "license_number": user.license_number, "territory": user.territory,
#                  "is_admin": user.is_admin}
#     html = f"""<!DOCTYPE html><html><head><title>UpFront Broker</title></head><body>
# <script>
# localStorage.setItem('ufb_token', {json.dumps(jwt_token)});
# localStorage.setItem('ufb_user', JSON.stringify({json.dumps(user_data)}));
# window.location.replace('/pages/dashboard.html');
# </script></body></html>"""
#     return HTMLResponse(html, headers={"Cache-Control": "no-store"})
