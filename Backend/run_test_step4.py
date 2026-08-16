"""
Run this to see the FULL chain, exactly the way the real pipeline will
run it later: Step 0 -> Step 1 -> Step 2 -> Step 4.

The point of this file is to make the data flow VISIBLE — notice that
every step's output is caught in a variable, then handed to the next
step as a plain argument. Nothing is pulled automatically; you (or
pipeline.py later) are always the one wiring outputs to inputs.

    python3 run_test_step4.py
"""

from dotenv import load_dotenv

load_dotenv()

from idea_agent import generate_titles
from plan_builder import build_plan
from content_generator import generate_content
from activities_generator import extract_lab_contexts, suggest_lab_types, generate_labs
from notebook_builder import save_all_lab_notebooks
from feedback_loop import review_loop

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

    # ---- Step 4a: find where the labs go, straight from Step 1's outline ----
    print("\nStep 4a: extracting lab slots from the outline...")
    lab_contexts = extract_lab_contexts(plan["outline"])
    print(f"  -> found {len(lab_contexts)} lab slot(s):")
    for ctx in lab_contexts:
        print(f"     {ctx}")

    # ---- Step 4b: ask the AI to suggest a type for each lab ----
    print("\nStep 4b: suggesting lab types (coding vs interactive_tool)...")
    suggestions = suggest_lab_types(chosen_title, lab_contexts)
    for s in suggestions["suggestions"]:
        print(f"     outline_index {s['outline_index']}: {s['lab_type']} — {s['reason']}")

    # ---- Simulating the trainer confirming (in the real UI, they'd click
    #      to accept/override each suggestion; here we just accept all) ----
    confirmed_lab_types = {s["outline_index"]: s["lab_type"] for s in suggestions["suggestions"]}

    # ---- Step 4c: generate the full labs, grounded in Step 2's real content ----
    print("\nStep 4c: generating the full labs (this calls the API once per lab)...")
    labs_result = generate_labs(
        title=chosen_title,
        lab_contexts=lab_contexts,
        confirmed_lab_types=confirmed_lab_types,
        content=content,  # <-- Step 2's output, passed in by hand, right here
        customization_notes="keep it beginner-friendly",
    )

    print("\n--- Generated labs (before review) ---")
    for lab in labs_result["labs"]:
        print(f"[{lab['lab_type']}] {lab['title']}")

    # ---- Review: let the trainer approve or give feedback in plain words.
    #      IMPORTANT: this must run BEFORE exporting .ipynb files below —
    #      otherwise the exported notebooks would be the pre-edit version. ----
    labs_result = review_loop(
        "Step 4: Labs",
        labs_result,
        "A set of workshop labs (coding notebooks and/or real interactive external tools), "
        "one per lab slot in the outline.",
    )

    print("\n--- Generated labs (final, after review) ---")
    for lab in labs_result["labs"]:
        print(f"\n[{lab['lab_type']}] {lab['title']}  (covers: {lab['covers_sections']}, {lab['duration_minutes']} min)")
        print(f"  instructions: {lab['instructions']}")
        if lab["lab_type"] == "coding":
            print(f"  trainee cells: {len(lab['trainee_notebook_cells'])}, solution cells: {len(lab['solution_notebook_cells'])}")
        else:
            print(f"  questions: {len(lab['questions'])}")
        print(f"  instructor notes: {lab['instructor_notes']}")
        for p in lab["suggested_platforms"]:
            print(f"  platform: {p['name']} — {p['url']}")

    # ---- Step 4d: automatically turn every "coding" lab's cells into
    #      real .ipynb files — the person never touches this step, it
    #      just runs right after generation ----
    print("\nStep 4d: writing .ipynb files for coding labs...")
    notebook_paths = save_all_lab_notebooks(labs_result, output_dir="generated_labs")
    if not notebook_paths:
        print("  (no coding labs in this run — nothing to write)")
    for entry in notebook_paths:
        print(f"  outline_index {entry['outline_index']}:")
        print(f"    trainee:  {entry['trainee_path']}")
        print(f"    solution: {entry['solution_path']}")
