from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from database import get_db
from models.user import User
from auth_utils import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter()

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    company: str = None
    phone: str = None

class LoginRequest(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    company: str = None
    phone: str = None
    photo_url: str = None
    license_number: str = None
    territory: str = None
    is_admin: bool

    class Config:
        from_attributes = True

@router.post("/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=req.email.lower(),
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        company=req.company,
        phone=req.phone
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.id})
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.from_orm(user)}

@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower()).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account suspended")

    token = create_access_token({"sub": user.id})
    return {"access_token": token, "token_type": "bearer", "user": UserResponse.from_orm(user)}

@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user

@router.put("/me", response_model=UserResponse)
def update_me(updates: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    allowed = ["full_name", "company", "phone", "photo_url", "license_number", "territory"]
    for key, val in updates.items():
        if key in allowed:
            setattr(current_user, key, val)
    db.commit()
    db.refresh(current_user)
    return current_user
