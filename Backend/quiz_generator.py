"""
Step 5: the quiz generator.

What it does, in plain English:
  1. Looks at the outline and figures out how many quiz questions fit —
     scaled to how much actual teaching time the workshop has (a longer
     workshop gets more questions, a short one gets fewer), not a fixed
     number.
  2. Picks only the TEACHING content to quiz on — if the outline has
     role tags (from plan_builder's explain/lab/break cycle), only
     "explain" sections count; labs, breaks, Q&A, etc. aren't quizzable
     content. If there are no role tags (freeform outline), every
     section counts.
  3. Writes ONE comprehensive multiple-choice quiz for the end of the
     workshop, covering everything taught, split into three EQUAL
     difficulty tiers (easy / medium / hard) — not a per-section quiz,
     one quiz for the whole session.

Like activities_generator.py, this is deliberately decoupled from
plan_builder.py and content_generator.py — it only reads a plain
"outline: list[dict]" and an optional "content" (any shape
normalize_content_for_sections already understands: Step 2's slide
blocks, a simple {section: text} dict, or nothing at all).
"""

import json
import copy

from llm_client import ask_llm_for_json
from activities_generator import normalize_content_for_sections
from config import (
    QUIZ_MINUTES_PER_QUESTION as MINUTES_PER_QUESTION,
    QUIZ_MIN_QUESTIONS as MIN_QUESTIONS,
    QUIZ_MAX_QUESTIONS as MAX_QUESTIONS,
)


def get_teaching_section_names(outline: list[dict]) -> list[str]:
    """
    Returns just the section names worth quizzing on:
      - role-based outline -> only sections with role == "explain"
        (labs, breaks, opening, qna, competition, closing are skipped —
        nothing to quiz there).
      - freeform outline (no role tags) -> every section, since there's
        no way to tell teaching content from anything else.
    """
    has_roles = any("role" in section for section in outline)
    if has_roles:
        return [section["section"] for section in outline if section.get("role") == "explain"]
    return [section["section"] for section in outline]


def compute_question_count(
    outline: list[dict],
    minutes_per_question: int = MINUTES_PER_QUESTION,
    min_questions: int = MIN_QUESTIONS,
    max_questions: int = MAX_QUESTIONS,
) -> int:
    """
    Scales the quiz length to actual teaching time (only "explain"
    sections if role tags exist, otherwise the whole outline) — a longer
    workshop gets more questions. Always rounds to the nearest multiple
    of 3 so the three difficulty tiers split perfectly evenly, then
    clamps between min_questions and max_questions (both multiples of 3
    by default, so the clamp never breaks the even split).
    """
    has_roles = any("role" in section for section in outline)
    if has_roles:
        teaching_minutes = sum(
            section["duration_minutes"] for section in outline if section.get("role") == "explain"
        )
    else:
        teaching_minutes = sum(section.get("duration_minutes", 0) for section in outline)

    if teaching_minutes <= 0:
        return min_questions

    raw = teaching_minutes / minutes_per_question
    rounded_to_3 = max(3, round(raw / 3) * 3)
    return min(max(rounded_to_3, min_questions), max_questions)


QUIZ_PROMPT_TEMPLATE = """You are writing a single comprehensive quiz for the END of a technical \
workshop, covering everything taught across the whole session — this is NOT a per-section quiz, \
it's one quiz that closes out the workshop.

Workshop title: {title}

Content taught across the workshop (use this to write specific, grounded questions tied to what \
was actually covered — never generic trivia unrelated to this content):
{content_text}

CRITICAL STIPULATIONS:
1. You must write EXACTLY {question_count} multiple-choice questions in total.
2. The questions must be split into EXACTLY THREE equal difficulty tiers, containing EXACTLY {per_tier} questions in each tier:
   - EXACTLY {per_tier} "easy" questions (straightforward recall/definition-level)
   - EXACTLY {per_tier} "medium" questions (requires applying a concept, not just recalling it)
   - EXACTLY {per_tier} "hard" questions (combines multiple concepts, or requires debugging/spotting a subtle mistake)
3. EVERY single question must be completely unique, distinct, and cover different subtopics. Do NOT repeat or duplicate the same question topic or structure in different tiers.
4. Each question needs EXACTLY 4 options, with exactly ONE correct answer. The "correct_answer" value must match one of the "options" EXACTLY, character for character.

Reply with ONLY this JSON, nothing else:
{{
  "quiz": {{
    "title": "...",
    "questions": [
      {{"question": "...", "options": ["...", "...", "...", "..."], "correct_answer": "...", "difficulty": "easy"}}
    ]
  }}
}}
"""


def validate_quiz(quiz: dict, expected_count: int, expected_per_tier: int) -> None:
    """
    Sanity-checks a generated quiz and prints warnings for anything off —
    doesn't raise, since a mostly-good quiz is still usable and can go
    through feedback_loop.review_loop for a fix, same as other steps'
    soft-warning pattern (see content_generator's missing-section check).
    Catches the two failure modes that would actually break the quiz UI:
    a correct_answer that doesn't match any option, and a tier split
    that isn't actually even.
    """
    questions = quiz.get("quiz", {}).get("questions", [])
    if len(questions) != expected_count:
        print(f"⚠️  Expected {expected_count} questions, got {len(questions)}.")

    tier_counts = {"easy": 0, "medium": 0, "hard": 0}
    for i, q in enumerate(questions):
        options = q.get("options", [])
        correct = q.get("correct_answer")
        if correct not in options:
            preview = (q.get("question", "") or "")[:50]
            print(f"⚠️  Question {i + 1} ('{preview}...'): correct_answer doesn't match any option.")
        difficulty = q.get("difficulty")
        if difficulty in tier_counts:
            tier_counts[difficulty] += 1
        else:
            print(f"⚠️  Question {i + 1}: unexpected difficulty value {difficulty!r}.")

    for tier, count in tier_counts.items():
        if count != expected_per_tier:
            print(f"⚠️  Expected {expected_per_tier} '{tier}' questions, got {count}.")


def generate_quiz(
    title: str,
    outline: list,
    content=None,
    minutes_per_question: int = MINUTES_PER_QUESTION,
    min_questions: int = MIN_QUESTIONS,
    max_questions: int = MAX_QUESTIONS,
    extra_context: str = "",
    question_count: int | None = None,
) -> dict:
    """
    The function the rest of the app calls. Give it the workshop title
    plus the outline (Step 1's, or a hand-built one in the same shape),
    optionally the content (Step 2's, a simple {section: text} dict, or
    nothing), get back {"quiz": {"title": ..., "questions": [...]}} —
    one comprehensive quiz, tiered difficulty.

    extra_context: raw text (e.g. uploaded content) used when outline is empty.

    question_count: if given, the trainer's own choice OVERRIDES the
    duration-based auto-scaling entirely — the quiz will have exactly
    this many questions (rounded to the nearest multiple of 3, minimum
    3, so the three difficulty tiers still split evenly). Leave as None
    to keep the automatic "scaled to teaching time" behavior.
    """
    outline = outline or []

    if question_count is not None:
        # Trainer-chosen count wins outright — skip duration-based scaling.
        question_count = max(3, round(question_count / 3) * 3)
        per_tier = question_count // 3
        if extra_context and not outline:
            content_text = extra_context[:4000]
        else:
            section_names = get_teaching_section_names(outline)
            content_text = normalize_content_for_sections(section_names, content)
            if extra_context:
                content_text = content_text + "\n\n" + extra_context[:2000]
    elif extra_context and not outline:
        # Content-only mode: use the uploaded content directly as quiz material
        question_count = min_questions  # default to min when no outline timing available
        per_tier = question_count // 3
        content_text = extra_context[:4000]
    else:
        question_count = compute_question_count(outline, minutes_per_question, min_questions, max_questions)
        per_tier = question_count // 3
        section_names = get_teaching_section_names(outline)
        content_text = normalize_content_for_sections(section_names, content)
        if extra_context:
            content_text = content_text + "\n\n" + extra_context[:2000]

    prompt = QUIZ_PROMPT_TEMPLATE.format(
        title=title,
        content_text=content_text,
        question_count=question_count,
        per_tier=per_tier,
    )
    quiz = ask_llm_for_json(prompt)
    
    # Programmatic deduplication and difficulty split enforcement
    if quiz and "quiz" in quiz and "questions" in quiz["quiz"]:
        raw_questions = quiz["quiz"]["questions"]
        seen_questions = set()
        unique_questions = []
        for q in raw_questions:
            q_text_norm = "".join(q.get("question", "").lower().split())
            if q_text_norm and q_text_norm not in seen_questions:
                seen_questions.add(q_text_norm)
                unique_questions.append(q)
        
        # Enforce exact even split across three tiers (easy, medium, hard)
        num_q = len(unique_questions)
        if num_q > 0:
            actual_per_tier = num_q // 3
            for idx, q in enumerate(unique_questions):
                if idx < actual_per_tier:
                    q["difficulty"] = "easy"
                elif idx < 2 * actual_per_tier:
                    q["difficulty"] = "medium"
                else:
                    q["difficulty"] = "hard"
            quiz["quiz"]["questions"] = unique_questions
            validate_quiz(quiz, question_count, per_tier)
            
    return quiz


EDIT_QUESTION_PROMPT_TEMPLATE = """You are revising ONE question from an already-finished workshop quiz, \
based on specific feedback from the trainer. Do NOT change anything else — only this question.

Original question (JSON):
{original_question}

Trainer's feedback on this question: "{feedback}"

Keep the same difficulty tier ("{difficulty}") unless the feedback explicitly asks to change the \
difficulty. Keep exactly 4 options, with exactly one correct answer that matches one of the \
options EXACTLY, character for character.

Reply with ONLY this JSON, nothing else:
{{"question": "...", "options": ["...", "...", "...", "..."], "correct_answer": "...", "difficulty": "..."}}
"""


def edit_quiz_question(quiz_result: dict, question_index: int, feedback: str) -> dict:
    """
    Revises ONE question in an existing quiz using plain-language feedback
    (e.g. "make this easier", "the wording is confusing", "change the
    correct answer to B") — every other question is left byte-for-byte
    untouched. Returns a NEW quiz_result (the original dict is not mutated).

    This is more surgical than routing a one-question tweak through
    feedback_loop.review_loop, which resends — and risks quietly
    perturbing — the WHOLE quiz just to fix a single question.

    Raises ValueError (nothing is written) if question_index is out of
    range, or if the model's revision doesn't have exactly 4 options with
    a correct_answer matching one of them — a malformed reply should
    never silently corrupt an otherwise-fine quiz.
    """
    questions = quiz_result.get("quiz", {}).get("questions", [])
    if not (0 <= question_index < len(questions)):
        raise ValueError(
            f"question_index {question_index} is out of range — this quiz has "
            f"{len(questions)} question(s) (valid indices: 0-{len(questions) - 1})."
        )

    original = questions[question_index]
    prompt = EDIT_QUESTION_PROMPT_TEMPLATE.format(
        original_question=json.dumps(original, ensure_ascii=False, indent=2),
        feedback=feedback,
        difficulty=original.get("difficulty", "medium"),
    )
    revised_question = ask_llm_for_json(prompt)

    options = revised_question.get("options", [])
    if len(options) != 4:
        raise ValueError(f"Revised question has {len(options)} options, expected exactly 4.")
    if revised_question.get("correct_answer") not in options:
        raise ValueError("Revised question's correct_answer doesn't match any of its options.")

    new_quiz_result = copy.deepcopy(quiz_result)
    new_quiz_result["quiz"]["questions"][question_index] = revised_question
    return new_quiz_result


if __name__ == "__main__":
    # Self-tests — compute_question_count/get_teaching_section_names/validate_quiz
    # need no API keys (pure Python). generate_quiz is mocked (no real network)
    # just to prove the plumbing is correct; testing actual prompt quality
    # against the real Gemini API is a separate, manual step.

    print("=== Test 1: compute_question_count — role-based outline ===")
    role_based_outline = [
        {"section": "Welcome", "duration_minutes": 10, "role": "opening"},
        {"section": "Prompting Basics", "duration_minutes": 30, "role": "explain"},
        {"section": "Write Your First Prompt", "duration_minutes": 20, "role": "lab"},
        {"section": "Break", "duration_minutes": 15, "role": "break"},
        {"section": "RAG Fundamentals", "duration_minutes": 30, "role": "explain"},
        {"section": "Build a Mini RAG Pipeline", "duration_minutes": 20, "role": "lab"},
        {"section": "Break", "duration_minutes": 15, "role": "break"},
        {"section": "Wrap-up Q&A", "duration_minutes": 15, "role": "qna"},
    ]
    # 60 teaching minutes (30+30) / 15 = 4 -> nearest multiple of 3 = 3, clamped to MIN_QUESTIONS=6
    count = compute_question_count(role_based_outline)
    print(f"teaching minutes = 60 -> question_count = {count} (expect 6, the floor)")
    assert count == 6 and count % 3 == 0

    print("\n=== Test 2: get_teaching_section_names — role-based (only 'explain') ===")
    names = get_teaching_section_names(role_based_outline)
    print(names)
    assert names == ["Prompting Basics", "RAG Fundamentals"]

    print("\n=== Test 3: compute_question_count — freeform outline (no roles) ===")
    freeform_outline = [
        {"section": "Intro to LLMs", "duration_minutes": 60, "description": "..."},
        {"section": "Tokenization", "duration_minutes": 60, "description": "..."},
        {"section": "Embeddings", "duration_minutes": 60, "description": "..."},
        {"section": "Vector Search", "duration_minutes": 60, "description": "..."},
    ]
    # 240 min / 15 = 16 -> nearest multiple of 3 = 15
    count2 = compute_question_count(freeform_outline)
    print(f"teaching minutes = 240 -> question_count = {count2} (expect 15)")
    assert count2 == 15 and count2 % 3 == 0

    print("\n=== Test 4: compute_question_count — clamps to MAX_QUESTIONS ===")
    huge_outline = [{"section": "Everything", "duration_minutes": 100000, "description": "..."}]
    count3 = compute_question_count(huge_outline)
    print(f"question_count = {count3} (expect {MAX_QUESTIONS})")
    assert count3 == MAX_QUESTIONS

    print("\n=== Test 5: get_teaching_section_names — freeform (no roles, uses all) ===")
    print(get_teaching_section_names(freeform_outline))
    assert get_teaching_section_names(freeform_outline) == [
        "Intro to LLMs", "Tokenization", "Embeddings", "Vector Search"
    ]

    print("\n=== Test 6: validate_quiz — a GOOD quiz (no warnings expected) ===")
    good_quiz = {
        "quiz": {
            "title": "Final Quiz",
            "questions": (
                [{"question": f"E{i}", "options": ["a", "b", "c", "d"], "correct_answer": "a", "difficulty": "easy"} for i in range(2)]
                + [{"question": f"M{i}", "options": ["a", "b", "c", "d"], "correct_answer": "b", "difficulty": "medium"} for i in range(2)]
                + [{"question": f"H{i}", "options": ["a", "b", "c", "d"], "correct_answer": "c", "difficulty": "hard"} for i in range(2)]
            ),
        }
    }
    validate_quiz(good_quiz, expected_count=6, expected_per_tier=2)
    print("(no warnings above = correct)")

    print("\n=== Test 7: validate_quiz — a BROKEN quiz (should print warnings, not crash) ===")
    broken_quiz = {
        "quiz": {
            "title": "Final Quiz",
            "questions": [
                {"question": "Bad Q", "options": ["a", "b", "c", "d"], "correct_answer": "z", "difficulty": "easy"},
                {"question": "Weird difficulty", "options": ["a", "b", "c", "d"], "correct_answer": "a", "difficulty": "impossible"},
            ],
        }
    }
    validate_quiz(broken_quiz, expected_count=6, expected_per_tier=2)

    print("\n=== Test 8: generate_quiz plumbing (mocked LLM, no real network) ===")
    import quiz_generator as qg

    def fake_ask_llm_for_json(prompt):
        return good_quiz

    qg.ask_llm_for_json = fake_ask_llm_for_json
    result = qg.generate_quiz("AI Coding Assistants Workshop", role_based_outline)
    print(f"got {len(result['quiz']['questions'])} questions back, title = {result['quiz']['title']!r}")
    assert len(result["quiz"]["questions"]) == 6

    print("\nAll self-tests passed.")
