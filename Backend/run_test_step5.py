"""
Run this to see the FULL chain for the quiz: Step 0 -> Step 1 -> Step 2 ->
Step 5. Same idea as run_test_step4.py — every step's output is caught in
a variable, then handed to the next step by hand. Nothing pulled
automatically.

    python3 run_test_step5.py
"""

from dotenv import load_dotenv

load_dotenv()

from idea_agent import generate_titles
from plan_builder import build_plan
from content_generator import generate_content
from quiz_generator import generate_quiz
from feedback_loop import review_loop
from quiz_doc_builder import save_quiz_docx

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
    content = generate_content(
        title=chosen_title,
        learning_objectives=plan["learning_objectives"],
        outline=plan["outline"],
    )
    print(f"  -> content generated for {len(content['content'])} sections")

    # ---- Step 5: one comprehensive end-of-workshop quiz ----
    print("\nStep 5: generating the quiz (one API call)...")
    quiz_result = generate_quiz(
        title=chosen_title,
        outline=plan["outline"],  # <-- Step 1's outline, passed in by hand
        content=content,          # <-- Step 2's content, passed in by hand, right here
    )

    # ---- Review: let the trainer approve or give feedback in plain words ----
    quiz_result = review_loop(
        "Step 5: Quiz",
        quiz_result,
        "A comprehensive end-of-workshop quiz: multiple-choice questions "
        "split evenly across easy/medium/hard difficulty.",
    )

    quiz = quiz_result["quiz"]
    print(f"\n--- {quiz['title']} ({len(quiz['questions'])} questions) ---")
    for i, q in enumerate(quiz["questions"], start=1):
        print(f"\n{i}. [{q['difficulty']}] {q['question']}")
        for opt in q["options"]:
            marker = "✓" if opt == q["correct_answer"] else " "
            print(f"   [{marker}] {opt}")

    # ---- Export: automatic .docx, runs AFTER review so it reflects the
    #      final (possibly edited) version, not the pre-review draft ----
    print("\nWriting quiz.docx...")
    docx_path = save_quiz_docx(quiz_result, output_path="quiz.docx")
    print(f"  -> saved to: {docx_path}")
