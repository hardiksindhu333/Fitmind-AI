import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import models, schemas
from ..dependencies import get_current_user
from app.worker import generate_nutrition_plan_task, generate_workout_plan_task

router = APIRouter()

@router.post("/generate-nutrition-plan", status_code=status.HTTP_202_ACCEPTED)
def generate_nutrition_plan(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Get user profile and goals
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()
    goals = db.query(models.UserGoals).filter(
        models.UserGoals.user_id == current_user.id
    ).first()
    if not profile or not goals:
        raise HTTPException(
            status_code=400,
            detail="User profile and goals must be set before generating a nutrition plan"
        )

    # Rate Limit Checks
    active_task = db.query(models.GenerationTask).filter(
        models.GenerationTask.user_id == current_user.id,
        models.GenerationTask.task_type == "nutrition",
        models.GenerationTask.status.in_(["PENDING", "PROCESSING"])
    ).first()
    if active_task:
        # If the active task is stale (older than 1 hour), mark it failed and allow a new task.
        stale_threshold = datetime.utcnow() - timedelta(hours=1)
        if active_task.created_at and active_task.created_at < stale_threshold:
            try:
                active_task.status = "FAILED"
                active_task.error = "Automatically marked FAILED due to being stuck >1 hour"
                db.commit()
            except Exception:
                db.rollback()
        else:
            raise HTTPException(
                status_code=400,
                detail="A nutrition plan generation task is already in progress."
            )

    one_day_ago = datetime.utcnow() - timedelta(days=1)
    recent_plan = db.query(models.NutritionPlan).filter(
        models.NutritionPlan.user_id == current_user.id,
        models.NutritionPlan.created_at >= one_day_ago
    ).first()
    if recent_plan:
        raise HTTPException(
            status_code=429,
            detail="You can only generate one nutrition plan per day."
        )

    task_id = str(uuid.uuid4())
    db_task = models.GenerationTask(
        id=task_id,
        user_id=current_user.id,
        task_type="nutrition",
        status="PENDING"
    )
    db.add(db_task)
    db.commit()

    generate_nutrition_plan_task.delay(task_id, current_user.id)

    return {
        "task_id": task_id,
        "status": "PENDING"
    }

@router.post("/generate-workout-plan", status_code=status.HTTP_202_ACCEPTED)
def generate_workout_plan(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate, parse, and store a structured workout plan."""
    
    # Fetch user info
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()
    goals = db.query(models.UserGoals).filter(
        models.UserGoals.user_id == current_user.id
    ).first()
    nutrition_plan = db.query(models.NutritionPlan).filter(
        models.NutritionPlan.user_id == current_user.id
    ).order_by(models.NutritionPlan.created_at.desc()).first()

    if not profile or not goals or not nutrition_plan:
        raise HTTPException(
            status_code=400,
            detail="User profile, goals, and nutrition plan must be set before generating a workout plan"
        )

    # Rate Limit Checks
    active_task = db.query(models.GenerationTask).filter(
        models.GenerationTask.user_id == current_user.id,
        models.GenerationTask.task_type == "workout",
        models.GenerationTask.status.in_(["PENDING", "PROCESSING"])
    ).first()
    if active_task:
        # If the active task is stale (older than 1 hour), mark it failed and allow a new task.
        stale_threshold = datetime.utcnow() - timedelta(hours=1)
        if active_task.created_at and active_task.created_at < stale_threshold:
            try:
                active_task.status = "FAILED"
                active_task.error = "Automatically marked FAILED due to being stuck >1 hour"
                db.commit()
            except Exception:
                db.rollback()
        else:
            raise HTTPException(
                status_code=400,
                detail="A workout plan generation task is already in progress."
            )

    one_day_ago = datetime.utcnow() - timedelta(days=1)
    recent_plan = db.query(models.WorkoutPlan).filter(
        models.WorkoutPlan.user_id == current_user.id,
        models.WorkoutPlan.created_at >= one_day_ago
    ).first()
    if recent_plan:
        raise HTTPException(
            status_code=429,
            detail="You can only generate one workout plan per day."
        )

    task_id = str(uuid.uuid4())
    db_task = models.GenerationTask(
        id=task_id,
        user_id=current_user.id,
        task_type="workout",
        status="PENDING"
    )
    db.add(db_task)
    db.commit()

    generate_workout_plan_task.delay(task_id, current_user.id)

    return {
        "task_id": task_id,
        "status": "PENDING"
    }

@router.get("/plans")
def get_user_plans(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    nutrition_plan = db.query(models.NutritionPlan).filter(
        models.NutritionPlan.user_id == current_user.id
    ).order_by(models.NutritionPlan.created_at.desc()).first()
    
    workout_plan = db.query(models.WorkoutPlan).filter(
        models.WorkoutPlan.user_id == current_user.id
    ).order_by(models.WorkoutPlan.created_at.desc()).first()
    
    return {
        "nutrition_plan":  nutrition_plan if nutrition_plan else None,
        "workout_plan": workout_plan if workout_plan else None
    }

@router.get("/tasks/{task_id}", response_model=schemas.TaskResponse)
def get_task_status(
    task_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    task = db.query(models.GenerationTask).filter(
        models.GenerationTask.id == task_id,
        models.GenerationTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task