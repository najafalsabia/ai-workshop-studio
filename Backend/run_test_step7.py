"""
Run this to see the FULL chain, all the way through Step 7: Step 0 ->
Step 1 -> Step 2 -> Step 4 -> Step 5 -> Step 7 (the final quality
checklist, reviewing the plan + content + labs + quiz TOGETHER).

Same idea as run_test_step4.py / run_test_step5.py — every step's output
is caught in a variable, then handed to the next step by hand. Nothing
pulled automatically.

    python3 run_test_step7.py
"""

from dotenv import load_dotenv

load_dotenv()

from idea_agent import generate_titles
from plan_builder import build_plan
from content_generator import generate_content_with_sources
from activities_generator import extract_lab_contexts, suggest_lab_types, generate_labs
from quiz_generator import generate_quiz
from feedback_loop import review_loop
from quality_checklist import run_quality_checklist

if __name__ == "__main__":
    user_input = dict(
        audience="university computer science students",
        age="18-24",
        duration="3 hours",
        goal="teach practical use of AI coding assistants",
        notes="should feel hands-on, not just slides",
    )

    # ---- Step 0: title suggestions ----
    print("Step 0: generating title suggestions...")
    titles_result = generate_titles(**user_input)
    chosen_title = titles_result["titles"][0]["title"]
    print(f"  -> chosen title: {chosen_title}")

    # ---- Step 1: plan (using the explain/lab/break cycle) ----
    print("\nStep 1: building the plan...")
    plan = build_plan(
        title=chosen_title,
        **user_input,
        use_lab_cycle=True,
        explain_minutes=30,
        lab_minutes=20,
        break_minutes=10,
    )
    print(f"  -> outline has {len(plan['outline'])} sections")

    # ---- Step 2: full slide content, built from Step 1's outline ----
    print("\nStep 2: generating content...")
    content = generate_content_with_sources(
        title=chosen_title,
        learning_objectives=plan["learning_objectives"],
        outline=plan["outline"],
    )
    print(f"  -> {len(content['slides'])} slides generated")

    # ---- Step 4: labs, grounded in Step 2's real content ----
    print("\nStep 4: generating labs...")
    lab_contexts = extract_lab_contexts(plan["outline"])
    suggestions = suggest_lab_types(chosen_title, lab_contexts)
    confirmed_lab_types = {s["outline_index"]: s["lab_type"] for s in suggestions["suggestions"]}
    labs_result = generate_labs(
        title=chosen_title,
        lab_contexts=lab_contexts,
        confirmed_lab_types=confirmed_lab_types,
        content=content,
        customization_notes="keep it beginner-friendly",
    )
    print(f"  -> {len(labs_result['labs'])} labs generated")

    # ---- Step 5: one comprehensive end-of-workshop quiz ----
    print("\nStep 5: generating the quiz...")
    quiz_result = generate_quiz(
        title=chosen_title,
        outline=plan["outline"],
        content=content,
    )
    print(f"  -> {len(quiz_result['quiz']['questions'])} quiz questions generated")

    # ---- Review: trainer approves or gives feedback before the final check ----
    labs_result = review_loop(
        "Step 4: Labs", labs_result,
        "A set of workshop labs, one per lab slot in the outline.",
    )
    quiz_result = review_loop(
        "Step 5: Quiz", quiz_result,
        "A comprehensive end-of-workshop quiz, tiered difficulty.",
    )

    # ---- Step 7: final quality checklist — reviews EVERYTHING together ----
    print("\nStep 7: running the final quality checklist...")
    checklist_result = run_quality_checklist(
        title=chosen_title,
        plan=plan,
        content=content,
        labs_result=labs_result,
        quiz_result=quiz_result,
    )

    print(f"\n=== OVERALL STATUS: {checklist_result['overall_status'].upper()} ===")

    if checklist_result["automated_issues"]:
        print("\n--- Automated structural issues (code-checked facts) ---")
        for issue in checklist_result["automated_issues"]:
            print(f"  ⚠️  {issue}")
    else:
        print("\n(no automated structural issues found)")

    print("\n--- Judgment-based review ---")
    for check in checklist_result["checks"]:
        status_icon = "✅" if check["status"] == "pass" else "❌"
        print(f"\n{status_icon} {check['category']}: {check['status']}")
        for issue in check.get("issues", []):
            print(f"    - {issue}")

    print(f"\n--- Summary ---\n{checklist_result['summary']}")