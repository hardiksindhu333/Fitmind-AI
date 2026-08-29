from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from enum import Enum

class ActivityLevelEnum(str, Enum):
    sedentary = "sedentary"
    lightly_active = "lightly_active"
    moderately_active = "moderately_active"
    very_active = "very_active"
    extremely_active = "extremely_active"

class GenderEnum(str, Enum):
    male = "Male"
    female = "Female"
    other = "Other"

class GoalEnum(str, Enum):
    fat_loss = "Fat loss"
    muscle_build = "Muscle build"
    stay_active = "Stay active"

# User Schemas
class UserCreate(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class User(BaseModel):
    id: int
    username: str
    full_name: str
    email: EmailStr
    created_at: datetime
    
    class Config:
        from_attributes = True

# Profile Schemas
class UserProfileCreate(BaseModel):
    height: float
    weight: float
    age: int
    gender: GenderEnum
    activity_level: ActivityLevelEnum

class UserProfile(BaseModel):
    id: int
    user_id: int
    height: float
    weight: float
    age: int
    gender: str
    activity_level: str
    created_at: datetime
    
    class Config:
        from_attributes = True

# Goals Schemas
class UserGoalsCreate(BaseModel):
    goal_type: GoalEnum
    target_weight: float
    target_days: int
    user_notes: Optional[str] = None

class UserGoals(BaseModel):
    id: int
    user_id: int
    goal_type: str
    target_weight: float
    target_days: int
    user_notes: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

# Plan Generation Schemas
class GeneratePlansRequest(BaseModel):
    user_id: int

class NutritionPlanResponse(BaseModel):
    id: int
    user_id: int
    plan_data: Dict[str, Any]
    created_at: datetime
    
    class Config:
        from_attributes = True

class WorkoutPlanResponse(BaseModel):
    id: int
    user_id: int
    plan_data: Dict[str, Any]
    created_at: datetime
    
    class Config:
        from_attributes = True

# Chat Schemas
class ChatMessage(BaseModel):
    message: str
    
class ChatResponse(BaseModel):
    response: str
    created_at: datetime

# Token Schemas
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

# Task Schemas
class TaskResponse(BaseModel):
    id: str
    user_id: int
    task_type: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Tracking Schemas ──────────────────────────────────────────────────────────

class DailyLogCreate(BaseModel):
    log_date: date
    completed_exercises: List[str] = []

class DailyLogResponse(BaseModel):
    id: int
    user_id: int
    log_date: date
    completed_exercises: List[str]
    workout_plan_id: Optional[int] = None
    total_exercises_completed: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ExerciseCheckOffRequest(BaseModel):
    exercise_name: str
    completed: bool  # True = mark done, False = unmark

class BodyMetricCreate(BaseModel):
    logged_at: date
    weight_kg: Optional[float] = None
    body_fat_pct: Optional[float] = None

class BodyMetricResponse(BaseModel):
    id: int
    user_id: int
    logged_at: date
    weight_kg: Optional[float] = None
    body_fat_pct: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class UserStreakResponse(BaseModel):
    id: int
    user_id: int
    current_streak: int
    longest_streak: int
    last_active_date: Optional[date] = None
    total_workouts_completed: int
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Feedback Loop Schemas ─────────────────────────────────────────────────────

class PlanFeedbackRequest(BaseModel):
    feedback_text: str
    plan_type: str  # 'workout' | 'nutrition'

class PlanFeedbackResponse(BaseModel):
    feedback_id: int
    plan_type: str
    feedback_text: str
    changes_summary: Optional[str]
    updated_plan: Dict[str, Any]
    created_at: datetime

class PlanFeedbackHistoryItem(BaseModel):
    id: int
    plan_type: str
    feedback_text: str
    changes_summary: Optional[str]
    source_plan_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True