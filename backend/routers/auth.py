"""
Google OAuth 2.0 authentication flow
─────────────────────────────────────
GET  /api/auth/google          → redirects browser to Google consent screen
GET  /api/auth/google/callback → receives code, issues JWT, redirects to login.html
GET  /api/auth/me              → returns current user (JWT required)
PUT  /api/auth/me              → updates profile fields (JWT required)

First-time flow
───────────────
callback detects new user or missing company → redirects to
  /pages/login.html?token=JWT&new=1&name=...&email=...
login.html shows profile-completion form (First, Last, Work Email, Company)
  → PUT /api/auth/me {full_name, company} → redirect to dashboard

Setup notes
───────────
1. Create OAuth 2.0 credentials at console.cloud.google.com
2. Add authorised redirect URI:
     http://localhost:8000/api/auth/google/callback        (local dev)
     https://YOUR-APP.onrender.com/api/auth/google/callback (Render)
3. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET — CALLBACK_URL is auto-derived
   from Render's RENDER_EXTERNAL_URL; no need to set it manually on Render.
"""
import json
import os
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from authlib.integrations.requests_client import OAuth2Session
from database import get_db
from models.user import User
from auth_utils import create_access_token, get_current_user

router = APIRouter()

# ── Google OAuth config ────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

# Auto-derive callback URL from Render's RENDER_EXTERNAL_URL when deployed;
# falls back to localhost for local dev; CALLBACK_URL env var overrides both.
_base        = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000").rstrip("/")
CALLBACK_URL = os.getenv("CALLBACK_URL", f"{_base}/api/auth/google/callback")

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"

FRONTEND_LOGIN   = "/pages/login.html"
FRONTEND_BRIDGE  = "/api/auth/complete"   # bridge endpoint — stores JWT then redirects

_ERROR_MESSAGES = {

    "auth_failed":    "Google sign-in failed. Please try again.",
    "auth_cancelled": "Sign-in was cancelled.",
    "no_credentials": "Google OAuth credentials are not configured.",
}


# ── Pydantic response ──────────────────────────────────────────────────────
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


# ── Routes ─────────────────────────────────────────────────────────────────
@router.get("/google")
def google_login():
    """Redirect the browser to Google's OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        return RedirectResponse(f"{FRONTEND_LOGIN}?error=no_credentials")

    client = OAuth2Session(
        client_id=GOOGLE_CLIENT_ID,
        redirect_uri=CALLBACK_URL,
        scope="openid email profile",
    )
    url, _ = client.create_authorization_url(
        GOOGLE_AUTH_URL,
        access_type="offline",
        prompt="select_account",
    )
    return RedirectResponse(url)


@router.get("/google/callback")
def google_callback(
    code:  str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    db:    Session = Depends(get_db),
):
    """Receive the OAuth code, verify it, upsert the user, issue a JWT."""
    if error or not code:
        return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_cancelled")

    # Exchange code for tokens
    client = OAuth2Session(
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        redirect_uri=CALLBACK_URL,
    )
    try:
        client.fetch_token(GOOGLE_TOKEN_URL, code=code)
    except Exception:
        return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_failed")

    # Fetch user profile from Google
    try:
        info = client.get(GOOGLE_USERINFO).json()
    except Exception:
        return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_failed")

    google_id = info.get("sub", "")
    email     = (info.get("email") or "").strip().lower()
    name      = (info.get("name") or "").strip()
    picture   = info.get("picture")

    if not google_id or not email:
        return RedirectResponse(f"{FRONTEND_LOGIN}?error=auth_failed")

    # Find or create the user (try google_id first, fall back to email)
    user = (
        db.query(User).filter(User.google_id == google_id).first()
        or db.query(User).filter(User.email == email).first()
    )
    is_new = user is None

    if is_new:
        # Parse Google display name into first/last; store full_name.
        # Company left empty — broker can fill it from settings later.
        parts = name.split(" ", 1)
        first = parts[0]
        last  = parts[1] if len(parts) > 1 else ""
        user = User(
            email=email,
            google_id=google_id,
            full_name=f"{first} {last}".strip(),
            company="",
            photo_url=picture,
            hashed_password=None,
        )
        db.add(user)
    else:
        if not user.google_id:
            user.google_id = google_id
        if not user.photo_url and picture:
            user.photo_url = picture
    db.commit()
    db.refresh(user)

    jwt_token     = create_access_token({"sub": user.id})
    needs_profile = is_new or not user.company

    # Redirect to the bridge endpoint — it stores the JWT in localStorage,
    # then sends the browser to the dashboard or profile-completion form.
    params: dict = {"token": jwt_token}
    if needs_profile:
        params["new"]   = "1"
        params["name"]  = name
        params["email"] = email

    return RedirectResponse(
        f"{FRONTEND_BRIDGE}?{urllib.parse.urlencode(params)}",
        status_code=302,
    )


@router.get("/complete")
def auth_complete(
    token: str = Query(""),
    new:   str = Query(""),
    name:  str = Query(""),
    email: str = Query(""),
    error: str = Query(""),
):
    """
    OAuth bridge — stores the JWT in localStorage then redirects the browser.

    Serving this as a proper FastAPI route (not StaticFiles) guarantees
    query parameters are never stripped by a static-file redirect.
    Uses json.dumps() to safely embed values into the inline script.
    """
    if error or not token:
        dest = f"{FRONTEND_LOGIN}?error={urllib.parse.quote(error or 'auth_failed')}"
    else:
        # Both new and returning users go straight to dashboard.
        # Profile completion (company, etc.) is handled via a settings page.
        dest = "/pages/dashboard.html"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Signing in…</title></head>
<body>
<script>
var _token = {json.dumps(token)};
var _dest  = {json.dumps(dest)};
try {{
  window.localStorage.setItem('ufb_token', _token);
  console.log('[UpFront] bridge: token stored, length=' + _token.length);
}} catch (e) {{
  console.error('[UpFront] bridge: localStorage write failed:', e);
}}
setTimeout(function () {{ window.location.replace(_dest); }}, 100);
</script>
</body></html>"""
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })


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
