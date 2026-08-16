"""
Shared human-in-the-loop helper, used after every generation step (Step 0,
1, 2, and later 4, 5...). After a step produces output, this shows it to
the user and lets them approve it or give feedback. On feedback, it asks
the AI to revise the SAME output (not start over), and loops until the
user approves or a round limit is hit.

This is deliberately a standalone helper, not something wired into
idea_agent.py / plan_builder.py / content_generator.py themselves — each
step keeps generating output exactly as it does now. Whoever calls a step
(a run_test_*.py script today, the real pipeline later) just wraps the
result in review_loop() afterward. No existing step file needs to change.

Right now feedback is collected via the terminal (input()), which is
enough for testing steps in isolation. Once the UI's approve/feedback
screen exists (Day 4), only the small "ask the user" part here gets
swapped out — review_loop's revision logic stays the same either way.
"""

import json

from llm_client import ask_llm_for_json

REVISION_PROMPT_TEMPLATE = """You previously produced this JSON output:
{previous_output}

Context on what this output is for:
{context_description}

The user reviewed it and gave this feedback:
"{feedback}"

Revise the output to address the feedback. Keep the EXACT same JSON
structure as before — same fields, same nesting — only change the
content based on the feedback. Don't add, remove, or rename fields.

Reply with ONLY the revised JSON, nothing else.
"""


def build_revision_prompt(previous_output: dict, feedback: str, context_description: str) -> str:
    """Builds a prompt asking the AI to fix one thing — the feedback —
    while preserving everything else and the output's exact shape."""
    return REVISION_PROMPT_TEMPLATE.format(
        previous_output=json.dumps(previous_output, indent=2, ensure_ascii=False),
        feedback=feedback,
        context_description=context_description,
    )


def review_loop(
    step_name: str,
    output: dict,
    context_description: str,
    max_rounds: int = 10,
) -> dict:
    """
    Shows `output` to the user, asks for approval or feedback, and loops:
    each round of feedback re-asks the AI to revise `output` (not
    regenerate from scratch), capped at max_rounds (10 by default) so an
    unclear request can't loop forever. Returns the final approved (or
    last revised) output either way.

    Usage — one line after any step's generate/build call:
        titles = generate_titles(**user_input)
        titles = review_loop("Step 0: Titles", titles, "5 workshop title suggestions")
    """
    current = output

    for round_num in range(max_rounds):
        print(f"\n--- {step_name} — review round {round_num + 1} ---")
        print(json.dumps(current, indent=2, ensure_ascii=False))
        answer = input("\nApprove this? (Enter/y = yes, or type your feedback): ").strip()

        if answer == "" or answer.lower() in ("y", "yes"):
            print(f"✅ {step_name} approved.")
            return current

        print(f"Applying feedback: \"{answer}\"...")
        revision_prompt = build_revision_prompt(current, answer, context_description)
        current = ask_llm_for_json(revision_prompt)

    print(f"⚠️  Reached {max_rounds} feedback rounds without approval — moving on with the latest version.")
    return current

def revise_single_slide(slide: dict, feedback: str) -> dict:
    """
    Asks the LLM to revise a single slide JSON dictionary based on custom feedback,
    while keeping the slide's schema and number unchanged.
    """
    prompt = f"""You previously generated this slide JSON:
{json.dumps(slide, indent=2, ensure_ascii=False)}

The user reviewed it and gave this feedback for this specific slide:
"{feedback}"

Revise the slide to address the feedback. Keep the EXACT same JSON structure:
- slide_number (integer)
- section (string)
- slide_title (string)
- content_type (string)
- blocks (list of block objects with type, text/items, position, source)
- source (source object with author, title, url, accessed_date)
- speaker_notes (string)

Reply with ONLY the revised JSON, nothing else."""

    return ask_llm_for_json(prompt)