import json
import re

def extract_json_from_plan_raw(plan_raw):
    # Step 1: Remove 'content=', single/double quotes
    content = plan_raw
    if content.startswith("content="):
        content = content[len("content="):].strip("'\"")
    # Step 2: Extract JSON from code block
    match = re.search(r"``````", content, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # fallback: try to find the first "{" to last "}" bracket (may need tuning)
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            json_str = content[start:end+1]
        else:
            return None, "JSON block not found"
    # Step 3: Restore normal newlines
    json_str = json_str.replace("\\n", "\n")
    try:
        return json.loads(json_str), None
    except Exception as e:
        return None, str(e)

def format_nutrition_plan(plan):
    if not plan:
        return "No nutrition plan available."
    return (
        f"### Nutrition Plan\n"
        f"- **Daily Calories:** {plan.get('daily_calories', 'N/A')}\n"
        f"- **Macros:**\n"
        f"  - Protein: {plan.get('macros', {}).get('protein', 'N/A')}g\n"
        f"  - Carbs: {plan.get('macros', {}).get('carbs', 'N/A')}g\n"
        f"  - Fats: {plan.get('macros', {}).get('fats', 'N/A')}g\n"
        f"- **Meal Plan:**\n"
        f"  - Breakfast: {plan.get('meal_plan', {}).get('breakfast', '')}\n"
        f"  - Lunch: {plan.get('meal_plan', {}).get('lunch', '')}\n"
        f"  - Dinner: {plan.get('meal_plan', {}).get('dinner', '')}\n"
        f"  - Snacks: {plan.get('meal_plan', {}).get('snacks', '')}\n"
        f"- **Hydration:** {plan.get('hydration', '')}\n"
        f"- **Supplements:** {plan.get('supplements', '')}\n"
    )

def format_workout_plan(plan):
    if not plan:
        return "No workout plan available."
    schedule = plan.get("weekly_schedule", {})
    schedule_str = "\n".join(
        f"- **{day.capitalize()}:** {details}" for day, details in schedule.items()
    )
    return (
        f"### Workout Plan\n"
        f"{schedule_str}\n"
        f"- **Progression:** {plan.get('progression', '')}\n"
        f"- **Recovery:** {plan.get('recovery', '')}\n"
    )

def format_chat_response(message, response):
    return (
        f"**You:** {message}\n\n"
        f"**AI:** {response}\n"
    )