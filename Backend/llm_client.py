"""
This file has ONE job: send text (a "prompt") to the AI model, and get back
its answer as clean data (JSON) instead of a messy paragraph.
"""

import os
import json
import time
import requests

from config import OPENAI_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, LLM_RETRY_DELAY_SECONDS

def ask_llm_for_json(prompt: str) -> dict:
    """
    Sends `prompt` to OpenAI and returns the response parsed as a Python
    dict/list.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No OPENAI_API_KEY found. Did you create your .env file? (Step 6 in README)"
        )

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    max_retries = LLM_MAX_RETRIES
    retry_delay = LLM_RETRY_DELAY_SECONDS

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                json={
                    "model": OPENAI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    # GPT-5-family models reject "max_tokens" outright (400
                    # Bad Request: "Unsupported parameter") — they require
                    # "max_completion_tokens" instead. Older models (gpt-4o-mini
                    # etc.) accept max_completion_tokens too, so this is safe
                    # either way, not just for GPT-5.
                    "max_completion_tokens": LLM_MAX_TOKENS,
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            break
        except (requests.exceptions.RequestException, Exception) as e:
            is_transient = True
            # Check if HTTP status code indicates a non-transient user error
            if hasattr(e, "response") and e.response is not None:
                if e.response.status_code in [400, 401, 403, 404]:
                    is_transient = False

            if is_transient and attempt < max_retries:
                time.sleep(retry_delay * attempt)
                continue
            else:
                raise e

    data = response.json()
    candidate = data["choices"][0]
    finish_reason = candidate.get("finish_reason")
    raw_text = candidate["message"]["content"]

    # Stripping fences if present
    cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        hint = (
            "\n\nHINT: finish_reason was 'length' — the response was cut off before finishing."
            if finish_reason == "length"
            else ""
        )
        raise RuntimeError(
            f"Couldn't parse OpenAI's reply as JSON (finish_reason: {finish_reason!r}).{hint}\n\n"
            f"--- Raw reply (first 2000 chars) ---\n{raw_text[:2000]}"
        ) from e


def ask_llm_to_verify_image(image_bytes: bytes, concept_text: str) -> bool:
    """
    Sends an image + a text description to OpenAI's vision-capable chat
    endpoint and asks a single yes/no question: does this image actually,
    genuinely depict the given concept? Used to reject search results
    that matched on SURROUNDING PAGE TEXT but aren't actually relevant
    images (e.g. a stack of unrelated business books on a page that
    happens to mention "data quality").

    Returns True only on an explicit "yes" — any failure (network error,
    bad response, timeout) returns False, since "couldn't verify" should
    be treated the same as "didn't pass": reject and try the next
    candidate rather than risk shipping an unrelated image.

    Bounded by design: this is called at most once per SEARCH CANDIDATE
    (already capped at 3 per concept — see download_image_for_concept),
    never in an open-ended retry loop.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return False

    import base64
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    prompt_text = (
        f'Does this image genuinely, visually depict or clearly relate to: "{concept_text}"? '
        "Answer strictly based on what is ACTUALLY VISIBLE in the image, not what a webpage "
        "containing it might have been about. Reply with ONLY this JSON, nothing else: "
        '{"relevant": true or false}'
    )

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": OPENAI_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}},
                    ],
                }],
                "response_format": {"type": "json_object"},
                # GPT-5-family models are reasoning models — they spend part
                # of the token budget on invisible internal "reasoning"
                # before writing the actual answer. With a tiny budget (the
                # 50 this used to be), the model can burn the ENTIRE budget
                # on reasoning and return a completely empty response,
                # which is why this was failing on almost every call. Fix:
                # give it real room to both think AND answer, and turn
                # reasoning effort down since this is a simple yes/no
                # judgment, not a task that needs deep reasoning.
                "max_completion_tokens": 300,
                "reasoning_effort": "minimal",
            },
            timeout=15,  # short — this is a quick yes/no check, not a generation call
        )
        response.raise_for_status()
        data = response.json()
        raw_text = data["choices"][0]["message"]["content"]
        if not raw_text.strip():
            # An empty (not malformed — genuinely empty) response from a
            # reasoning model almost always means it spent the whole token
            # budget on internal reasoning and had nothing left to write
            # the actual answer with. Bumping max_completion_tokens further
            # is the fix if this starts happening again.
            print("⚠️  Image relevance check got an EMPTY response (likely reasoning tokens used the whole budget) — treating as not relevant.")
            return False
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return bool(json.loads(cleaned).get("relevant", False))
    except Exception as e:
        print(f"⚠️  Image relevance check failed ({e}) — treating as not relevant.")
        return False


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    test_prompt = 'Reply with ONLY this JSON, nothing else: {"status": "it works"}'
    print(ask_llm_for_json(test_prompt))