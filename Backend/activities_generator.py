"""
Step 4: activities/labs generator.

What it does, in plain English:
  1. Looks at Step 1's outline and figures out exactly where each lab
     should go, and what content it should be tied to.
       - If the plan was built with use_lab_cycle=True (explain -> lab ->
         break rhythm), each outline section marked role="lab" already
         IS a lab slot — we just read its position and duration straight
         off the outline.
       - If the plan has no role tags (a freely structured outline),
         we fall back to grouping the outline into ~60-minute blocks and
         giving each block one lab, tied to everything covered in it.
     This step is deliberately decoupled from plan_builder.py — it only
     reads a plain "outline: list[dict]" with "section"/"duration_minutes"
     (and optional "role") keys. It doesn't import or call plan_builder,
     so any outline in that shape works here, whether it came from Step 1
     or was put together by hand.
  2. For each lab slot, asks the AI to SUGGEST a lab type (coding vs
     interactive_tool) based on the content — this is shown to the trainer to
     confirm or override before anything is actually generated.
  3. Once the trainer confirms type + any customization notes, generates
     the full lab: for "coding" labs, a trainee notebook + a solved
     solution notebook; for "interactive_tool" labs, a real matching external tool + guided prompts.
     Every lab also gets instructor notes and 1-3 real, searched external
     platform suggestions (Kaggle, Colab, etc.) as an alternative/supplement.

This file is being built in stages so each piece can be tested on its own
before the next one is added. So far: extract_lab_contexts (pure Python,
no API needed) and suggest_lab_types (one LLM call).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from llm_client import ask_llm_for_json
from search_tool import search_web
from idea_agent import format_results

from config import LAB_MINUTES_PER_HOUR_BLOCK as MINUTES_PER_HOUR_BLOCK


def extract_lab_contexts(outline: list[dict]) -> list[dict]:
    """
    Figures out which parts of the outline should get a lab, and what
    content each lab should be tied to. Returns one entry per lab, in
    order, each shaped:

        {"covers_sections": [...], "duration_minutes": N, "outline_index": i}

    Two modes, auto-detected from the outline itself:

    - ROLE-BASED (outline sections have a "role" key — i.e. the plan was
      built with plan_builder's use_lab_cycle=True): one lab context per
      section whose role is exactly "lab", tied to whichever "explain"
      section(s) came right before it since the last lab or break. This
      matches the trainer's chosen explain/lab/break rhythm exactly —
      no re-grouping needed, the plan already decided where labs go.

    - HOUR-BASED FALLBACK (no "role" key anywhere — a freely structured
      outline, use_lab_cycle=False): groups consecutive sections into
      blocks of ~60 minutes each and gives each block one lab, tied to
      everything covered in that hour. This is the fallback for
      workshops that don't use the fixed cycle structure.
    """
    has_roles = any("role" in section for section in outline)

    if has_roles:
        contexts = []
        pending_explains: list[str] = []
        for i, section in enumerate(outline):
            name = section.get("section")
            minutes = section.get("duration_minutes")
            if name is None or minutes is None:
                raise ValueError(
                    f"Outline section at index {i} is missing 'section' or "
                    f"'duration_minutes': {section!r}. This usually means Step 1's "
                    "LLM reply was malformed — check the plan before running Step 4."
                )
            role = section.get("role")
            if role == "explain":
                pending_explains.append(name)
            elif role == "lab":
                contexts.append(
                    {
                        # Falls back to the lab's own name only in the edge
                        # case where a lab appears with no preceding explain
                        # section at all (e.g. right after the opening).
                        "covers_sections": pending_explains or [name],
                        "duration_minutes": minutes,
                        "outline_index": i,
                    }
                )
                pending_explains = []
            elif role == "break":
                # A break resets what "just covered" means — content before
                # a break shouldn't bleed into the next explain/lab pair.
                pending_explains = []
        return contexts

    # Hour-based fallback for outlines with no role tags.
    contexts = []
    current_block: list[str] = []
    current_minutes = 0
    block_start_index = 0
    for i, section in enumerate(outline):
        name = section.get("section")
        minutes = section.get("duration_minutes")
        if name is None or minutes is None:
            raise ValueError(
                f"Outline section at index {i} is missing 'section' or "
                f"'duration_minutes': {section!r}. This usually means Step 1's "
                "LLM reply was malformed — check the plan before running Step 4."
            )
        current_block.append(name)
        current_minutes += minutes
        if current_minutes >= MINUTES_PER_HOUR_BLOCK or i == len(outline) - 1:
            contexts.append(
                {
                    "covers_sections": current_block,
                    "duration_minutes": current_minutes,
                    "outline_index": block_start_index,
                }
            )
            current_block, current_minutes = [], 0
            block_start_index = i + 1
    return contexts


def format_content_blocks(blocks: list[dict]) -> str:
    """
    Renders one section's Step-2-style content blocks (heading, paragraph,
    bullet_list, code, image_placeholder) as readable plain text.

    This is the OLD Step 2 shape's formatter (single-flavor blocks, always
    keyed under "text"). Kept for backward compatibility with any content
    still in that shape; new Step 2 output uses format_slide_blocks below.
    """
    lines = []
    for block in blocks:
        block_type = block.get("type")
        text = block.get("text")
        if block_type == "bullet_list" and isinstance(text, list):
            lines.extend(f"  - {item}" for item in text)
        elif block_type == "code":
            lines.append(f"  [code]\n{text}")
        elif text:
            lines.append(f"  {text}")
    return "\n".join(lines)


def format_slide_blocks(blocks: list[dict]) -> str:
    """
    Renders ONE slide's blocks as readable plain text — for the current
    Step 2 shape, where each slide's blocks vary by layout type
    (roadmap_slide, columns_3_slide, timeline_slide, content_slide) and
    aren't all keyed the same way as the old format_content_blocks
    expects (e.g. bullet_list uses "items" here, not "text"; roadmap,
    columns, and timeline blocks nest their own sub-structures entirely).
    Unknown block shapes are skipped rather than raising, since this is
    read-only grounding text, not something that needs to be complete.
    """
    lines = []
    for block in blocks:
        block_type = block.get("type")

        if block_type in ("heading", "paragraph", "activity", "image_placeholder"):
            text = block.get("text")
            if text:
                lines.append(f"  {text}")

        elif block_type == "bullet_list":
            for item in block.get("items", []):
                lines.append(f"  - {item}")

        elif block_type == "roadmap":
            for item in block.get("items", []):
                lines.append(f"  - {item.get('title', '')}: {item.get('detail', '')}")

        elif block_type == "columns_3":
            for col in block.get("columns", []):
                lines.append(f"  - {col.get('heading', '')}: {col.get('text', '')}")

        elif block_type == "timeline":
            for event in block.get("events", []):
                lines.append(f"  - [{event.get('date', '')}] {event.get('title', '')}: {event.get('text', '')}")

    return "\n".join(lines)


def group_slides_by_section(slides: list[dict]) -> dict[str, list[dict]]:
    """
    Groups the current Step 2 shape's flat "slides" list back by the
    outline section each slide belongs to — Step 2 makes multiple slides
    per section (2 by default), so this reconstructs a per-section view
    the same way the old {"content": [...]} shape provided directly.
    """
    by_section: dict[str, list[dict]] = {}
    for slide in slides:
        section_name = slide.get("section")
        if section_name is None:
            continue
        by_section.setdefault(section_name, []).append(slide)
    return by_section


def normalize_content_for_sections(covers_sections: list[str], content=None) -> str:
    """
    Builds a plain-text "what was actually taught" block for a lab, no
    matter what shape the content comes in — this is what lets Step 4
    work whether Step 2's full slide content is ready, half-ready, in a
    completely different shape, or not available at all:

      - CURRENT Step 2 shape ({"slides": [{"section": ..., "slide_title":
        ..., "blocks": [...], "speaker_notes": ...}]}) -> groups slides by
        section, renders each slide's title, speaker notes, and blocks
        (any layout type — see format_slide_blocks).
      - OLD Step 2 shape ({"content": [{"section": "...", "blocks": [...]}]})
        -> still supported, for any content generated before this shape
        changed, or built by hand in that format.
      - A simple {"section name": "raw text"} dict — e.g. slide text
        pasted in by hand, or content from anywhere else entirely — used
        as-is.
      - None, an unrecognized shape, or a section with no matching entry
        in any shape above -> falls back to just the section's name,
        so the lab still generates (grounded in less detail) instead of
        crashing or blocking on missing content.
    """
    if content is None:
        return "\n".join(
            f"- {name} (no detailed content available — use the section name/topic as your guide)"
            for name in covers_sections
        )

    # Current Step 2 shape: {"slides": [{"section": ..., "blocks": [...], ...}]}
    if isinstance(content, dict) and "slides" in content and isinstance(content["slides"], list):
        by_section = group_slides_by_section(content["slides"])
        parts = []
        for name in covers_sections:
            slides = by_section.get(name)
            if slides:
                slide_texts = []
                for slide in slides:
                    slide_title = slide.get("slide_title", "")
                    blocks_text = format_slide_blocks(slide.get("blocks", []))
                    notes = slide.get("speaker_notes", "")
                    piece = f"### {slide_title}\n{blocks_text}"
                    if notes:
                        piece += f"\n  (speaker notes: {notes})"
                    slide_texts.append(piece)
                parts.append(f"## {name}\n" + "\n".join(slide_texts))
            else:
                parts.append(
                    f"## {name}\n(no detailed content found for this section — "
                    "use the section name/topic as your guide)"
                )
        return "\n\n".join(parts)

    # Old Step 2 shape: {"content": [{"section": ..., "blocks": [...]}]}
    if isinstance(content, dict) and "content" in content and isinstance(content["content"], list):
        by_section = {
            entry.get("section"): entry.get("blocks", [])
            for entry in content["content"]
            if isinstance(entry, dict)
        }
        parts = []
        for name in covers_sections:
            blocks = by_section.get(name)
            if blocks:
                parts.append(f"## {name}\n{format_content_blocks(blocks)}")
            else:
                parts.append(
                    f"## {name}\n(no detailed content found for this section — "
                    "use the section name/topic as your guide)"
                )
        return "\n\n".join(parts)

    # A simple {section_name: "raw text"} dict — any other source of content.
    if isinstance(content, dict):
        parts = []
        for name in covers_sections:
            text = content.get(name)
            parts.append(
                f"## {name}\n"
                f"{text if text else '(no detailed content available — use the section name/topic as your guide)'}"
            )
        return "\n\n".join(parts)

    # Unrecognized shape — don't guess at parsing it, fall back safely.
    return "\n".join(
        f"- {name} (content format not recognized — using section name/topic as your guide)"
        for name in covers_sections
    )


TYPE_SUGGESTION_PROMPT_TEMPLATE = """You are helping a trainer plan hands-on labs for a technical workshop.

Workshop title: {title}

Below are the lab slots already placed in this workshop, each tied to the
content that leads into it. For EACH one, decide whether it should be:
  - "interactive_tool": pick this when a REAL, well-known, genuinely
    excellent existing website already lets someone practice this exact
    skill hands-on WITHOUT writing code (e.g. teachablemachine.withgoogle.com
    for training an image/sound classifier by example, CyberChef for data
    encoding/decoding, an official interactive playground for a specific
    technology). This is often the BETTER choice when such a tool exists —
    a real, polished tool beats a from-scratch notebook when the trainee's
    goal is to understand something experientially.
  - "coding": a hands-on exercise where the trainee writes/runs actual
    code in a notebook — pick this when no genuinely great existing
    interactive tool covers this content, OR when writing code IS the
    specific skill being taught (so a no-code tool would skip the point).

There is no third "just answer some questions" type — every lab must be
something the trainee actively DOES, either on a real tool or in code.
If you're unsure whether a great matching tool exists, lean "coding" —
generate_labs will still search for and prefer a real tool automatically
when generating an "interactive_tool" lab, and safely falls back to
"coding" itself if no good tool turns up at generation time.

This is a SUGGESTION ONLY — the trainer will confirm or override it
before anything gets generated, so make your best judgment call and
briefly explain why.

Lab slots:
{contexts_list}

Reply with ONLY this JSON, nothing else — exactly one entry per lab slot
listed above, same order, same outline_index values:
{{
  "suggestions": [
    {{"outline_index": 0, "lab_type": "coding", "reason": "one short sentence"}}
  ]
}}
"""


def format_lab_contexts(lab_contexts: list[dict]) -> str:
    """Turns lab contexts into a readable, numbered block for the prompt."""
    lines = []
    for ctx in lab_contexts:
        covers = ", ".join(ctx["covers_sections"])
        lines.append(
            f"- outline_index {ctx['outline_index']} ({ctx['duration_minutes']} min): covers [{covers}]"
        )
    return "\n".join(lines)


def suggest_lab_types(title: str, lab_contexts: list[dict]) -> dict:
    """
    One LLM call: for each lab context, suggest "coding" or "interactive_tool"
    based on the content it covers, plus a one-line reason. Meant to be
    shown to the trainer as a pre-filled default they confirm or change —
    NOT the final decision (generate_labs, added next, takes the
    trainer-confirmed type, not this suggestion, as its real input).

    Returns {"suggestions": [{"outline_index": i, "lab_type": "...", "reason": "..."}]}.
    Returns {"suggestions": []} immediately (no API call) if there are no
    lab slots to suggest for.
    """
    if not lab_contexts:
        return {"suggestions": []}

    prompt = TYPE_SUGGESTION_PROMPT_TEMPLATE.format(
        title=title,
        contexts_list=format_lab_contexts(lab_contexts),
    )
    return ask_llm_for_json(prompt)


def attach_suggested_types(lab_contexts: list[dict], suggestions: dict) -> list[dict]:
    """
    Merges suggest_lab_types' output back onto lab_contexts, matched by
    outline_index (not position — safer if the model ever reorders its
    reply). Each context gets "suggested_lab_type" and "suggested_reason"
    added. If a context's index is missing from the suggestions for any
    reason, it's left as None rather than crashing, so the UI can still
    show it and let the trainer pick manually.
    """
    by_index = {s["outline_index"]: s for s in suggestions.get("suggestions", [])}
    merged = []
    for ctx in lab_contexts:
        suggestion = by_index.get(ctx["outline_index"])
        merged.append(
            {
                **ctx,
                "suggested_lab_type": suggestion["lab_type"] if suggestion else None,
                "suggested_reason": suggestion["reason"] if suggestion else None,
            }
        )
    return merged


LAB_GENERATION_PROMPT_TEMPLATE = """You are creating a hands-on lab for a technical workshop. This lab must be \
ready to use as-is: trainees get a working exercise, and the trainer gets a complete answer key ready \
BEFORE the session — never something to solve live in front of trainees.

Workshop title: {title}
Lab type: {lab_type}
Time allotted for this lab: {duration_minutes} minutes

Content actually taught right before this lab — ground the lab in THIS, don't invent unrelated material:
{content_text}
{customization_block}
Real search results below — these are the ONLY candidates you may use, never invent a name or URL \
that isn't in this list:
{search_results}

{type_instructions}

Reply with ONLY this JSON, nothing else:
{schema_block}
"""

CODING_TYPE_INSTRUCTIONS = """Since lab_type is "coding", build TWO SEPARATE notebooks, each as a list of cells:
- "trainee_notebook_cells": markdown cells explaining the task, plus CODE cells that are scaffolded/incomplete \
(e.g. "# TODO: ..." or blanks to fill in) — this is what trainees receive.
- "solution_notebook_cells": the exact same structure and cell count, but with the code cells fully written \
and working — this is the trainer's answer key, ready before the session.
Each cell is {"cell_type": "markdown" or "code", "content": "..."}.
From the search results, if any are a genuinely interactive/hands-on resource (not a passive tutorial \
video or course) that would make a good SUPPLEMENTARY option alongside the notebook, list it in \
"suggested_platforms". If none qualify, return an empty list — never invent one or include a passive one."""

INTERACTIVE_TOOL_TYPE_INSTRUCTIONS = """Since lab_type is "interactive_tool", your job is to pick ONE real, \
genuinely excellent tool from the search results below that lets the trainee practice this exact content \
hands-on, with no code required. Set "found_matching_tool" to true and fill in "external_tool" ONLY if at \
least one search result is a real, well-known, GENUINELY INTERACTIVE tool/playground for this exact topic \
(the trainee can train/build/configure/experiment there, not just read or watch). REJECT anything passive — \
tutorial videos, articles, course listings, marketing pages. If NOTHING in the search results is a \
genuinely great, genuinely interactive match, set "found_matching_tool" to false and leave "external_tool" \
null — do NOT force a mediocre or loosely-related match just to fill the field. Write "instructions" and \
"guided_prompts" only if found_matching_tool is true (step-by-step what to do at the tool, tied to this \
content, plus 2-4 short reflection/task prompts the trainee notes down while using it — not a graded quiz, \
just structure for what to notice/try)."""

CODING_SCHEMA = """{
  "title": "...",
  "instructions": "markdown: what the trainee needs to do, in plain language",
  "trainee_notebook_cells": [{"cell_type": "markdown", "content": "..."}],
  "solution_notebook_cells": [{"cell_type": "markdown", "content": "..."}],
  "instructor_notes": "what to watch for, common mistakes, timing tips",
  "suggested_platforms": [{"name": "...", "url": "...", "why_it_fits": "..."}]
}"""

INTERACTIVE_TOOL_SCHEMA = """{
  "found_matching_tool": true or false,
  "title": "... (empty string if found_matching_tool is false)",
  "instructions": "markdown: step-by-step what to do at the tool, tied to this content (empty string if found_matching_tool is false)",
  "external_tool": {"name": "...", "url": "...", "why_it_fits": "..."},
  "guided_prompts": ["a short reflection/task prompt", "..."],
  "instructor_notes": "what to watch for, timing tips (empty string if found_matching_tool is false)"
}"""


def generate_one_lab(
    title: str,
    lab_context: dict,
    lab_type: str,
    content=None,
    customization_notes: str = "",
) -> dict:
    """
    Generates ONE fully-built lab: one web search for grounding, then one
    LLM call for the actual content (a real external tool for
    "interactive_tool", two notebooks for "coding").

    IMPORTANT: if lab_type is "interactive_tool" but the search + LLM call
    can't find a genuinely great, genuinely interactive real tool for this
    content, this function automatically FALLS BACK to generating a
    "coding" lab instead (a fresh search + a second LLM call) — there is
    no third "just questions" type to fall back to anymore, and a
    forced/mediocre tool match is worse than a solid notebook.

    Returns the lab's own fields plus its context (outline_index,
    covers_sections, duration_minutes, lab_type — reflecting whatever
    type was ACTUALLY generated, which may differ from the requested
    lab_type if a fallback happened) merged in.
    """
    if lab_type not in ("coding", "interactive_tool"):
        raise ValueError(f"lab_type must be 'coding' or 'interactive_tool', got {lab_type!r}.")

    covers = lab_context["covers_sections"]
    content_text = normalize_content_for_sections(covers, content)
    customization_block = (
        f'\nTrainer\'s customization request for THIS lab — follow it: "{customization_notes}"\n'
        if customization_notes
        else ""
    )

    def _generate_coding_lab() -> dict:
        search_query = (
            f"{title} {' '.join(covers)} interactive coding exercise "
            "Kaggle notebook Colab practice sandbox"
        )
        search_results = search_web(search_query)
        prompt = LAB_GENERATION_PROMPT_TEMPLATE.format(
            title=title,
            lab_type="coding",
            duration_minutes=lab_context["duration_minutes"],
            content_text=content_text,
            customization_block=customization_block,
            search_results=format_results(search_results),
            type_instructions=CODING_TYPE_INSTRUCTIONS,
            schema_block=CODING_SCHEMA,
        )
        result = ask_llm_for_json(prompt)
        result["lab_type"] = "coding"
        return result

    if lab_type == "coding":
        lab = _generate_coding_lab()
    else:
        # "interactive_tool": search for a real matching tool FIRST, then
        # ask the LLM to confirm a genuine match exists before building
        # the lab around it.
        search_query = (
            f"{title} {' '.join(covers)} interactive tool train build practice "
            "online no-code playground sandbox"
        )
        search_results = search_web(search_query)
        prompt = LAB_GENERATION_PROMPT_TEMPLATE.format(
            title=title,
            lab_type="interactive_tool",
            duration_minutes=lab_context["duration_minutes"],
            content_text=content_text,
            customization_block=customization_block,
            search_results=format_results(search_results),
            type_instructions=INTERACTIVE_TOOL_TYPE_INSTRUCTIONS,
            schema_block=INTERACTIVE_TOOL_SCHEMA,
        )
        result = ask_llm_for_json(prompt)

        if result.get("found_matching_tool") and result.get("external_tool", {}).get("url"):
            result["lab_type"] = "interactive_tool"
            lab = result
        else:
            # No genuinely good tool found — fall back to a coding lab
            # rather than shipping a forced/weak match or leaving a gap.
            print(
                f"No matching interactive tool found for '{lab_context['covers_sections']}', "
                "falling back to a coding lab instead."
            )
            lab = _generate_coding_lab()

    lab["outline_index"] = lab_context["outline_index"]
    lab["covers_sections"] = covers
    lab["duration_minutes"] = lab_context["duration_minutes"]
    return lab


def generate_labs(
    title: str,
    lab_contexts: list[dict],
    confirmed_lab_types: dict,
    content=None,
    customization_notes=None,
) -> dict:
    """
    The function the rest of the app calls for Step 4's real generation.

    confirmed_lab_types: {outline_index: "coding" or "interactive_tool"} — the
      TRAINER-CONFIRMED type for each lab (from the UI, after reviewing
      suggest_lab_types' suggestions). This function does not fall back
      to the AI's suggestion on its own — every lab needs an explicit
      confirmed type, or it raises rather than silently guessing. Note:
      an "interactive_tool" request may still come back as a "coding"
      lab in the result if generate_one_lab couldn't find a genuinely
      good matching tool — check each returned lab's own "lab_type".
    content: passed straight to normalize_content_for_sections — Step 2's
      output, a simple {section: text} dict, or None. Any shape is safe.
    customization_notes: either one string applied to every lab, or a
      {outline_index: "note"} dict for per-lab notes. Optional.

    Returns {"labs": [...]}, one fully generated lab per lab_context, in
    the SAME order as lab_contexts regardless of which one finishes
    generating first (labs are generated concurrently — see below).
    """
    # Validate every type is confirmed BEFORE spawning any work — fail
    # fast on a missing confirmation instead of doing (and discarding)
    # partial work in other threads.
    jobs = []  # (ctx, lab_type, notes), one per lab_context, in original order
    for ctx in lab_contexts:
        lab_type = confirmed_lab_types.get(ctx["outline_index"])
        if lab_type not in ("coding", "interactive_tool"):
            raise ValueError(
                f"No confirmed lab_type for outline_index {ctx['outline_index']} "
                f"(covers {ctx['covers_sections']!r}) — got {lab_type!r}. Every lab "
                "needs a trainer-confirmed type before generation; run suggest_lab_types "
                "first and have the trainer confirm/override each one."
            )

        if isinstance(customization_notes, dict):
            notes = customization_notes.get(ctx["outline_index"], "")
        elif isinstance(customization_notes, str):
            notes = customization_notes
        else:
            notes = ""
        jobs.append((ctx, lab_type, notes))

    # Labs are independent of each other (each is its own search + LLM
    # call, sometimes two if an interactive_tool falls back to coding),
    # so generating them one at a time was the same needless bottleneck
    # content generation had before it was parallelized — same fix here.
    def _generate_one(job):
        ctx, lab_type, notes = job
        return ctx["outline_index"], generate_one_lab(title, ctx, lab_type, content=content, customization_notes=notes)

    max_workers = min(3, len(jobs)) if jobs else 1
    results_by_index = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_generate_one, job) for job in jobs]
        for future in as_completed(futures):
            outline_index, lab = future.result()
            results_by_index[outline_index] = lab

    # Reassemble in the ORIGINAL lab_contexts order — not completion
    # order, which is unpredictable with concurrent generation.
    labs = [results_by_index[ctx["outline_index"]] for ctx in lab_contexts]

    return {"labs": labs}


if __name__ == "__main__":
    # Quick self-tests — extract_lab_contexts needs no API keys (pure
    # Python). suggest_lab_types is mocked here (no real network call) just
    # to prove attach_suggested_types' merging logic is correct; testing
    # the actual prompt quality against the real Gemini API is a separate,
    # manual step (run with a real .env and real outline data).

    print("=== Test 1: role-based outline (use_lab_cycle=True style) ===")
    role_based_outline = [
        {"section": "Welcome", "duration_minutes": 10, "role": "opening"},
        {"section": "Prompting Basics", "duration_minutes": 30, "role": "explain"},
        {"section": "Write Your First Prompt", "duration_minutes": 20, "role": "lab"},
        {"section": "Stretch Break", "duration_minutes": 15, "role": "break"},
        {"section": "RAG Fundamentals", "duration_minutes": 30, "role": "explain"},
        {"section": "Build a Mini RAG Pipeline", "duration_minutes": 20, "role": "lab"},
        {"section": "Break", "duration_minutes": 15, "role": "break"},
        {"section": "Wrap-up Q&A", "duration_minutes": 15, "role": "qna"},
    ]
    lab_contexts = extract_lab_contexts(role_based_outline)
    for ctx in lab_contexts:
        print(ctx)

    print("\n=== Test 2: hour-based fallback (no role tags) ===")
    freeform_outline = [
        {"section": "Intro to LLMs", "duration_minutes": 25, "description": "..."},
        {"section": "Tokenization", "duration_minutes": 20, "description": "..."},
        {"section": "Embeddings", "duration_minutes": 25, "description": "..."},
        {"section": "Vector Search", "duration_minutes": 30, "description": "..."},
    ]
    for ctx in extract_lab_contexts(freeform_outline):
        print(ctx)

    print("\n=== Test 3: attach_suggested_types merging (mocked LLM reply) ===")
    mock_suggestions = {
        "suggestions": [
            {"outline_index": 2, "lab_type": "coding", "reason": "Prompting is best learned by writing prompts."},
            {"outline_index": 5, "lab_type": "coding", "reason": "RAG is best learned by building a pipeline."},
        ]
    }
    merged = attach_suggested_types(lab_contexts, mock_suggestions)
    for ctx in merged:
        print(ctx)

    print("\n=== Test 4: attach_suggested_types with a MISSING suggestion (shouldn't crash) ===")
    incomplete_suggestions = {
        "suggestions": [
            {"outline_index": 2, "lab_type": "coding", "reason": "..."},
            # outline_index 5 missing on purpose
        ]
    }
    merged_partial = attach_suggested_types(lab_contexts, incomplete_suggestions)
    for ctx in merged_partial:
        print(ctx)

    print("\n=== Test 5: suggest_lab_types with an empty lab list (should skip the API call) ===")
    print(suggest_lab_types("Some Workshop", []))

    print("\n=== Test 6: normalize_content_for_sections — Step 2 slide format ===")
    step2_content = {
        "content": [
            {
                "section": "Prompting Basics",
                "blocks": [
                    {"block_id": "s1-b1", "type": "heading", "text": "What is a prompt?"},
                    {"block_id": "s1-b2", "type": "paragraph", "text": "A prompt is the input you give an LLM."},
                    {"block_id": "s1-b3", "type": "bullet_list", "text": ["Be specific", "Give examples", "Set format"]},
                    {"block_id": "s1-b4", "type": "code", "text": "prompt = 'Summarize this in 3 bullets: ...'"},
                ],
            }
        ]
    }
    print(normalize_content_for_sections(["Prompting Basics"], step2_content))

    print("\n=== Test 7: normalize_content_for_sections — simple {section: text} dict ===")
    plain_content = {"Prompting Basics": "Covered zero-shot vs few-shot prompting with live examples."}
    print(normalize_content_for_sections(["Prompting Basics"], plain_content))

    print("\n=== Test 8: normalize_content_for_sections — no content at all ===")
    print(normalize_content_for_sections(["Prompting Basics"], None))

    print("\n=== Test 9: normalize_content_for_sections — unrecognized shape (shouldn't crash) ===")
    print(normalize_content_for_sections(["Prompting Basics"], ["some", "random", "list"]))

    print("\n=== Test 10: normalize_content_for_sections — section missing from Step 2 content ===")
    print(normalize_content_for_sections(["A Section Not In Step 2's Output"], step2_content))

    print("\n=== Test 11: generate_labs plumbing (mocked LLM + search, no real network) ===")
    import activities_generator as ag

    def fake_search_web(query, max_results=5):
        return [{"title": "Fake Kaggle Notebook", "snippet": "A relevant exercise.", "url": "https://kaggle.com/fake"}]

    def fake_ask_llm_for_json(prompt):
        # Returns a minimal valid CODING-shaped reply regardless of prompt content —
        # this test only checks that generate_one_lab/generate_labs wire things
        # together correctly, not prompt quality (that needs the real API).
        return {
            "title": "Mock Lab",
            "instructions": "Do the thing.",
            "trainee_notebook_cells": [{"cell_type": "code", "content": "# TODO"}],
            "solution_notebook_cells": [{"cell_type": "code", "content": "print('done')"}],
            "instructor_notes": "Watch for X.",
            "suggested_platforms": [{"name": "Kaggle", "url": "https://kaggle.com/fake", "why_it_fits": "..."}],
        }

    ag.search_web = fake_search_web
    ag.ask_llm_for_json = fake_ask_llm_for_json

    result = ag.generate_labs(
        title="AI Coding Assistants Workshop",
        lab_contexts=lab_contexts,  # from Test 1
        confirmed_lab_types={2: "coding", 5: "coding"},
        content=step2_content,
        customization_notes={2: "make it easier for beginners"},
    )
    for lab in result["labs"]:
        print(lab)

    print("\n=== Test 12: generate_labs raises clearly when a lab_type wasn't confirmed ===")
    try:
        ag.generate_labs(
            title="AI Coding Assistants Workshop",
            lab_contexts=lab_contexts,
            confirmed_lab_types={2: "coding"},  # missing index 5 on purpose
        )
    except ValueError as e:
        print("Correctly caught missing confirmation:", e)