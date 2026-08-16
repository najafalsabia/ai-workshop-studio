"""
Step 2 (Fixed): Slide Content Generator with Sources.

Searches the web per outline section, then generates slides mapped to
layouts (roadmap_slide, columns_3_slide, timeline_slide, content_slide)
with speaker notes and source citations.

Changes from the previous version, and why:
  1. Style rules (word/bullet counts) now come from ONE place per call,
     not two conflicting blocks — the model no longer has to guess which
     number to follow.
  2. Sources ask for a paraphrased takeaway, not a word-perfect quote —
     the model only ever sees a short search snippet, so demanding an
     "exact quote" from it was asking the model to fabricate precision
     it doesn't have.
  3. Slide count scales with section duration instead of being fixed at 2.
  4. A short delay between sections avoids tripping the free-tier rate
     limit partway through a run.
  5. Each section is wrapped in try/except with one retry — one bad
     response no longer throws away every slide generated before it.
  6. The JSON schema is now built per-call for the chosen layout only,
     instead of showing the model four options with inline comments in
     the same block it's supposed to output valid JSON into.
  7. Layout schema examples now use instructional placeholders (e.g.
     "<specific visual concept for THIS column>") instead of copyable
     literal words like "Concept" — some models were literally echoing
     the example word back as the actual output instead of writing real
     content, which is why placeholders were showing up as generic
     single words on rendered slides.
"""

import sys
# Reconfigure stdout/stderr to support printing Arabic Unicode characters and emojis in Windows shell
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from search_tool import search_web
from llm_client import ask_llm_for_json
from config import CONTENT_GEN_RETRY_DELAY_SECONDS, CONTENT_GEN_BETWEEN_SECTIONS_DELAY_SECONDS

SLIDE_TYPE_MAPPING = {
    "opening": ["roadmap_slide"],
    "explain": ["columns_3_slide", "timeline_slide", "content_slide"],
    "lab": ["content_slide"],
    "break": ["content_slide"],
    "qna": ["content_slide"],
    "competition": ["content_slide"],
    "closing": ["content_slide"],
}

# Search phrasing tuned per role — "academic documentation" doesn't help
# a hands-on lab section, and a break doesn't need sourcing at all.
SEARCH_QUERY_SUFFIX = {
    "opening": "workshop agenda structure best practices",
    "explain": "curriculum best practices academic documentation",
    "lab": "hands-on exercise ideas tutorial",
    "qna": "common questions discussion topics",
    "competition": "quiz game activity ideas",
    "closing": "next steps further learning resources",
    "break": None,  # no search needed — break slides don't cite sources
}

# Single source of truth for word/bullet counts per style. The prompt
# below reads directly from this dict, so there's no second hardcoded
# rule anywhere else that could contradict it.
STYLE_RULES = {
    "Clean & Minimal": {
        "paragraph_words": "5-8 words",
        "bullets": "exactly 3 bullet points",
        "extra": "Keep the design extremely clean, professional, and corporate.",
    },
    "Bold & Impactful": {
        "paragraph_words": "5-7 words, statement-style",
        "bullets": "exactly 3 bullet points, punchy phrasing",
        "extra": "Headings use strong action-oriented words. Use large numbers or emojis as visual anchors.",
    },
    "Visual & Diagram-heavy": {
        "paragraph_words": "5-8 words",
        "bullets": "exactly 2 bullet points",
        "extra": "Every slide MUST include an image_placeholder block with a detailed description of a flowchart, process map, or architecture diagram.",
    },
    "Data & Research": {
        "paragraph_words": "8-12 words, must include a specific statistic or metric",
        "bullets": "exactly 3 bullet points, each a specific data point",
        "extra": "Academic/research paper aesthetic. Citations must be prominent.",
    },
    "Interactive & Workshop": {
        "paragraph_words": "5-8 words",
        "bullets": "3-4 checklist-style bullet points",
        "extra": "Every slide MUST include an activity block with a hands-on 'Try it' task.",
    },
}
DEFAULT_STYLE = "Clean & Minimal"

# The block schema for each layout, kept separate from the prompt's
# instruction text so there's exactly one schema shown per call — the
# one matching whichever layout the model actually picks.
#
# NOTE: values are written as <instructional placeholders>, not literal
# copyable example words. A previous version used plain words like
# "Concept" or "Diagram details" here, and some model responses just
# echoed those words back verbatim as the actual slide content instead
# of writing something real — that's why slides were showing up with
# identical generic "Concept" labels on every column.
LAYOUT_SCHEMAS = {
    "roadmap_slide": '''{"blocks": [{"type": "roadmap", "items": [{"title": "<specific block title>", "detail": "<specific detail for this block>"}]}]}''',
    "columns_3_slide": '''{"blocks": [{"type": "paragraph", "text": "<one intro sentence>"}, {"type": "columns_3", "columns": [{"heading": "<this column's specific heading>", "text": "<this column's specific detail>", "image_placeholder": "<a specific visual concept for THIS column, e.g. 'padlock icon representing access control' — never a generic word like Concept or Icon>"}]}]}''',
    "timeline_slide": '''{"blocks": [{"type": "timeline", "events": [{"title": "<specific event>", "date": "<specific date/era>", "text": "<specific detail>"}]}, {"type": "image_placeholder", "text": "<a specific, detailed description of the diagram this timeline needs>"}]}''',
    "content_slide": '''{"blocks": [{"type": "heading", "text": "<specific short heading>"}, {"type": "paragraph", "text": "<one specific sentence>"}, {"type": "bullet_list", "items": ["<specific item>", "<specific item>"]}, {"type": "image_placeholder", "text": "<a specific, detailed description of the diagram this section needs>"}]}''',
}

CANONICAL_EXAMPLE_PROMPT = """A workshop titled "{title}" needs ONE consistent example model/library/tool \
that every section's slides will reference when a concrete example is needed — this prevents different \
sections picking different, sometimes technically incompatible examples (e.g. mixing a causal/generative \
model like distilgpt2 with an unrelated encoder model like distilbert in the same walkthrough).

Learning objectives:
{objectives}

Pick ONE real, well-known, small/beginner-friendly example (a specific model name, library, or tool) that \
fits ALL of these objectives well enough to be reused throughout. If the workshop doesn't need one \
consistent technical example (e.g. it's a conceptual/non-technical topic), reply with an empty string.

Reply with ONLY this JSON, nothing else:
{{"canonical_example": "e.g. distilgpt2 (Hugging Face Transformers)", "reason": "one short sentence"}}
"""


def determine_canonical_example(title: str, learning_objectives: list[str]) -> str:
    """
    One LLM call, made ONCE per workshop (not per section) — decides on a
    single consistent example model/library/tool for the whole content
    generation pass to reference, instead of letting each independently-
    generated section pick its own (which is what previously produced
    slides that mixed technically incompatible examples, like citing both
    distilgpt2 and distilbert as if interchangeable).

    Returns an empty string if no single example fits (fine for
    non-technical workshops) or if this call fails for any reason — a
    missing canonical example just means sections keep picking their own,
    same as before this feature existed, not a hard failure.
    """
    try:
        prompt = CANONICAL_EXAMPLE_PROMPT.format(
            title=title, objectives="\n".join(f"- {o}" for o in learning_objectives)
        )
        result = ask_llm_for_json(prompt)
        return result.get("canonical_example", "") or ""
    except Exception as e:
        print(f"⚠️  Could not determine a canonical example ({e}) — sections will pick their own as before.")
        return ""


def format_canonical_example_block(canonical_example: str) -> str:
    if not canonical_example:
        return "(No single canonical example was set for this workshop — use your own best judgment, staying consistent within THIS section at least.)"
    return (
        f'This workshop has ONE agreed-upon example to reuse everywhere a concrete technical example is '
        f'needed: "{canonical_example}". If this section needs to name a specific model/library/tool as an '
        f"example, use THIS one — don't introduce a different, potentially incompatible example."
    )


CONTENT_PROMPT_TEMPLATE = """You are creating PRESENTATION SLIDES for the section: "{section_name}".

STYLE RULES FOR THIS SLIDE (follow these exactly — they are the only word/bullet counts that apply):
- Paragraph blocks: {paragraph_words}
- Bullet lists: {bullets}
- {style_extra}

LAYOUT: use "{chosen_layout}". Its blocks array must follow this exact shape:
{layout_schema}

Any "image_placeholder" text must be a specific, concrete description tied to
THIS exact content (e.g. "padlock icon over a code file, representing secret
scanning"). Never write a generic single word like "Concept", "Icon", or
"Diagram" — that gives no one enough information to actually create the image.

REAL TOOLS ONLY — CRITICAL:
- If you name a specific product, tool, framework, or platform, it MUST be a
  real, well-known, verifiable one (e.g. OWASP ZAP, Burp Suite, Postman,
  Semgrep, Snyk, GitHub Copilot — not names you construct yourself).
- NEVER invent a tool/product name that sounds real but isn't (e.g. don't
  make up something like "SingGuard" or "NiyamAI"). If you need to describe
  a technique, mechanism, or pattern that doesn't have one specific famous
  tool behind it, describe the TECHNIQUE itself in plain language instead of
  giving it an invented brand name — a made-up-sounding tool name is worse
  than no tool name, because trainees may think it's something they can go
  look up or install.

STAY CONSISTENT WITH THE REST OF THE WORKSHOP — CRITICAL:
{canonical_example_block}

DEPTH GOES IN speaker_notes, NOT ON THE SLIDE:
- The visible slide text (paragraph/bullets above) must stay within the
  word/bullet limits — slides are not meant to be read as documents.
- BUT speaker_notes is where the real teaching material goes: for a
  hands-on/technical section, include a CONCRETE example the trainer can
  actually use out loud — a short real prompt template, a code/command
  snippet, a specific step sequence, or a worked example tied to this
  section's exact topic. Write 2-4 sentences here, not one throwaway line —
  this is what lets the trainer actually teach the concept instead of just
  reading the slide title.

DO NOT PROMISE ACTIVITIES YOU AREN'T DESCRIBING RIGHT NOW:
- Only reference a hands-on activity, lab, or exercise BY NAME if you are
  currently writing the content for that exact activity. Don't have an
  explanatory section promise "you'll practice X, Y, and Z later" unless
  you know for certain those specific labs exist elsewhere in this
  workshop — an unfulfilled promise on a slide is worse than no promise,
  since it sets an expectation the workshop package may not actually meet.

SOURCES:
- Base every factual claim on the search results below.
- For each source, give a short paraphrased takeaway of what it says — in
  your own words, not a word-for-word quote (you're only seeing a short
  excerpt, so a claimed "exact quote" would likely be wrong).
- If the search results below are empty or don't support a claim, don't
  invent a source for it — just don't cite one for that point.

SEARCH RESULTS:
{search_results}

{mimic_instruction}

Generate {num_slides} slides for this section, slide numbers starting at {slide_start}.

Reply with ONLY this JSON, nothing else — no comments, no extra text:
{{
  "slides": [
    {{
      "slide_number": {slide_start},
      "section": "{section_name}",
      "slide_title": "Short title (3-5 words)",
      "content_type": "{chosen_layout}",
      "blocks": [ ... matching the layout shape above ... ],
      "sources": [
        {{"author": "...", "year": "...", "title": "...", "url": "https://...", "takeaway": "one-sentence paraphrase of the relevant point"}}
      ],
      "speaker_notes": "2-4 sentences: the concrete teaching material for this slide (a real example, snippet, or worked walkthrough — see the DEPTH rule above)"
    }}
  ]
}}
"""


def get_role_from_section(section: dict) -> str:
    role = section.get("role")
    if role:
        return role.lower()

    name = section.get("section", "").lower()
    desc = section.get("description", "").lower()
    if "intro" in name or "welcome" in name or "opening" in name:
        return "opening"
    elif any(k in name or k in desc for k in ["lab", "exercise", "practice", "hands-on", "activity"]):
        return "lab"
    elif "break" in name or "rest" in name:
        return "break"
    elif "q&a" in name or "question" in name or "discussion" in name:
        return "qna"
    elif "quiz" in name or "competition" in name or "game" in name:
        return "competition"
    elif "close" in name or "wrap" in name or "conclusion" in name or "thank" in name:
        return "closing"
    else:
        return "explain"


def format_section_search_results(results: list[dict]) -> str:
    if not results:
        return "No web search results available — do not cite any sources for this section."
    lines = []
    for idx, r in enumerate(results, 1):
        lines.append(f"Source [{idx}]:\n- Title: {r['title']}\n- URL: {r['url']}\n- Excerpt: {r['snippet']}\n")
    return "\n".join(lines)


def num_slides_for_duration(duration_minutes: int) -> int:
    """
    Scale slide count to how long the section actually is.
    Rule of thumb: ~1 slide per 10 minutes of content, uncapped at 8 per
    section so that longer workshops naturally produce 25-40+ slides total
    rather than being cut off at ~20.
    """
    return max(2, min(8, round(duration_minutes / 10)))


GENERIC_PLACEHOLDER_WORDS = {
    "concept", "icon", "image", "diagram", "visual", "graphic", "picture",
}


def has_generic_placeholder(slides: list[dict]) -> bool:
    """
    Checks every image_placeholder text (including nested ones inside
    columns_3 blocks) for generic single-word filler like "Concept" or
    "Icon". The prompt instruction alone wasn't reliably preventing this
    on columns_3_slide specifically — this is the code-side backstop,
    same idea as the duration-sum check in plan_builder.py: don't just
    trust the prompt held, verify it.
    """
    def is_generic(text: str) -> bool:
        words = text.strip().split()
        return len(words) <= 1 or text.strip().lower() in GENERIC_PLACEHOLDER_WORDS

    for slide in slides:
        for block in slide.get("blocks", []):
            if block.get("type") == "image_placeholder" and is_generic(block.get("text", "")):
                return True
            if block.get("type") == "columns_3":
                for col in block.get("columns", []):
                    if is_generic(col.get("image_placeholder", "")):
                        return True
    return False


def generate_slides_for_section(
    section: dict,
    title: str,
    slide_start: int,
    default_style: str,
    section_styles: dict | None,
    mimic_example: str | None,
    uploaded_content: str | None = None,
    canonical_example: str = "",
) -> list[dict]:
    """Builds and generates the slides for ONE outline section. Raises on failure —
    caller decides whether to retry or skip."""
    sec_name = section.get("section", "Introduction")
    sec_desc = section.get("description", "")
    sec_dur = section.get("duration_minutes", 15)
    role = get_role_from_section(section)

    # ── BREAK SLIDES ─────────────────────────────────────────────────────────
    # Break sections don't need LLM content — just a simple placeholder slide.
    if role == "break":
        is_arabic = any(ord(c) > 0x600 for c in title)
        break_title   = "استراحة" if is_arabic else "Break Time"
        break_body    = "10 - 15 دقائق" if is_arabic else "10 – 15 minutes"
        return [{
            "slide_number": slide_start,
            "section": sec_name,
            "slide_title": break_title,
            "content_type": "content_slide",
            "slide_style": (section_styles or {}).get(sec_name, default_style),
            "blocks": [
                {"type": "heading",   "text": break_title},
                {"type": "paragraph", "text": break_body},
            ],
            "sources": [],
            "speaker_notes": "Break time — participants resume in 10–15 minutes.",
        }]

    search_suffix = SEARCH_QUERY_SUFFIX.get(role)
    if search_suffix:
        # Keep this tight: title + suffix carry the real signal. Adding
        # sec_desc on top (as a previous version did) diluted the query
        # into a long run-on blob, which in practice let overly generic
        # suffixes (like "workshop wrap up") pull in an unrelated result —
        # a personal social media post, in one real case — that the LLM
        # then built content on top of. Fewer, sharper terms > more terms.
        search_results = search_web(f"{title} {search_suffix}", max_results=4)
    else:
        search_results = []  # e.g. break slides — no sourcing needed

    style_name = (section_styles or {}).get(sec_name, default_style)
    style = STYLE_RULES.get(style_name, STYLE_RULES[DEFAULT_STYLE])

    allowed_layouts = SLIDE_TYPE_MAPPING.get(role, ["content_slide"])
    chosen_layout = allowed_layouts[0]  # deterministic choice; swap for LLM-chosen if you want variety

    mimic_instruction = ""
    if mimic_example:
        mimic_instruction = (
            "The user provided example slides to mimic in tone and block structure "
            f"(but still follow the layout schema above exactly):\n{mimic_example}"
        )
    if uploaded_content:
        mimic_instruction += (
            "\nGenerate the slide content strictly based on this custom source reference text:\n"
            f"{uploaded_content}\n"
        )

    prompt = CONTENT_PROMPT_TEMPLATE.format(
        section_name=sec_name,
        paragraph_words=style["paragraph_words"],
        bullets=style["bullets"],
        style_extra=style["extra"],
        chosen_layout=chosen_layout,
        layout_schema=LAYOUT_SCHEMAS[chosen_layout],
        search_results=format_section_search_results(search_results),
        mimic_instruction=mimic_instruction,
        num_slides=num_slides_for_duration(sec_dur),
        slide_start=slide_start,
        canonical_example_block=format_canonical_example_block(canonical_example),
    )

    result = ask_llm_for_json(prompt)
    slides = result.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError(f"LLM returned no usable slides for section '{sec_name}'")
    if has_generic_placeholder(slides):
        raise ValueError(
            f"Section '{sec_name}' returned a generic image_placeholder "
            "(e.g. 'Concept', 'Icon') despite the prompt instruction — retrying."
        )

    for slide in slides:
        slide["slide_style"] = style_name
    return slides


def generate_content_with_sources(
    title: str,
    learning_objectives: list[str],
    outline: list[dict],
    mimic_example: str = None,
    default_style: str = DEFAULT_STYLE,
    section_styles: dict = None,
    progress_callback=None,
    uploaded_content: str = None,
) -> dict:
    """
    Generate slide content with bounded concurrency. Independent sections
    are generated in parallel (3 workers) to avoid waiting for every LLM
    request and web search sequentially. If a section fails (bad JSON, empty
    result, etc.) it's retried once, then skipped with a warning — the rest
    of the deck still gets built instead of the whole run dying on one bad
    response.
    """
    all_slides = []
    failed_sections = []
    slide_counter = 1
    total_sections = len(outline)

    # Decided ONCE for the whole workshop, not per section — see
    # determine_canonical_example's docstring for why.
    canonical_example = determine_canonical_example(title, learning_objectives)
    if canonical_example:
        print(f"📌 Canonical example for this workshop: {canonical_example}")

    # Generate independent sections concurrently instead of waiting for
    # section 1 to finish before starting section 2, etc.
    #
    # Keep this deliberately small (3 workers). It gives a large speed-up
    # while avoiding a burst of requests that could trigger rate limits.
    max_workers = min(3, total_sections) if total_sections else 1

    # slide_start is only used inside the prompt. We calculate an expected
    # starting number here; after generation, slides are renumbered in their
    # original outline order below.
    expected_starts = {}
    expected_counter = 1
    for idx, section in enumerate(outline):
        expected_starts[idx] = expected_counter
        role = get_role_from_section(section)
        if role == "break":
            expected_counter += 1
        else:
            expected_counter += num_slides_for_duration(
                section.get("duration_minutes", 15)
            )

    def generate_one_section(idx: int, section: dict):
        sec_name = section.get("section", "Introduction")
        section_start = expected_starts[idx]

        for attempt in range(2):  # one retry
            try:
                slides = generate_slides_for_section(
                    section, title, section_start, default_style, section_styles,
                    mimic_example, uploaded_content, canonical_example,
                )
                return idx, sec_name, slides, None
            except Exception as e:
                if attempt == 0:
                    print(
                        f"⚠️  Section '{sec_name}' failed ({e}), retrying once..."
                    )
                    time.sleep(CONTENT_GEN_RETRY_DELAY_SECONDS)
                else:
                    print(
                        f"❌ Section '{sec_name}' failed twice, skipping it: {e}"
                    )
                    return idx, sec_name, [], str(e)

    completed = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(generate_one_section, idx, section)
            for idx, section in enumerate(outline)
        ]

        for future in as_completed(futures):
            idx, sec_name, section_slides, error = future.result()
            completed[idx] = (sec_name, section_slides, error)

            # Progress is reported when each section actually finishes.
            if progress_callback:
                finished = len(completed)
                progress_callback(finished, total_sections, sec_name)

    # Preserve the original outline order even though sections finished
    # concurrently.
    for idx, section in enumerate(outline):
        sec_name, section_slides, error = completed.get(
            idx,
            (
                section.get("section", "Introduction"),
                [],
                "section did not complete",
            ),
        )

        if error:
            failed_sections.append(sec_name)

        for slide in section_slides:
            slide["slide_number"] = slide_counter
            slide["section"] = sec_name
            all_slides.append(slide)
            slide_counter += 1

    if failed_sections:
        print(f"\n⚠️  {len(failed_sections)} section(s) skipped entirely: {', '.join(failed_sections)}")
        print("Consider re-running just those sections, or check if search/LLM quota was the cause.")

    return {"slides": all_slides, "failed_sections": failed_sections}


def generate_content(title: str, learning_objectives: list[str], outline: list[dict]) -> dict:
    """Wrapper matching the original function name/signature used elsewhere in the pipeline."""
    return generate_content_with_sources(title, learning_objectives, outline)