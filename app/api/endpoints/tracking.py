"""
Tracking endpoints – Daily Log, Body Metrics, Streak
"""
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import models, schemas
from ..dependencies import get_current_user

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_daily_log(
    user_id: int, log_date: date, db: Session
) -> models.DailyLog:
    """Fetch existing daily log or create an empty one."""
    daily_log = (
        db.query(models.DailyLog)
        .filter(
            models.DailyLog.user_id == user_id,
            models.DailyLog.log_date == log_date,
        )
        .first()
    )
    if not daily_log:
        # Link to the user's latest workout plan if one exists
        latest_plan = (
            db.query(models.WorkoutPlan)
            .filter(models.WorkoutPlan.user_id == user_id)
            .order_by(models.WorkoutPlan.created_at.desc())
            .first()
        )
        daily_log = models.DailyLog(
            user_id=user_id,
            log_date=log_date,
            completed_exercises=[],
            workout_plan_id=latest_plan.id if latest_plan else None,
        )
        db.add(daily_log)
        db.commit()
        db.refresh(daily_log)
    return daily_log


def _update_streak(user_id: int, today: date, db: Session) -> models.UserStreak:
    """
    Recalculate and persist the user's streak.
    Rules:
      - last_active_date == today  → already counted, no-op
      - last_active_date == yesterday → extend streak
      - anything else              → reset to 1
    Always bumps total_workouts_completed when advancing from a new day.
    """
    streak = (
        db.query(models.UserStreak)
        .filter(models.UserStreak.user_id == user_id)
        .first()
    )
    if not streak:
        streak = models.UserStreak(
            user_id=user_id,
            current_streak=0,
            longest_streak=0,
            last_active_date=None,
            total_workouts_completed=0,
        )
        db.add(streak)

    if streak.last_active_date == today:
        # Already counted today – nothing changes
        return streak

    streak.total_workouts_completed += 1

    if streak.last_active_date == today - timedelta(days=1):
        streak.current_streak += 1
    else:
        streak.current_streak = 1

    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak

    streak.last_active_date = today
    db.commit()
    db.refresh(streak)
    return streak


def _daily_log_to_response(log: models.DailyLog) -> schemas.DailyLogResponse:
    completed = log.completed_exercises or []
    return schemas.DailyLogResponse(
        id=log.id,
        user_id=log.user_id,
        log_date=log.log_date,
        completed_exercises=completed,
        workout_plan_id=log.workout_plan_id,
        total_exercises_completed=len(completed),
        created_at=log.created_at,
        updated_at=log.updated_at,
    )


# ── Daily Log Endpoints ───────────────────────────────────────────────────────

@router.get("/daily-log", response_model=schemas.DailyLogResponse)
def get_today_log(
    log_date: Optional[date] = Query(default=None, description="Defaults to today (server date)"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the daily workout log for today (or a specific date).
    Auto-creates an empty log if one doesn't exist yet.
    The response includes the list of completed exercises and the user's active
    workout plan id so clients can fetch today's scheduled exercises.
    """
    target_date = log_date or date.today()
    daily_log = _get_or_create_daily_log(current_user.id, target_date, db)
    return _daily_log_to_response(daily_log)


@router.post("/daily-log", response_model=schemas.DailyLogResponse)
def upsert_daily_log(
    payload: schemas.DailyLogCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upsert a full daily log for a given date.
    Replaces completed_exercises list entirely.
    If at least 1 exercise is completed, streak is updated.
    """
    daily_log = _get_or_create_daily_log(current_user.id, payload.log_date, db)
    daily_log.completed_exercises = payload.completed_exercises
    db.commit()
    db.refresh(daily_log)

    if payload.completed_exercises:
        _update_streak(current_user.id, payload.log_date, db)

    return _daily_log_to_response(daily_log)


@router.patch("/daily-log/exercise", response_model=schemas.DailyLogResponse)
def toggle_exercise(
    payload: schemas.ExerciseCheckOffRequest,
    log_date: Optional[date] = Query(default=None, description="Defaults to today"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Toggle a single exercise as completed or not completed.
    If at least 1 exercise is now marked complete, the streak is updated for that day.
    """
    target_date = log_date or date.today()
    daily_log = _get_or_create_daily_log(current_user.id, target_date, db)

    completed: List[str] = list(daily_log.completed_exercises or [])

    if payload.completed:
        if payload.exercise_name not in completed:
            completed.append(payload.exercise_name)
    else:
        completed = [e for e in completed if e != payload.exercise_name]

    daily_log.completed_exercises = completed
    db.commit()
    db.refresh(daily_log)

    # Update streak whenever ≥1 exercise is marked done for this day
    if completed:
        _update_streak(current_user.id, target_date, db)

    return _daily_log_to_response(daily_log)


@router.get("/daily-log/history", response_model=List[schemas.DailyLogResponse])
def get_log_history(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Paginated list of past daily logs, newest first.
    """
    logs = (
        db.query(models.DailyLog)
        .filter(models.DailyLog.user_id == current_user.id)
        .order_by(models.DailyLog.log_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_daily_log_to_response(log) for log in logs]


# ── Body Metrics Endpoints ────────────────────────────────────────────────────

@router.post("/body-metrics", response_model=schemas.BodyMetricResponse)
def log_body_metrics(
    payload: schemas.BodyMetricCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Log body weight and/or body fat percentage for a given date.
    If a record already exists for that date, it is updated (upsert).
    At least one of weight_kg or body_fat_pct must be provided.
    """
    if payload.weight_kg is None and payload.body_fat_pct is None:
        raise HTTPException(
            status_code=422,
            detail="At least one of weight_kg or body_fat_pct must be provided.",
        )

    existing = (
        db.query(models.BodyMetricLog)
        .filter(
            models.BodyMetricLog.user_id == current_user.id,
            models.BodyMetricLog.logged_at == payload.logged_at,
        )
        .first()
    )

    if existing:
        if payload.weight_kg is not None:
            existing.weight_kg = payload.weight_kg
        if payload.body_fat_pct is not None:
            existing.body_fat_pct = payload.body_fat_pct
        db.commit()
        db.refresh(existing)
        return existing
    else:
        new_entry = models.BodyMetricLog(
            user_id=current_user.id,
            logged_at=payload.logged_at,
            weight_kg=payload.weight_kg,
            body_fat_pct=payload.body_fat_pct,
        )
        db.add(new_entry)
        db.commit()
        db.refresh(new_entry)
        return new_entry


@router.get("/body-metrics", response_model=List[schemas.BodyMetricResponse])
def get_body_metrics(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=90, ge=1, le=365),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return all body metric logs for the current user, oldest first (for charting).
    """
    logs = (
        db.query(models.BodyMetricLog)
        .filter(models.BodyMetricLog.user_id == current_user.id)
        .order_by(models.BodyMetricLog.logged_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs


# ── Streak Endpoint ───────────────────────────────────────────────────────────

@router.get("/streak", response_model=schemas.UserStreakResponse)
def get_streak(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the current user's streak data.
    Auto-creates a zeroed record if none exists yet.
    """
    streak = (
        db.query(models.UserStreak)
        .filter(models.UserStreak.user_id == current_user.id)
        .first()
    )
    if not streak:
        streak = models.UserStreak(
            user_id=current_user.id,
            current_streak=0,
            longest_streak=0,
            last_active_date=None,
            total_workouts_completed=0,
        )
        db.add(streak)
        db.commit()
        db.refresh(streak)
    return streak
