"""
This file has ONE job: given a search phrase, go find current info on the
web about it, and hand back a clean list of results.

You don't need to understand every line — you need to understand what goes
IN (a search phrase, like "AI workshop trends for university students") and
what comes OUT (a list of {title, snippet, url} results).
"""

import os
import requests

# Domains that have produced irrelevant citations in practice (personal
# social posts, reels) rather than substantive, checkable content, PLUS
# paid stock-photo sites — their preview images carry a visible watermark
# (e.g. "alamy.com", "Image ID: ...") and aren't actually licensed for use
# once embedded in a real deliverable, so they're excluded from image
# search results the same way as the social platforms below.
EXCLUDED_DOMAINS = [
    "instagram.com", "tiktok.com", "facebook.com", "pinterest.com",
    "alamy.com", "shutterstock.com", "istockphoto.com", "gettyimages.com",
    "dreamstime.com", "123rf.com", "depositphotos.com", "stock.adobe.com",
]


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Searches the web using Tavily and returns a simple list of results.

    Example:
        results = search_web("current trends in AI workshops 2026")
        # results = [{"title": "...", "snippet": "...", "url": "..."}, ...]
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No TAVILY_API_KEY found. Did you create your .env file? (Step 6 in README)"
        )

    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "exclude_domains": EXCLUDED_DOMAINS,
        },
        timeout=20,
    )
    response.raise_for_status()  # this will error loudly if something went wrong
    data = response.json()

    # We turn Tavily's response into a simpler shape that's easier to work with
    # everywhere else in the project.
    results = []
    for item in data.get("results", []):
        results.append(
            {
                "title": item.get("title", ""),
                "snippet": item.get("content", ""),
                "url": item.get("url", ""),
            }
        )
    return results


def search_images(query: str, max_results: int = 3) -> list[dict]:
    """
    Searches the web for REAL, relevant images using Tavily's image
    search (include_images) — the images come back tied to actual
    matching pages, not a blind tag lottery, so they're far more likely
    to relate to the query than a random-photo fallback service.

    Returns a list of {"url": ..., "description": ...} dicts, most
    relevant first. Some results may have an empty "description" if
    Tavily didn't have one for that image — that's normal, not an error.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No TAVILY_API_KEY found. Did you create your .env file? (Step 6 in README)"
        )

    response = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "include_images": True,
            "include_image_descriptions": True,
            "exclude_domains": EXCLUDED_DOMAINS,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    images = []
    for item in data.get("images", [])[:max_results]:
        # Tavily's image entries can come back as either a plain URL string
        # or a {"url": ..., "description": ...} dict depending on whether
        # include_image_descriptions was honored — handle both shapes
        # rather than assuming one and crashing on the other.
        if isinstance(item, dict):
            images.append({"url": item.get("url", ""), "description": item.get("description", "")})
        else:
            images.append({"url": item, "description": ""})
    return [img for img in images if img["url"]]


# This block only runs if you execute THIS file directly (python3 search_tool.py).
# It's a quick way to test just this one piece, in isolation, without the
# whole agent. Handy for debugging.
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    test_results = search_web("current trends in AI workshops for students")
    for r in test_results:
        print(r["title"], "-", r["url"])