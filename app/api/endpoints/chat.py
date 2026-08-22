from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import json
from ...core.database import get_db
from ...core.langraph_workflow import workflow_manager
from ...models import models, schemas
from ...utils import helpers
from ...utils.rate_limit import check_chat_rate_limit
from ..dependencies import get_current_user

router = APIRouter()

@router.post("/chat", response_model=schemas.ChatResponse)
def chat_with_ai(
    message: schemas.ChatMessage,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check rate limit
    if not check_chat_rate_limit(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. You can only make 20 requests per minute."
        )
    # Get user profile and goals
    profile = db.query(models.UserProfile).filter(
        models.UserProfile.user_id == current_user.id
    ).first()
    
    goals = db.query(models.UserGoals).filter(
        models.UserGoals.user_id == current_user.id
    ).first()
    
    # Get latest plans
    nutrition_plan = db.query(models.NutritionPlan).filter(
        models.NutritionPlan.user_id == current_user.id
    ).order_by(models.NutritionPlan.created_at.desc()).first()
    
    workout_plan = db.query(models.WorkoutPlan).filter(
        models.WorkoutPlan.user_id == current_user.id
    ).order_by(models.WorkoutPlan.created_at.desc()).first()
    
    if not profile or not goals:
        raise HTTPException(
            status_code=400,
            detail="User profile and goals must be set before chatting"
        )
    
    # Get last N chat messages for context
    history_records = db.query(models.ChatHistory).filter(
        models.ChatHistory.user_id == current_user.id
    ).order_by(models.ChatHistory.created_at.desc()).limit(10).all()
    
    chat_messages = [
        {"user": record.message, "assistant": record.response}
        for record in reversed(history_records)
    ]

    # Prepare user data for chat
    user_data = {
        "user_id": current_user.id,
        "height": profile.height,
        "weight": profile.weight,
        "age": profile.age,
        "gender": profile.gender,
        "activity_level": profile.activity_level,
        "goal_type": goals.goal_type,
        "target_weight": goals.target_weight,
        "target_days": goals.target_days,
        "user_notes": goals.user_notes,
        "nutrition_plan": nutrition_plan.plan_data if nutrition_plan else None,
        "workout_plan": workout_plan.plan_data if workout_plan else None,
        "chat_messages": chat_messages,
        "chat_query": None,
        "chat_response": None,
        "error_message": None
    }
    
    # Get AI response
    response = workflow_manager.chat_with_AI(user_data, message.message)

    chat_history = models.ChatHistory(
        user_id=current_user.id,
        message=message.message,
        response=response
    )
    db.add(chat_history)
    db.commit()
    db.refresh(chat_history)

    return schemas.ChatResponse(
        response=response,
        created_at=chat_history.created_at,  # type: ignore
    )   

@router.get("/chat/history")
def get_chat_history(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50
):
    history = db.query(models.ChatHistory).filter(
        models.ChatHistory.user_id == current_user.id
    ).order_by(models.ChatHistory.created_at.desc()).limit(limit).all()
    
    return [
        {
            "message": chat.message,
            "response": chat.response,
            "created_at": chat.created_at
        }
        for chat in history
    ]