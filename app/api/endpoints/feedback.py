"""
Feedback Loop endpoints — adaptive plan modification via AI.
POST /api/feedback/plan   → adapt workout or nutrition plan based on free-text feedback
GET  /api/feedback/history → paginated history of past feedback + what the AI changed
"""
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.langraph_workflow import workflow_manager
from ...models import models, schemas
from ..dependencies import get_current_user

router = APIRouter()

# Maximum adaptations per user per plan_type per day
DAILY_FEEDBACK_LIMIT = 5


def _check_feedback_rate_limit(user_id: int, plan_type: str, db: Session) -> None:
    """Raise 429 if the user has already submitted DAILY_FEEDBACK_LIMIT adaptations today."""
    one_day_ago = datetime.utcnow() - timedelta(days=1)
    count = (
        db.query(models.PlanFeedback)
        .filter(
            models.PlanFeedback.user_id == user_id,
            models.PlanFeedback.plan_type == plan_type,
            models.PlanFeedback.created_at >= one_day_ago,
        )
        .count()
    )
    if count >= DAILY_FEEDBACK_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You have reached the limit of {DAILY_FEEDBACK_LIMIT} "
                f"{plan_type} plan adaptations per day. Try again tomorrow."
            ),
        )


def _build_user_data(
    profile: models.UserProfile,
    goals: models.UserGoals,
    workout_plan: models.WorkoutPlan | None,
    nutrition_plan: models.NutritionPlan | None,
    user_id: int,
) -> dict:
    return {
        "user_id": user_id,
        "height": profile.height,
        "weight": profile.weight,
        "age": profile.age,
        "gender": profile.gender,
        "activity_level": profile.activity_level,
        "goal_type": goals.goal_type,
        "target_weight": goals.target_weight,
        "target_days": goals.target_days,
        "user_notes": goals.user_notes,
        "workout_plan": workout_plan.plan_data if workout_plan else None,
        "nutrition_plan": nutrition_plan.plan_data if nutrition_plan else None,
        "chat_messages": [],
        "chat_query": None,
        "chat_response": None,
        "error_message": None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/plan", response_model=schemas.PlanFeedbackResponse)
def submit_plan_feedback(
    payload: schemas.PlanFeedbackRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit natural-language feedback about a workout or nutrition plan.
    The AI surgically adapts the plan, preserving historical preferences,
    and saves the result as a new plan version (old plan rows are kept intact).

    - **plan_type**: `"workout"` or `"nutrition"`
    - **feedback_text**: e.g. *"This feels too intense for my knees"*
    """
    plan_type = payload.plan_type.lower()
    if plan_type not in ("workout", "nutrition"):
        raise HTTPException(
            status_code=422,
            detail="plan_type must be 'workout' or 'nutrition'.",
        )

    # Rate limit check
    _check_feedback_rate_limit(current_user.id, plan_type, db)

    # Load profile & goals
    profile = (
        db.query(models.UserProfile)
        .filter(models.UserProfile.user_id == current_user.id)
        .first()
    )
    goals = (
        db.query(models.UserGoals)
        .filter(models.UserGoals.user_id == current_user.id)
        .first()
    )
    if not profile or not goals:
        raise HTTPException(
            status_code=400,
            detail="User profile and goals must be set before submitting feedback.",
        )

    # Load current plans
    latest_workout = (
        db.query(models.WorkoutPlan)
        .filter(models.WorkoutPlan.user_id == current_user.id)
        .order_by(models.WorkoutPlan.created_at.desc())
        .first()
    )
    latest_nutrition = (
        db.query(models.NutritionPlan)
        .filter(models.NutritionPlan.user_id == current_user.id)
        .order_by(models.NutritionPlan.created_at.desc())
        .first()
    )

    # Ensure the relevant plan actually exists
    if plan_type == "workout" and not latest_workout:
        raise HTTPException(
            status_code=400,
            detail="No workout plan found. Generate one first before submitting feedback.",
        )
    if plan_type == "nutrition" and not latest_nutrition:
        raise HTTPException(
            status_code=400,
            detail="No nutrition plan found. Generate one first before submitting feedback.",
        )

    # Load cumulative feedback history for this plan type (last 10, oldest first)
    past_feedbacks = (
        db.query(models.PlanFeedback)
        .filter(
            models.PlanFeedback.user_id == current_user.id,
            models.PlanFeedback.plan_type == plan_type,
        )
        .order_by(models.PlanFeedback.created_at.asc())
        .limit(10)
        .all()
    )
    feedback_history = [
        {
            "feedback_text": fb.feedback_text,
            "changes_summary": fb.changes_summary or "",
        }
        for fb in past_feedbacks
    ]

    user_data = _build_user_data(
        profile, goals, latest_workout, latest_nutrition, current_user.id
    )

    # ── Call the AI ───────────────────────────────────────────────────────────
    if plan_type == "workout":
        updated_plan = workflow_manager.adapt_workout_plan(
            user_data, payload.feedback_text, feedback_history
        )
        source_plan_id = latest_workout.id if latest_workout else None

        # Extract and strip the AI's embedded summary
        changes_summary: str = updated_plan.pop("changes_summary", "Plan adapted per your feedback.")

        # Persist new plan version (original row untouched)
        new_plan_row = models.WorkoutPlan(
            user_id=current_user.id,
            plan_data=updated_plan,
        )
        db.add(new_plan_row)

    else:  # nutrition
        updated_plan = workflow_manager.adapt_nutrition_plan(
            user_data, payload.feedback_text, feedback_history
        )
        source_plan_id = latest_nutrition.id if latest_nutrition else None

        changes_summary = updated_plan.pop("changes_summary", "Plan adapted per your feedback.")

        new_plan_row = models.NutritionPlan(
            user_id=current_user.id,
            plan_data=updated_plan,
        )
        db.add(new_plan_row)

    db.flush()  # get new_plan_row.id before committing

    # Persist feedback record
    feedback_record = models.PlanFeedback(
        user_id=current_user.id,
        plan_type=plan_type,
        feedback_text=payload.feedback_text,
        changes_summary=changes_summary,
        source_plan_id=source_plan_id,
    )
    db.add(feedback_record)
    db.commit()
    db.refresh(feedback_record)

    return schemas.PlanFeedbackResponse(
        feedback_id=feedback_record.id,
        plan_type=plan_type,
        feedback_text=payload.feedback_text,
        changes_summary=changes_summary,
        updated_plan=updated_plan,
        created_at=feedback_record.created_at,
    )


@router.get("/history", response_model=List[schemas.PlanFeedbackHistoryItem])
def get_feedback_history(
    plan_type: str = Query(
        default=None,
        description="Filter by plan type: 'workout' or 'nutrition'. Omit for all.",
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the history of all feedback submissions for the current user, newest first.
    Optionally filter by plan_type.
    """
    query = db.query(models.PlanFeedback).filter(
        models.PlanFeedback.user_id == current_user.id
    )
    if plan_type:
        plan_type = plan_type.lower()
        if plan_type not in ("workout", "nutrition"):
            raise HTTPException(
                status_code=422, detail="plan_type must be 'workout' or 'nutrition'."
            )
        query = query.filter(models.PlanFeedback.plan_type == plan_type)

    records = (
        query.order_by(models.PlanFeedback.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return records
