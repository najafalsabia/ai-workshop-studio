"""
Step 7: the final quality checklist.

What it does, in plain English — reviews EVERYTHING together right before
export (plan + content + labs + quiz), not any one piece in isolation,
and returns a pass/fail verdict with specific issues to fix. This is the
last gate before Step 8 (PPTX export) and the final downloads.

Two layers, same defense-in-depth pattern used elsewhere in this project
(rebalance_outline, title_from_description, validate_quiz):

  1. run_automated_checks() — deterministic, code-only checks for things
     that don't need judgment: does every outline section have content?
     does every lab slot have a lab? does every quiz question have a
     valid correct_answer? These never rely on the model to notice them.

  2. One LLM call — for things that DO need judgment: does the content
     actually match the learning objectives? do the labs meaningfully
     practice what was taught? does the quiz test real understanding,
     not just recall? is the difficulty appropriate for the audience?

Automated issues always force a "fail" overall, regardless of what the
LLM concludes — a structural gap (e.g. a section with no content) is a
fact, not a judgment call, so it can't be argued away by the model.
"""

from llm_client import ask_llm_for_json
from activities_generator import group_slides_by_section, format_slide_blocks


def run_automated_checks(
    plan: dict,
    content: dict,
    labs_result: dict | None,
    quiz_result: dict | None,
) -> list[str]:
    """
    Deterministic, code-only checks — no LLM involved. Returns a list of
    plain-language issue strings (empty list = nothing objectively wrong).
    """
    issues = []
    outline = plan.get("outline", [])

    # --- Plan: every section has a name, duration, and description ---
    for i, section in enumerate(outline):
        if not section.get("section"):
            issues.append(f"Plan: outline section at index {i} has no name.")
        if not section.get("description"):
            issues.append(f"Plan: outline section '{section.get('section', f'#{i}')}' has no description.")

    total_minutes = sum(s.get("duration_minutes", 0) for s in outline)
    # duration_minutes is guaranteed exact by plan_builder's rebalance_outline,
    # but re-checking here means Step 7 doesn't silently trust an upstream
    # step that could have changed by the time this runs.
    if total_minutes <= 0:
        issues.append("Plan: outline has no duration at all (total is 0 minutes).")

    # --- Content: every non-break/qna/opening/closing section has slides ---
    slides = content.get("slides", []) if content else []
    if slides:
        by_section = group_slides_by_section(slides)
        skip_roles = {"break", "qna", "opening", "closing"}
        for section in outline:
            role = section.get("role")
            if role in skip_roles:
                continue
            name = section.get("section")
            if name not in by_section or not by_section[name]:
                issues.append(f"Content: no slides were generated for section '{name}'.")

    # --- Labs: every lab-role section has a matching generated lab ---
    if labs_result and labs_result.get("labs"):
        lab_role_indices = {i for i, s in enumerate(outline) if s.get("role") == "lab"}
        covered_indices = {lab.get("outline_index") for lab in labs_result.get("labs", [])}
        missing = lab_role_indices - covered_indices
        for i in missing:
            issues.append(f"Labs: outline section '{outline[i]['section']}' is a lab slot with no generated lab.")

        for lab in labs_result.get("labs", []):
            if lab.get("lab_type") == "coding":
                if not lab.get("trainee_notebook_cells") or not lab.get("solution_notebook_cells"):
                    issues.append(f"Labs: coding lab '{lab.get('title', '?')}' is missing notebook cells.")
            elif lab.get("lab_type") == "interactive_tool":
                if not lab.get("external_tool", {}).get("url"):
                    issues.append(f"Labs: interactive_tool lab '{lab.get('title', '?')}' has no external_tool URL.")

    # --- Quiz: every question has a correct_answer that matches an option ---
    if quiz_result and (quiz_result.get("quiz") or quiz_result.get("questions")):
        quiz_data = quiz_result.get("quiz", quiz_result)
        questions = quiz_data.get("questions", [])
        if not questions:
            issues.append("Quiz: no questions were generated.")
        for i, q in enumerate(questions):
            options = q.get("options", [])
            if len(options) != 4:
                issues.append(f"Quiz: question {i + 1} has {len(options)} options, expected exactly 4.")
            if q.get("correct_answer") not in options:
                issues.append(f"Quiz: question {i + 1}'s correct_answer doesn't match any of its options.")

    return issues


def summarize_plan(plan: dict) -> str:
    """Condensed, readable summary of the plan for the review prompt."""
    lines = ["Learning objectives:"]
    lines += [f"- {obj}" for obj in plan.get("learning_objectives", [])]
    lines.append("\nOutline:")
    for s in plan.get("outline", []):
        role = f" [{s['role']}]" if "role" in s else ""
        lines.append(f"- {s.get('section')}{role} ({s.get('duration_minutes')} min): {s.get('description')}")
    return "\n".join(lines)


def summarize_content(content: dict) -> str:
    """Condensed summary of the slide content — titles and block text per
    section, not the full slide JSON, to keep the review prompt a
    reasonable size."""
    by_section = group_slides_by_section(content.get("slides", []))
    parts = []
    for section_name, slides in by_section.items():
        parts.append(f"## {section_name}")
        for slide in slides:
            parts.append(f"- Slide \"{slide.get('slide_title', '')}\" ({slide.get('content_type', '?')})")
            block_text = format_slide_blocks(slide.get("blocks", []))
            if block_text:
                parts.append(block_text)
    return "\n".join(parts)


def summarize_labs(labs_result: dict | None) -> str:
    """Condensed summary of the labs — title, type, and instructions,
    not the full notebook cells or question sets."""
    if labs_result is None:
        return "(no labs generated for this workshop)"
    parts = []
    for lab in labs_result.get("labs", []):
        parts.append(
            f"- [{lab.get('lab_type')}] \"{lab.get('title')}\" — covers: {lab.get('covers_sections')}, "
            f"{lab.get('duration_minutes')} min\n  instructions: {lab.get('instructions')}"
        )
    return "\n".join(parts) if parts else "(no labs generated for this workshop)"


def summarize_quiz(quiz_result: dict | None) -> str:
    """Condensed summary of the quiz — every question's text and
    difficulty, not the full options/answers (kept short since quiz
    questions are short by design already)."""
    if quiz_result is None:
        return "(no quiz generated for this workshop)"
    questions = quiz_result.get("quiz", {}).get("questions", [])
    if not questions:
        return "(no quiz generated for this workshop)"
    return "\n".join(f"- [{q.get('difficulty')}] {q.get('question')}" for q in questions)


CHECKLIST_PROMPT_TEMPLATE = """You are doing a final quality review of a complete technical workshop \
package, right before it gets exported and used. Review the plan, content, labs, and quiz TOGETHER — \
not each piece alone — and judge whether they actually fit together as one coherent workshop.

Workshop title: {title}

=== PLAN ===
{plan_summary}

=== SLIDE CONTENT ===
{content_summary}

=== LABS ===
{labs_summary}

=== QUIZ ===
{quiz_summary}

=== AUTOMATED STRUCTURAL CHECKS (already run in code — these are FACTS, not your judgment) ===
{automated_issues_text}

Now do the judgment-based review these automated checks CAN'T do. For each category, decide pass or \
fail and list specific issues (empty list if none):

1. "plan": Are the learning objectives specific and measurable? Does the outline's time allocation \
make sense for the content depth?
2. "content": Does the slide content actually support the learning objectives? Is anything shallow, \
generic, or clearly ungrounded in real information?
3. "labs": Do the labs genuinely practice what was just taught (not something unrelated)? Is the \
difficulty appropriate for the stated audience?
4. "quiz": Do the questions test real understanding of what was actually taught (not generic trivia)? \
Is the difficulty spread reasonable?
5. "cross_consistency": Do the plan, content, labs, and quiz all agree on the same topics and \
terminology — or does any part feel like it belongs to a different workshop?

Reply with ONLY this JSON, nothing else:
{{
  "checks": [
    {{"category": "plan", "status": "pass" or "fail", "issues": ["..."]}},
    {{"category": "content", "status": "pass" or "fail", "issues": ["..."]}},
    {{"category": "labs", "status": "pass" or "fail", "issues": ["..."]}},
    {{"category": "quiz", "status": "pass" or "fail", "issues": ["..."]}},
    {{"category": "cross_consistency", "status": "pass" or "fail", "issues": ["..."]}}
  ],
  "summary": "one short paragraph on the overall state of the workshop package"
}}
"""


def run_quality_checklist(
    title: str,
    plan: dict,
    content: dict,
    labs_result: dict | None = None,
    quiz_result: dict | None = None,
) -> dict:
    """
    The function the rest of the app calls for Step 7. Give it everything
    generated so far — the plan, content, and optionally labs/quiz (pass
    None for whichever wasn't generated for this workshop) — get back:

        {
          "overall_status": "pass" | "fail",
          "checks": [{"category": ..., "status": ..., "issues": [...]}],
          "automated_issues": [...],   # structural facts, checked in code
          "summary": "..."
        }

    overall_status is "fail" if EITHER the automated checks found
    anything OR the LLM marked any category "fail" — a workshop only
    passes if both the objective structure and the judgment-based review
    are clean.
    """
    automated_issues = run_automated_checks(plan, content, labs_result, quiz_result)
    automated_issues_text = "\n".join(f"- {issue}" for issue in automated_issues) or "(none found)"

    prompt = CHECKLIST_PROMPT_TEMPLATE.format(
        title=title,
        plan_summary=summarize_plan(plan),
        content_summary=summarize_content(content),
        labs_summary=summarize_labs(labs_result),
        quiz_summary=summarize_quiz(quiz_result),
        automated_issues_text=automated_issues_text,
    )
    result = ask_llm_for_json(prompt)

    llm_failed = any(check.get("status") == "fail" for check in result.get("checks", []))
    result["automated_issues"] = automated_issues
    result["overall_status"] = "fail" if (automated_issues or llm_failed) else "pass"

    return result


if __name__ == "__main__":
    # Self-tests — run_automated_checks needs no API keys (pure Python).
    # run_quality_checklist's LLM call is mocked here just to prove the
    # merging logic (automated + LLM verdict -> overall_status) is
    # correct; testing actual review quality against the real Gemini API
    # is a separate, manual step.

    print("=== Test 1: run_automated_checks — a CLEAN package (no issues expected) ===")
    good_plan = {
        "learning_objectives": ["Build an agent", "Debug an agent"],
        "outline": [
            {"section": "Welcome", "duration_minutes": 10, "role": "opening", "description": "Intro"},
            {"section": "Agent Basics", "duration_minutes": 30, "role": "explain", "description": "Core concepts"},
            {"section": "Build Your First Agent", "duration_minutes": 20, "role": "lab", "description": "Hands-on"},
        ],
    }
    good_content = {
        "slides": [
            {"section": "Welcome", "slide_title": "Hi", "content_type": "content_slide", "blocks": []},
            {"section": "Agent Basics", "slide_title": "What is an Agent", "content_type": "content_slide", "blocks": []},
            {"section": "Build Your First Agent", "slide_title": "Lab Time", "content_type": "content_slide", "blocks": []},
        ]
    }
    good_labs = {
        "labs": [
            {
                "outline_index": 2, "lab_type": "coding", "title": "Build an Agent",
                "trainee_notebook_cells": [{"cell_type": "code", "content": "..."}],
                "solution_notebook_cells": [{"cell_type": "code", "content": "..."}],
            }
        ]
    }
    good_quiz = {
        "quiz": {
            "questions": [
                {"question": "Q1", "options": ["a", "b", "c", "d"], "correct_answer": "a", "difficulty": "easy"},
            ]
        }
    }
    issues = run_automated_checks(good_plan, good_content, good_labs, good_quiz)
    print("issues found:", issues)
    assert issues == [], f"Expected no issues, got {issues}"

    print("\n=== Test 2: run_automated_checks — a BROKEN package (issues expected) ===")
    broken_content = {"slides": [{"section": "Welcome", "slide_title": "Hi", "content_type": "content_slide", "blocks": []}]}
    # "Agent Basics" has no slides at all
    broken_labs = {"labs": []}  # the lab-role section has no generated lab
    broken_quiz = {"quiz": {"questions": [{"question": "Q1", "options": ["a", "b"], "correct_answer": "z", "difficulty": "easy"}]}}
    issues2 = run_automated_checks(good_plan, broken_content, broken_labs, broken_quiz)
    print("issues found:")
    for i in issues2:
        print(" -", i)
    assert any("Agent Basics" in i for i in issues2), "should catch the missing-content section"
    assert any("Build Your First Agent" in i for i in issues2), "should catch the missing lab"
    assert any("options" in i for i in issues2), "should catch the wrong option count"
    assert any("correct_answer" in i for i in issues2), "should catch the mismatched correct_answer"

    print("\n=== Test 3: run_quality_checklist — automated issues force overall FAIL even if LLM says pass ===")
    import quality_checklist as qc

    def fake_ask_llm_for_json_all_pass(prompt):
        return {
            "checks": [
                {"category": "plan", "status": "pass", "issues": []},
                {"category": "content", "status": "pass", "issues": []},
                {"category": "labs", "status": "pass", "issues": []},
                {"category": "quiz", "status": "pass", "issues": []},
                {"category": "cross_consistency", "status": "pass", "issues": []},
            ],
            "summary": "Looks fine.",
        }

    qc.ask_llm_for_json = fake_ask_llm_for_json_all_pass
    result = qc.run_quality_checklist("Test Workshop", good_plan, broken_content, broken_labs, broken_quiz)
    print("overall_status:", result["overall_status"], "(expect 'fail' — automated issues exist)")
    assert result["overall_status"] == "fail"
    assert len(result["automated_issues"]) > 0

    print("\n=== Test 4: run_quality_checklist — clean automated checks, but LLM finds a judgment issue ===")
    def fake_ask_llm_for_json_one_fail(prompt):
        return {
            "checks": [
                {"category": "plan", "status": "pass", "issues": []},
                {"category": "content", "status": "fail", "issues": ["Slide content is too generic."]},
                {"category": "labs", "status": "pass", "issues": []},
                {"category": "quiz", "status": "pass", "issues": []},
                {"category": "cross_consistency", "status": "pass", "issues": []},
            ],
            "summary": "Content needs work.",
        }

    qc.ask_llm_for_json = fake_ask_llm_for_json_one_fail
    result2 = qc.run_quality_checklist("Test Workshop", good_plan, good_content, good_labs, good_quiz)
    print("overall_status:", result2["overall_status"], "(expect 'fail' — LLM flagged content)")
    assert result2["overall_status"] == "fail"
    assert result2["automated_issues"] == []

    print("\n=== Test 5: run_quality_checklist — everything clean -> overall PASS ===")
    qc.ask_llm_for_json = fake_ask_llm_for_json_all_pass
    result3 = qc.run_quality_checklist("Test Workshop", good_plan, good_content, good_labs, good_quiz)
    print("overall_status:", result3["overall_status"], "(expect 'pass')")
    assert result3["overall_status"] == "pass"

    print("\nAll self-tests passed.")