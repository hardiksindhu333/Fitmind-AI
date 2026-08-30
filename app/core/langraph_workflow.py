from typing import TypedDict, Optional, Dict, Any, List
from enum import Enum
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
import json
import re
import os
from .config import settings

# Initialize LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
    google_api_key=settings.GOOGLE_API_KEY
)

class FitnessAppState(TypedDict):
    # User Profile Information
    height: float
    weight: float
    age: int
    gender: str
    activity_level: str
    
    # User Goals
    goal_type: str
    target_weight: float
    target_days: int
    
    # User Notes
    user_notes: Optional[str]
    
    # Generated Plans
    nutrition_plan: Optional[Dict[str, Any]]
    workout_plan: Optional[Dict[str, Any]]
    
    # Chat Context
    chat_messages: List[Dict[str, str]]
    chat_query: Optional[str]
    chat_response: Optional[str]
    
    # Error Handling
    error_message: Optional[str]

def calculate_bmr(height: float, weight: float, age: int, gender: str) -> float:
    """Calculate Basal Metabolic Rate using Mifflin-St Jeor equation"""
    if gender.lower() == "male":
        return 10 * weight + 6.25 * height - 5 * age + 5
    else:
        return 10 * weight + 6.25 * height - 5 * age - 161

def calculate_daily_calories(bmr: float, activity_level: str) -> float:
    """Calculate daily calorie needs based on activity level"""
    multipliers = {
        "sedentary": 1.2,
        "lightly_active": 1.375,
        "moderately_active": 1.55,
        "very_active": 1.725,
        "extremely_active": 1.9
    }
    return bmr * multipliers.get(activity_level.lower(), 1.2)

def adjust_calories_for_goal(daily_calories: float, goal_type: str, target_weight: float, current_weight: float, target_days: int) -> float:
    """Adjust calories based on user goals"""
    if goal_type == "Fat loss":
        if target_days == 0:
            raise ValueError("target_days cannot be zero.")
        
        weekly_loss = (current_weight - target_weight) / (target_days / 7)
        deficit = min(weekly_loss * 1000, 1000)  # Max 1000 cal deficit
        return daily_calories - deficit
    elif goal_type == "Muscle build":
        return daily_calories + 300  # Moderate surplus
    else:
        return daily_calories  # Maintenance

def generate_nutrition_plan(state: FitnessAppState) -> FitnessAppState:
    """Generate personalized nutrition plan using LLM with structured JSON output."""
    
    # Calculate BMR and daily calorie needs
    bmr = calculate_bmr(state["height"], state["weight"], state["age"], state["gender"])
    daily_calories = calculate_daily_calories(bmr, state["activity_level"])
    
    # Adjust calories based on goal
    target_calories = adjust_calories_for_goal(
        daily_calories,
        state["goal_type"],
        state["target_weight"],
        state["weight"],
        state["target_days"]
    )

    # Nutrition prompt for LLM
    nutrition_prompt = f"""
    You are a fitness and nutrition expert. 
    Create a detailed, personalized nutrition plan for the following user profile:
    - Age: {state['age']}, Gender: {state['gender']}
    - Height: {state['height']} cm, Weight: {state['weight']} kg
    - Activity Level: {state['activity_level']}
    - Goal: {state['goal_type']}, Target Weight: {state['target_weight']} kg in {state['target_days']} days
    - Target Daily Calories: {target_calories}
    - Additional Notes: {state['user_notes']}

    Provide the response *only* in valid JSON format with the following keys:
    {{
        "daily_calories": number,
        "macros": {{
            "protein": number,
            "carbs": number,
            "fats": number
        }},
        "meal_plan": {{
            "breakfast": string,
            "lunch": string,
            "dinner": string,
            "snacks": string
        }},
        "hydration": string,
        "supplements": string
    }}
    """

    response = llm.invoke(nutrition_prompt)
    response_text = str(getattr(response, "content", response)).strip()

    # Attempt to extract JSON substring if extra text appears
    match = re.search(r'\{.*\}', response_text, re.DOTALL)
    json_str = match.group(0) if match else response_text

    # Parse JSON safely
    try:
        nutrition_plan = json.loads(json_str)
    except json.JSONDecodeError:
        # fallback: structured but with default placeholders
        nutrition_plan = {
            "daily_calories": target_calories,
            "macros": {"protein": None, "carbs": None, "fats": None},
            "meal_plan": {"breakfast": "", "lunch": "", "dinner": "", "snacks": ""},
            "hydration": "",
            "supplements": "",
            "raw_response": response_text  # store the raw LLM text for debugging
        }

    # Attach to state and return
    state["nutrition_plan"] = nutrition_plan
    return state

def generate_workout_plan(state: FitnessAppState) -> FitnessAppState:
    """Generate personalized workout plan with structured JSON output."""
    
    # Prompt for LLM
    workout_prompt = f"""
    You are a professional fitness trainer.
    Create a detailed, personalized workout plan for the following user profile:
    - Age: {state['age']}, Gender: {state['gender']}
    - Height: {state['height']} cm, Weight: {state['weight']} kg
    - Activity Level: {state['activity_level']}
    - Goal: {state['goal_type']}, Target Weight: {state['target_weight']} kg in {state['target_days']} days
    - Nutrition Plan Summary: {state['nutrition_plan']}
    - Additional Notes: {state['user_notes']}
    
    Provide the response strictly in valid JSON format with the following structure:
    {{
        "weekly_schedule": {{
            "monday": string,
            "tuesday": string,
            "wednesday": string,
            "thursday": string,
            "friday": string,
            "saturday": string,
            "sunday": string
        }},
        "progression": string,
        "recovery": string
    }}
    """

    # Invoke the LLM
    response = llm.invoke(workout_prompt)
    response_text = str(getattr(response, "content", response)).strip()

    # Extract only JSON substring if LLM adds extra commentary
    match = re.search(r'\{.*\}', response_text, re.DOTALL)
    json_str = match.group(0) if match else response_text

    # Try parsing structured JSON
    try:
        workout_plan = json.loads(json_str)
    except json.JSONDecodeError:
        # Fallback if JSON parsing fails
        workout_plan = {
            "weekly_schedule": {
                "monday": "", "tuesday": "", "wednesday": "",
                "thursday": "", "friday": "", "saturday": "", "sunday": ""
            },
            "progression": "",
            "recovery": "",
            "raw_response": response_text
        }

    # Attach to state and return
    state["workout_plan"] = workout_plan
    return state

def handle_chat_query(state: FitnessAppState) -> FitnessAppState:
    """Handle general user queries in chat"""
    
    # Format recent chat history if available
    history_str = ""
    if state.get("chat_messages"):
        history_str = "\n".join([
            f"User: {msg['user']}\nAssistant: {msg['assistant']}"
            for msg in state["chat_messages"]
        ])
    
    chat_prompt = f"""
    User context:
    - Profile: Age {state['age']}, {state['gender']}, {state['height']}cm, {state['weight']}kg
    - Activity Level: {state['activity_level']}
    - Goals: {state['goal_type']}, target {state['target_weight']}kg in {state['target_days']} days
    - User Notes: {state['user_notes']}
    - Current Nutrition Plan: {state['nutrition_plan']}
    - Current Workout Plan: {state['workout_plan']}
    
    Chat History:
    {history_str}
    
    User Question: {state['chat_query']}
    
    Provide a helpful, personalized response considering their profile, plans, and the chat history.
    """
    
    response = llm.invoke(chat_prompt)
    response_content = str(getattr(response, "content", response))
    
    # Add to chat history
    if not state["chat_messages"]:
        state["chat_messages"] = []
    
    state["chat_messages"].append({
        "user": state["chat_query"] or "",
        "assistant": response_content
    })
    
    state["chat_response"] = response_content
    state["chat_query"] = None
    return state

class FitnessWorkflowManager:
    def __init__(self):
        self.memory = MemorySaver()
        self.workflow = self._create_workflow()
    
    def _create_workflow(self):
        """Create and configure the LangGraph workflow"""
        workflow = StateGraph(FitnessAppState)
        
        # Add nodes
        workflow.add_node("generate_nutrition_plan", generate_nutrition_plan)
        workflow.add_node("generate_workout_plan", generate_workout_plan)
        workflow.add_node("handle_chat_query", handle_chat_query)
        
        # Set entry point and edges
        workflow.add_edge(START, "generate_nutrition_plan")
        workflow.add_edge("generate_nutrition_plan", "generate_workout_plan")
        workflow.add_edge("generate_workout_plan", END)
        workflow.add_edge("handle_chat_query", END)
        
        return workflow.compile(checkpointer=self.memory)
    
    def generate_nutrition_plan(self, user_data: dict) -> dict:
        state = FitnessAppState(**user_data)
        result = generate_nutrition_plan(state)
        return dict(result)

    def generate_workout_plan(self, user_data: dict) -> dict:
        state = FitnessAppState(**user_data)
        result = generate_workout_plan(state)
        return dict(result)
    
    def chat_with_AI(self, user_data: Dict[str, Any], query: str) -> str:
        """Handle chat queries"""
        state = FitnessAppState(**user_data)
        state["chat_query"] = query
        
        config = RunnableConfig(configurable={"thread_id": f"user_{user_data.get('user_id', 'unknown')}"})
        
        # Use only the chat node
        result = handle_chat_query(state)
        return result["chat_response"] or ""

    def adapt_workout_plan(
        self,
        user_data: Dict[str, Any],
        feedback_text: str,
        feedback_history: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Surgically adapt the current workout plan based on user feedback.
        feedback_history: list of {feedback_text, changes_summary} dicts (oldest→newest).
        Returns the updated plan dict (same schema as WorkoutPlan.plan_data) with an
        extra top-level key 'changes_summary' holding a plain-English description.
        """
        current_plan = user_data.get("workout_plan") or {}

        # Build cumulative constraints from past feedback
        history_block = ""
        if feedback_history:
            history_block = "Previously applied user preferences (must all still be respected):\n"
            for i, fb in enumerate(feedback_history, 1):
                history_block += (
                    f"  {i}. Feedback: \"{fb['feedback_text']}\" "
                    f"→ Change made: {fb.get('changes_summary', 'N/A')}\n"
                )

        prompt = f"""You are an expert personal trainer adapting a workout plan based on user feedback.

CURRENT WORKOUT PLAN (JSON):
{json.dumps(current_plan, indent=2)}

USER PROFILE:
- Age: {user_data.get('age')}, Gender: {user_data.get('gender')}
- Height: {user_data.get('height')} cm, Weight: {user_data.get('weight')} kg
- Activity Level: {user_data.get('activity_level')}
- Goal: {user_data.get('goal_type')}, Target Weight: {user_data.get('target_weight')} kg in {user_data.get('target_days')} days

{history_block}

NEW USER FEEDBACK: "{feedback_text}"

INSTRUCTIONS:
1. Make the MINIMAL necessary changes to satisfy the new feedback while honouring all past preferences above.
2. Keep the overall plan structure and goal intact — only modify what must change.
3. Return the COMPLETE updated plan as valid JSON using the EXACT same schema as the current plan above.
4. Add one extra top-level key "changes_summary" (string) with a concise human-readable description of what you changed and why.

Return ONLY valid JSON. No markdown, no explanation outside the JSON.
"""
        response = llm.invoke(prompt)
        response_text = str(getattr(response, "content", response)).strip()

        match = re.search(r'\{.*\}', response_text, re.DOTALL)
        json_str = match.group(0) if match else response_text

        try:
            updated_plan = json.loads(json_str)
        except json.JSONDecodeError:
            # Fallback: return original plan with error note
            updated_plan = dict(current_plan)
            updated_plan["changes_summary"] = (
                f"Could not parse AI response. Raw: {response_text[:300]}"
            )

        return updated_plan

    def adapt_nutrition_plan(
        self,
        user_data: Dict[str, Any],
        feedback_text: str,
        feedback_history: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Surgically adapt the current nutrition plan based on user feedback.
        Same contract as adapt_workout_plan.
        """
        current_plan = user_data.get("nutrition_plan") or {}

        history_block = ""
        if feedback_history:
            history_block = "Previously applied user preferences (must all still be respected):\n"
            for i, fb in enumerate(feedback_history, 1):
                history_block += (
                    f"  {i}. Feedback: \"{fb['feedback_text']}\" "
                    f"→ Change made: {fb.get('changes_summary', 'N/A')}\n"
                )

        prompt = f"""You are an expert nutritionist adapting a nutrition plan based on user feedback.

CURRENT NUTRITION PLAN (JSON):
{json.dumps(current_plan, indent=2)}

USER PROFILE:
- Age: {user_data.get('age')}, Gender: {user_data.get('gender')}
- Height: {user_data.get('height')} cm, Weight: {user_data.get('weight')} kg
- Activity Level: {user_data.get('activity_level')}
- Goal: {user_data.get('goal_type')}, Target Weight: {user_data.get('target_weight')} kg in {user_data.get('target_days')} days

{history_block}

NEW USER FEEDBACK: "{feedback_text}"

INSTRUCTIONS:
1. Make the MINIMAL necessary changes to satisfy the new feedback while honouring all past preferences above.
2. Preserve total daily calories and macro targets unless the feedback explicitly requires changing them.
3. Return the COMPLETE updated plan as valid JSON using the EXACT same schema as the current plan above.
4. Add one extra top-level key "changes_summary" (string) with a concise human-readable description of what you changed and why.

Return ONLY valid JSON. No markdown, no explanation outside the JSON.
"""
        response = llm.invoke(prompt)
        response_text = str(getattr(response, "content", response)).strip()

        match = re.search(r'\{.*\}', response_text, re.DOTALL)
        json_str = match.group(0) if match else response_text

        try:
            updated_plan = json.loads(json_str)
        except json.JSONDecodeError:
            updated_plan = dict(current_plan)
            updated_plan["changes_summary"] = (
                f"Could not parse AI response. Raw: {response_text[:300]}"
            )

        return updated_plan

# Global instance
workflow_manager = FitnessWorkflowManager()