"""
This is YOUR main piece: Step 0, the idea + search agent.

What it does, in plain English:
  1. Takes the user's answers (audience, age, duration, goal, notes).
  2. Searches the web for current trends related to that.
  3. Asks the AI: "is this enough info, or should I search again?"
  4. Either searches once more with a sharper query, or moves on.
  5. Asks the AI to turn everything into 3-5 workshop title suggestions.

The PROMPT_TEMPLATE text below is the part you'll spend most of your time
editing this week. Changing the wording there changes the quality of the
output far more than changing any of the surrounding code.
"""

from search_tool import search_web
from llm_client import ask_llm_for_json
try:
    from workshop_db import list_workshops
except ImportError:
    # Handle import if run standalone in a different context
    def list_workshops(): return []

MAX_SEARCH_ROUNDS = 2  # hard cap so the agent can never loop forever

JUDGE_PROMPT_TEMPLATE = """You are helping plan a technical workshop.

User's request:
- Audience: {audience}
- Age: {age}
- Duration: {duration}
- Goal: {goal}
- Field / Domain: {field}
- Extra notes: {notes}

Here are web search results on this topic:
{search_results}

Question: is this enough information to suggest 3-5 strong, CURRENT, specific
workshop titles that are firmly inside the stated Field/Domain above?
Or would a more specific follow-up search on that field help?

Reply with ONLY this JSON, nothing else:
{{"enough_info": true or false, "next_search_query": "a sharper search query focused on the stated field, or empty string if enough_info is true"}}
"""

TITLES_PROMPT_TEMPLATE = """You are helping plan a technical workshop.

User's request:
- Audience: {audience}
- Age: {age}
- Duration: {duration}
- Goal: {goal}
- Field / Domain: {field}
- Extra notes: {notes}

Here is everything found from web research:
{search_results}

IMPORTANT: Every title you suggest MUST be directly and specifically about
the Field/Domain stated above: "{field}". Do NOT suggest titles about
unrelated domains even if those topics appear in the search results.

PAST WORKSHOPS GENERATED:
{past_workshops_list}

CRITICAL: To ensure variety and prevent duplicate work, you MUST NOT suggest titles, concepts, or topics that are identical or highly similar to any of the past workshops listed above.

Based on this research, suggest EXACTLY 5 workshop titles, no more, no fewer.
Each should be specific and reflect a CURRENT trend within the stated field,
not a generic textbook topic.

Reply with ONLY this JSON, nothing else:
{{"titles": [{{"title": "...", "why": "one sentence that names the specific source or study from the search results above — not a general trend claim"}}]}}
"""



def format_results(results: list[dict]) -> str:
    """Turns a list of search results into a readable text block for the prompt."""
    lines = []
    for r in results:
        lines.append(f"- {r['title']}: {r['snippet']} ({r['url']})")
    return "\n".join(lines) if lines else "(no results)"


def generate_titles(audience: str, age: str, duration: str, goal: str, notes: str) -> dict:
    """
    This is the function the rest of the app will call. Give it the user's
    answers, get back {"titles": [...]}.
    """
    # Extract the Workshop Field/Domain from notes (injected by app.py)
    field = ""
    notes_clean = notes
    for line in notes.splitlines():
        if line.startswith("Workshop Field/Domain:"):
            field = line.replace("Workshop Field/Domain:", "").strip()
            break

    # Build a focused search query that includes the field so results are on-topic
    if field:
        query = f"current trends {field} workshop for {audience}"
        if goal:
            query += f" {goal}"
    else:
        query = f"current trends {goal} workshop for {audience}"

    all_results = search_web(query)

    for round_num in range(MAX_SEARCH_ROUNDS):
        judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
            audience=audience,
            age=age,
            duration=duration,
            goal=goal,
            field=field or "(not specified)",
            notes=notes_clean,
            search_results=format_results(all_results),
        )
        judgment = ask_llm_for_json(judge_prompt)

        if judgment.get("enough_info") or not judgment.get("next_search_query"):
            break

        print(f"[round {round_num + 1}] Searching again: {judgment['next_search_query']}")
        more_results = search_web(judgment["next_search_query"])
        all_results.extend(more_results)

    # Retrieve past workshop titles
    try:
        past_workshops = list_workshops()
        past_titles = [w.get("title") for w in past_workshops if w.get("title")]
    except Exception:
        past_titles = []
    
    if past_titles:
        past_workshops_list = "\n".join(f"- {t}" for t in past_titles)
    else:
        past_workshops_list = "(no past workshops generated yet)"

    titles_prompt = TITLES_PROMPT_TEMPLATE.format(
        audience=audience,
        age=age,
        duration=duration,
        goal=goal,
        field=field or "(not specified)",
        notes=notes_clean,
        search_results=format_results(all_results),
        past_workshops_list=past_workshops_list
    )
    return ask_llm_for_json(titles_prompt)
