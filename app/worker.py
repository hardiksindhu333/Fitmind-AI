import logging
from celery import Celery
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import models
from app.core.langraph_workflow import workflow_manager
from app.utils import helpers

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Celery
celery_app = Celery(
    "fitness_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

# Optional configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(name="app.worker.generate_nutrition_plan_task")
def generate_nutrition_plan_task(task_id: str, user_id: int):
    logger.info(f"Starting nutrition plan generation task {task_id} for user {user_id}")
    db = SessionLocal()
    try:
        # Update task status to PROCESSING
        task = db.query(models.GenerationTask).filter(models.GenerationTask.id == task_id).first()
        if not task:
            logger.error(f"Task {task_id} not found in database")
            return
        task.status = "PROCESSING"
        db.commit()

        # Get profile and goals
        profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user_id).first()
        goals = db.query(models.UserGoals).filter(models.UserGoals.user_id == user_id).first()
        if not profile or not goals:
            raise ValueError("User profile and goals must be set before generating a nutrition plan")

        user_data = {
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
            "nutrition_plan": None,
            "workout_plan": None,
            "chat_messages": [],
            "chat_query": None,
            "chat_response": None,
            "error_message": None
        }

        # Generate plan
        result_state = workflow_manager.generate_nutrition_plan(user_data)
        nutrition_plan_data = result_state.get("nutrition_plan", {})

        # If the model returned fallback text (non-JSON), try to extract JSON
        if "plan_text" in nutrition_plan_data:
            plan_text = nutrition_plan_data["plan_text"]
            plan_raw = plan_text.get("plan_data", {}).get("plan_raw", "")
            parsed_json, error = helpers.extract_json_from_plan_raw(plan_raw)
            if parsed_json:
                nutrition_json = parsed_json
            else:
                nutrition_json = {"error": error, "raw_content": plan_raw}
        else:
            nutrition_json = nutrition_plan_data

        # Store nutrition plan
        nutrition_plan = models.NutritionPlan(
            user_id=user_id,
            plan_data=nutrition_json,
        )
        db.add(nutrition_plan)

        # Update task status to SUCCESS
        task.status = "SUCCESS"
        task.result = {"nutrition_plan": nutrition_json}
        db.commit()
        logger.info(f"Nutrition plan generation task {task_id} succeeded")

    except Exception as e:
        logger.error(f"Nutrition plan generation task {task_id} failed: {str(e)}")
        db.rollback()
        task = db.query(models.GenerationTask).filter(models.GenerationTask.id == task_id).first()
        if task:
            task.status = "FAILED"
            task.error = str(e)
            db.commit()
    finally:
        db.close()


@celery_app.task(name="app.worker.generate_workout_plan_task")
def generate_workout_plan_task(task_id: str, user_id: int):
    logger.info(f"Starting workout plan generation task {task_id} for user {user_id}")
    db = SessionLocal()
    try:
        # Update task status to PROCESSING
        task = db.query(models.GenerationTask).filter(models.GenerationTask.id == task_id).first()
        if not task:
            logger.error(f"Task {task_id} not found in database")
            return
        task.status = "PROCESSING"
        db.commit()

        # Get profile, goals, and nutrition plan
        profile = db.query(models.UserProfile).filter(models.UserProfile.user_id == user_id).first()
        goals = db.query(models.UserGoals).filter(models.UserGoals.user_id == user_id).first()
        nutrition_plan = db.query(models.NutritionPlan).filter(
            models.NutritionPlan.user_id == user_id
        ).order_by(models.NutritionPlan.created_at.desc()).first()

        if not profile or not goals or not nutrition_plan:
            raise ValueError("User profile, goals, and nutrition plan must be set before generating a workout plan")

        user_data = {
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
            "nutrition_plan": nutrition_plan.plan_data,
            "workout_plan": None,
            "chat_messages": [],
            "chat_query": None,
            "chat_response": None,
            "error_message": None
        }

        # Generate plan
        result_state = workflow_manager.generate_workout_plan(user_data)
        workout_plan_data = result_state.get("workout_plan", {})

        # Handle unstructured response
        if "plan_text" in workout_plan_data:
            plan_text = workout_plan_data.get("plan_text", "")
            if isinstance(plan_text, dict):
                plan_raw = plan_text.get("plan_data", {}).get("plan_raw", "")
            else:
                plan_raw = plan_text
            parsed_json, error = helpers.extract_json_from_plan_raw(plan_raw)
            if parsed_json:
                workout_json = parsed_json
            else:
                workout_json = {"error": error, "raw_content": plan_raw}
        else:
            workout_json = workout_plan_data

        # Store workout plan
        workout_plan = models.WorkoutPlan(
            user_id=user_id,
            plan_data=workout_json,
        )
        db.add(workout_plan)

        # Update task status to SUCCESS
        task.status = "SUCCESS"
        task.result = {"workout_plan": workout_json}
        db.commit()
        logger.info(f"Workout plan generation task {task_id} succeeded")

    except Exception as e:
        logger.error(f"Workout plan generation task {task_id} failed: {str(e)}")
        db.rollback()
        task = db.query(models.GenerationTask).filter(models.GenerationTask.id == task_id).first()
        if task:
            task.status = "FAILED"
            task.error = str(e)
            db.commit()
    finally:
        db.close()
