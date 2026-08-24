from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from ...core.config import settings
from ...core.database import get_db
from ...models import models, schemas
from ..dependencies import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash
)

router = APIRouter()

@router.post("/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    if db.query(models.User).filter(models.User.username == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email,
                           username=user.username,
                           full_name=user.full_name,
                          hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.post("/token", response_model=schemas.Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_data = {"sub": user.username}
    access_token = create_access_token(token_data)
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=schemas.User)
async def read_users_me(current_user: schemas.User = Depends(get_current_user)):
    return current_user

@router.post("/profile", response_model=schemas.UserProfile)
def create_user_profile(
    profile: schemas.UserProfileCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == current_user.id).first()
    if db_profile:
        for key, value in profile.model_dump().items():
            setattr(db_profile, key, value)
    else:
        db_profile = models.UserProfile(**profile.model_dump(), user_id=current_user.id)
        db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.post("/goals", response_model=schemas.UserGoals)
def create_user_goals(
    goals: schemas.UserGoalsCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_goals = db.query(models.UserGoals).filter(models.UserGoals.user_id == current_user.id).first()
    if db_goals:
        for key, value in goals.model_dump().items():
            setattr(db_goals, key, value)
    else:
        db_goals = models.UserGoals(**goals.model_dump(), user_id=current_user.id)
        db.add(db_goals)
    db.commit()
    db.refresh(db_goals)
    return db_goals


@router.put("/profile", response_model=schemas.UserProfile)
def update_user_profile(
    profile_update: schemas.UserProfileCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == current_user.id).first()
    if not db_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    for key, value in profile_update.dict().items():
        setattr(db_profile, key, value)
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.put("/goals", response_model=schemas.UserGoals)
def update_user_goals(
    goals_update: schemas.UserGoalsCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_goals = db.query(models.UserGoals).filter(models.UserGoals.user_id == current_user.id).first()
    if not db_goals:
        raise HTTPException(status_code=404, detail="User goals not found")
    for key, value in goals_update.dict().items():
        setattr(db_goals, key, value)
    db.commit()
    db.refresh(db_goals)
    return db_goals