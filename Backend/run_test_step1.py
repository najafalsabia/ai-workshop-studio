"""
Run this to test Step 0 -> Step 1 chained together, the way they'll
actually run in the real app: generate titles, pick one, build a plan
from it.

    python3 run_test_step1.py
"""

import time
from dotenv import load_dotenv

load_dotenv()

from idea_agent import generate_titles
from plan_builder import build_plan

if __name__ == "__main__":
    user_input = dict(
        audience="university computer science students",
        age="18-24",
        duration="4.5 hours",
        goal="teach practical use of AI coding assistants",
        notes="should feel hands-on, not just slides",
    )

    print("Generating title suggestions...")
    titles_result = generate_titles(**user_input)
    chosen_title = titles_result["titles"][0]["title"]
    print(f"\n(Simulating user picking the first suggestion: '{chosen_title}')")

    time.sleep(4)  # small gap before the next LLM call, same reasoning as before

    print("\nBuilding the plan...")
    plan = build_plan(title=chosen_title, **user_input)

    print("\n--- Learning objectives ---")
    for obj in plan.get("learning_objectives", []):
        print(f"• {obj}")

    print("\n--- Outline ---")
    for section in plan.get("outline", []):
        print(f"\n[{section['duration_minutes']} min] {section['section']}")
        print(f"  {section['description']}")
