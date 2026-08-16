"""
Central settings for the whole project. If you want to change a model,
a limit, a timing rule, or a path — change it HERE, not by hunting
through every Backend file that happens to use it.

Every other Backend file should import its constants from here instead of
re-declaring its own copy. Nothing in this file makes an API call or does
any work — it's just numbers and strings.
"""

from pathlib import Path

BACKEND_DIR = Path(__file__).parent

# ── LLM (text generation) ───────────────────────────────────────────────
# As of the latest update, TEXT generation (plans, content, labs, quiz
# questions, quality checks) runs on OpenAI, not Gemini — Gemini is now
# used ONLY for image generation (see IMAGE section below), and Tavily
# handles web search. Three separate services, three separate API keys.
OPENAI_MODEL = "gpt-5-mini"
LLM_MAX_TOKENS = 16000
LLM_TIMEOUT_SECONDS = 120
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY_SECONDS = 2.0  # multiplied by attempt number (2s, 4s, 6s...)

# ── Image generation (Imagen 3, via the Gemini API) ─────────────────────
IMAGEN_MODEL = "imagen-3.0-generate-002"
IMAGEN_ASPECT_RATIO = "4:3"
IMAGEN_TIMEOUT_SECONDS = 10

# ── Web search (Tavily) ──────────────────────────────────────────────────
SEARCH_EXCLUDED_DOMAINS = ["instagram.com", "tiktok.com", "facebook.com", "pinterest.com"]
SEARCH_DEFAULT_MAX_RESULTS = 5

# ── Content generation pacing (content_generator.py) ─────────────────────
# Deliberate delays between sections to stay under the LLM API's
# per-minute rate limit. This is the single biggest knob for "content
# generation feels slow" — for an 8-10 section workshop, these delays
# alone add up to 30-40+ seconds of pure waiting, on top of each
# section's actual API call time.
#
# If you're on a paid tier with a higher rate limit, LOWER these (or set
# to 0) for a real speed win. If you start seeing rate-limit errors,
# RAISE them instead.
CONTENT_GEN_RETRY_DELAY_SECONDS = 4
CONTENT_GEN_BETWEEN_SECTIONS_DELAY_SECONDS = 4

# ── Quiz (quiz_generator.py) ──────────────────────────────────────────────
QUIZ_MINUTES_PER_QUESTION = 15  # roughly one auto-generated question per 15 min of teaching
QUIZ_MIN_QUESTIONS = 6          # always a multiple of 3, so the three difficulty tiers split evenly
QUIZ_MAX_QUESTIONS = 30

# ── Activities / labs (activities_generator.py) ──────────────────────────
LAB_MINUTES_PER_HOUR_BLOCK = 60  # fallback grouping size for outlines with no role tags

# ── Kahoot export (kahoot_export.py) ──────────────────────────────────────
KAHOOT_TEMPLATE_PATH = BACKEND_DIR / "KahootQuizTemplate.xlsx"
KAHOOT_MAX_QUESTIONS = 100  # the official template has exactly 100 pre-numbered rows
KAHOOT_TIME_LIMIT_BY_DIFFICULTY = {"easy": 20, "medium": 30, "hard": 60}
KAHOOT_DEFAULT_TIME_LIMIT = 30

# ── Local history database (workshop_db.py) ───────────────────────────────
WORKSHOP_DB_PATH = BACKEND_DIR / "workshops.db"
