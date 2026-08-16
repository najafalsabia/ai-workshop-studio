"""
Step 1: the plan builder.

What it does, in plain English:
  1. Takes the title the user picked from Step 0's suggestions.
  2. Does ONE focused search on that specific title (sharper than Step 0's
     broader search, since now we know exactly what the workshop is).
  3. Asks the AI to turn that into a full plan: learning objectives + an
     outline with timed sections.

Unlike idea_agent.py, this is NOT a loop/agent — it's search once, then
generate once. That's intentional: by this point the user has already
committed to a title, so there's no "is this enough info?" decision left
to make. Simpler code, same pattern as before.
"""

import re

from search_tool import search_web
from llm_client import ask_llm_for_json
from idea_agent import format_results  # reusing the helper from Step 0

PLAN_PROMPT_TEMPLATE = """You are building a detailed plan for a technical workshop.

Workshop title: {title}

Context on the workshop:
- Audience: {audience}
- Age: {age}
- Duration: {duration} (== {duration_minutes} minutes total)
- Goal: {goal}
- Extra notes: {notes}

Recent, relevant web research on this specific topic:
{search_results}

Build a workshop plan grounded in this research. Include:
1. 3-5 clear learning objectives (what attendees should be able to DO by the end)
2. An outline broken into timed sections. Each section needs a name, a
   duration in minutes, and a one-sentence description. The duration_minutes
   values MUST sum to EXACTLY {duration_minutes} minutes. Before answering,
   add up your own section durations and adjust them until the total is
   exactly {duration_minutes} — this is a hard requirement, not a guideline.

Reply with ONLY this JSON, nothing else:
{{
  "learning_objectives": ["...", "..."],
  "outline": [
    {{"section": "...", "duration_minutes": 0, "description": "..."}}
  ]
}}
"""


def parse_duration_to_minutes(duration: str) -> int | None:
    """
    Turns a human duration string ("3 hours", "90 minutes", "4.5 hours")
    into a plain number of minutes. Returns None if it can't parse it —
    callers should handle that gracefully rather than assuming success.
    """
    text = duration.lower()
    hours_match = re.search(r"(\d+(?:\.\d+)?)\s*h", text)
    mins_match = re.search(r"(\d+(?:\.\d+)?)\s*m", text)

    if not hours_match and not mins_match:
        return None

    total = 0.0
    if hours_match:
        total += float(hours_match.group(1)) * 60
    if mins_match:
        total += float(mins_match.group(1))
    return round(total)


def rebalance_outline(outline: list[dict], target_minutes: int) -> list[dict]:
    """
    Scales an outline's section durations so they sum to exactly
    target_minutes, preserving each section's relative share of the time.
    Any rounding remainder is applied to the last section.
    """
    actual_minutes = sum(section.get("duration_minutes", 0) for section in outline)

    if actual_minutes == target_minutes or actual_minutes == 0 or not outline:
        return outline

    scale = target_minutes / actual_minutes
    for section in outline:
        section["duration_minutes"] = max(1, round(section.get("duration_minutes", 0) * scale))

    remainder = target_minutes - sum(section["duration_minutes"] for section in outline)
    outline[-1]["duration_minutes"] += remainder

    return outline


CYCLE_PROMPT_TEMPLATE = """You are building a detailed plan for a technical workshop.

Workshop title: {title}

Context on the workshop:
- Audience: {audience}
- Age: {age}
- Duration: {duration} (== {duration_minutes} minutes total)
- Goal: {goal}
- Extra notes: {notes}

Recent, relevant web research on this specific topic:
{search_results}

This workshop follows a fixed explain -> hands-on lab -> break rhythm,
repeated as many times as fits the total duration. Below is the exact
section structure with durations ALREADY DECIDED — do NOT change, add,
remove, or reorder sections, and do NOT change any duration_minutes value.

Each line below shows a ROLE in brackets, like [explain] or [lab] — this
is a CATEGORY, not a title. Your job is to invent a real, specific,
topic-relevant title for each one and write a one-sentence description.

CRITICAL: the "section" field in your JSON must NEVER be one of the role
words themselves ("opening", "explain", "lab", "break", "qna",
"competition", "closing"). Those words must not appear as a section name.
For example, if the role is [explain], a BAD section name is "explain" —
a GOOD section name is something like "Crafting Effective System Prompts".

What each role means, to guide the title/description you write:
- "opening": a short welcome/intro
- "explain": teaching content for that part of the topic
- "lab": a hands-on exercise applying what was just taught
- "break": simply a break, low-effort description is fine
- "qna": an open Q&A / discussion segment
- "competition": a light, fast recap game or quiz on what's been covered
  so far (NOT a full new topic — this is left over time, keep it playful)
- "closing": a short wrap-up / thank you

Fixed structure:
{skeleton_list}

Also include 3-5 clear learning objectives (what attendees should be able
to DO by the end).

Reply with ONLY this JSON, nothing else — "outline" must have exactly
{section_count} items, in the same order as the fixed structure above,
each keeping its given duration_minutes unchanged:
{{
  "learning_objectives": ["...", "..."],
  "outline": [
    {{"section": "...", "duration_minutes": 0, "description": "..."}}
  ]
}}
"""


def classify_leftover_minutes(leftover_minutes: int) -> list[dict]:
    """
    Decides what to do with time left over after fitting as many full
    explain/lab/break cycles as possible — never enough for another full
    cycle, but too much to just ignore. Returns a list because larger
    leftovers are split across a couple of blocks instead of one oversized
    one (e.g. a 50-minute leftover becomes a competition + Q&A + closing,
    not one 50-minute "closing" slide nobody wants to sit through).

    Thresholds (tune freely):
      < 10 min  -> folded into the last break, not its own section
      10-20 min -> a short Q&A segment
      21-40 min -> a light recap competition/quiz
      41+ min   -> competition + Q&A + a short closing, splitting the time
    """
    if leftover_minutes <= 0:
        return []
    if leftover_minutes < 10:
        return [{"role": "break", "duration_minutes": leftover_minutes, "merge_into_last_break": True}]
    if leftover_minutes <= 20:
        return [{"role": "qna", "duration_minutes": leftover_minutes, "merge_into_last_break": False}]
    if leftover_minutes <= 40:
        return [{"role": "competition", "duration_minutes": leftover_minutes, "merge_into_last_break": False}]

    competition_minutes = 25
    closing_minutes = 10
    qna_minutes = leftover_minutes - competition_minutes - closing_minutes
    return [
        {"role": "competition", "duration_minutes": competition_minutes, "merge_into_last_break": False},
        {"role": "qna", "duration_minutes": qna_minutes, "merge_into_last_break": False},
        {"role": "closing", "duration_minutes": closing_minutes, "merge_into_last_break": False},
    ]


def build_cycle_skeleton(
    duration_minutes: int,
    explain_minutes: int,
    lab_minutes: int,
    break_minutes: int,
    opening_minutes: int = 10,
) -> list[dict]:
    """
    Computes an opening -> [explain, lab, break] x N skeleton using the
    exact explain/lab/break lengths the user chose, fitting as many full
    cycles as the duration allows. Time left over (not enough for another
    full cycle) becomes a fitting bonus block via classify_leftover_minutes
    — Q&A, a quick competition, or an extended closing — rather than being
    forced into a shortened, awkward extra cycle.
    """
    cycle_total = explain_minutes + lab_minutes + break_minutes
    if cycle_total <= 0:
        raise ValueError("explain_minutes + lab_minutes + break_minutes must be greater than 0.")

    available = duration_minutes - opening_minutes
    if available < cycle_total:
        raise ValueError(
            f"{duration_minutes} minutes isn't enough for even one "
            f"explain({explain_minutes}) + lab({lab_minutes}) + break({break_minutes}) "
            f"cycle plus the {opening_minutes}-minute opening. Shorten the cycle or "
            "lengthen the workshop."
        )

    num_full_cycles = available // cycle_total
    leftover_minutes = available - (num_full_cycles * cycle_total)

    skeleton = [{"role": "opening", "duration_minutes": opening_minutes}]
    for _ in range(num_full_cycles):
        skeleton.append({"role": "explain", "duration_minutes": explain_minutes})
        skeleton.append({"role": "lab", "duration_minutes": lab_minutes})
        skeleton.append({"role": "break", "duration_minutes": break_minutes})

    bonus_blocks = classify_leftover_minutes(leftover_minutes)
    for i, bonus in enumerate(bonus_blocks):
        if bonus["merge_into_last_break"] and i == 0 and skeleton[-1]["role"] == "break":
            skeleton[-1]["duration_minutes"] += bonus["duration_minutes"]
        else:
            skeleton.append({"role": bonus["role"], "duration_minutes": bonus["duration_minutes"]})

    return skeleton


def format_skeleton(skeleton: list[dict]) -> str:
    """Turns the cycle skeleton into a readable, numbered block for the prompt."""
    lines = []
    for i, item in enumerate(skeleton, start=1):
        lines.append(f"{i}. [{item['role']}] {item['duration_minutes']} minutes")
    return "\n".join(lines)


def title_from_description(description: str, fallback: str) -> str:
    """
    Builds a short, presentable title out of a section's own description,
    for when the model didn't provide a usable title itself. Takes the
    first several words of the description; falls back to a generic
    label if the description is empty.
    """
    words = (description or "").strip().split()
    if not words:
        return fallback
    title = " ".join(words[:6]).rstrip(".,;:")
    return title[0].upper() + title[1:] if title else fallback


def build_plan(
    title: str,
    audience: str,
    age: str,
    duration: str,
    goal: str,
    notes: str,
    use_lab_cycle: bool = False,
    explain_minutes: int = 30,
    lab_minutes: int = 20,
    break_minutes: int = 15,
) -> dict:
    """
    The function the rest of the app calls. Give it the chosen title plus
    the same user inputs from Step 0, get back {"learning_objectives": [...], "outline": [...]}.

    use_lab_cycle=True switches to a fixed explain -> lab -> break rhythm,
    repeated as many times as the duration allows (good for hands-on
    technical workshops); leave it False for a freely structured outline
    (better for lighter or more conceptual workshops). explain_minutes /
    lab_minutes / break_minutes default to 30 / 20 / 15 but are meant to
    come straight from the user's input form when they customize the
    rhythm. Any time left over after the last full cycle is appended once,
    at the very end (never split between cycles), as a fitting bonus block
    — Q&A, a quick competition, or an extended closing — instead of a
    forced partial cycle. See classify_leftover_minutes.
    """
    duration_minutes = parse_duration_to_minutes(duration)
    if duration_minutes is None:
        raise ValueError(
            f"Couldn't understand duration '{duration}' as a number of hours/minutes. "
            "Expected something like '3 hours', '90 minutes', or '4.5 hours'."
        )

    # One focused search, now that we know the exact title — sharper than
    # Step 0's broader "current trends" search.
    search_results = search_web(f"{title} workshop curriculum best practices")

    if use_lab_cycle:
        skeleton = build_cycle_skeleton(
            duration_minutes,
            explain_minutes=explain_minutes,
            lab_minutes=lab_minutes,
            break_minutes=break_minutes,
        )
        prompt = CYCLE_PROMPT_TEMPLATE.format(
            title=title,
            audience=audience,
            age=age,
            duration=duration,
            duration_minutes=duration_minutes,
            goal=goal,
            notes=notes,
            search_results=format_results(search_results),
            skeleton_list=format_skeleton(skeleton),
            section_count=len(skeleton),
        )
        plan = ask_llm_for_json(prompt)

        # BUG FIX: the model doesn't always return exactly len(skeleton)
        # outline items despite the prompt instruction (LLMs are inconsistent
        # about "return exactly N items" on longer lists). zip() below
        # silently pairs only up to the SHORTER of the two lists — if the
        # model returned fewer or more sections than the skeleton, some
        # skeleton entries never get their locked duration/role applied at
        # all. The old code then called rebalance_outline() unconditionally
        # at the very end (see below), which — once the total no longer
        # matched duration_minutes because of the mismatch above — would
        # PROPORTIONALLY RESCALE every section's duration, silently
        # overwriting the "locked" explain/lab/break minutes the user
        # explicitly chose. That's the actual mechanism behind "I set exact
        # minutes and it still didn't stick": the cycle math was correct,
        # but a mismatched LLM reply plus the final rebalance pass could
        # still quietly break it.
        #
        # Fix: force the outline to have EXACTLY len(skeleton) items, built
        # directly from the skeleton itself — using the model's own
        # section/description by position where it provided one, and a
        # sensible fallback where it didn't — so every duration is fixed
        # by construction, never by a rescale that can silently drift.
        model_outline = plan.get("outline", [])
        if len(model_outline) != len(skeleton):
            print(
                f"⚠️  Plan model returned {len(model_outline)} outline items, "
                f"expected exactly {len(skeleton)} (one per skeleton slot). "
                "Rebuilding the outline directly from the skeleton so every "
                "explain/lab/break duration stays exact."
            )
        fixed_outline = []
        for i, fixed in enumerate(skeleton):
            model_section = model_outline[i] if i < len(model_outline) else {}
            fixed_outline.append({
                "section": model_section.get("section", ""),
                "description": model_section.get("description", ""),
                "duration_minutes": fixed["duration_minutes"],
                "role": fixed["role"],
            })
        plan["outline"] = fixed_outline

        # Durations/roles are locked by the skeleton, not left to the model. If
        # the model also left a raw role word as the section name instead of a
        # real title (or left it blank because this slot didn't exist in its
        # reply), build one from that section's own description instead.
        role_words = {"", "explain", "lab", "qna", "competition"}  # never legitimate titles on their own
        for section in plan["outline"]:
            if section.get("section", "").strip().lower() in role_words:
                section["section"] = title_from_description(
                    section.get("description", ""), fallback=section["role"].capitalize()
                )
    else:
        prompt = PLAN_PROMPT_TEMPLATE.format(
            title=title,
            audience=audience,
            age=age,
            duration=duration,
            duration_minutes=duration_minutes,
            goal=goal,
            notes=notes,
            search_results=format_results(search_results),
        )
        plan = ask_llm_for_json(prompt)
        # Only rebalance in freeform mode. In cycle mode, every section's
        # duration is already fixed by construction (see above) — running
        # a proportional rebalance on top would silently override the
        # exact explain/lab/break minutes the user chose, which is the
        # opposite of what "lock the cycle durations" is supposed to mean.
        plan["outline"] = rebalance_outline(plan.get("outline", []), duration_minutes)

    return plan