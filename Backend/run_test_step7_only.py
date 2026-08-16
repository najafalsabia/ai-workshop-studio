"""
Test Step 7 (the final quality checklist) BY ITSELF — no need to
re-run Step 0 -> 1 -> 2 -> 4 -> 5 first. This reuses the plan, content,
labs, and quiz that are already sitting in temp_session_state.json (the
app saves this automatically after every run), so testing Step 7 costs
ONE API call instead of six or seven.

Run this from Backend/, after you've gone through the app at least once
so temp_session_state.json exists with real data in it:

    python3 run_test_step7_only.py

To test against a DIFFERENT saved session, pass its path:

    python3 run_test_step7_only.py path/to/other_session_state.json
"""

import json
import sys
from dotenv import load_dotenv

load_dotenv()

from quality_checklist import run_quality_checklist

STATE_FILE = sys.argv[1] if len(sys.argv) > 1 else "temp_session_state.json"

if __name__ == "__main__":
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(
            f"Couldn't find {STATE_FILE}. Run the app (streamlit run app.py) at least "
            "once, through Step 5, so it has real data saved — or pass a different "
            "saved session file as an argument."
        )
        raise SystemExit(1)

    required = ["chosen_title", "plan_result", "content_result"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        print(f"{STATE_FILE} is missing required data: {missing}. Run the app further before testing Step 7.")
        raise SystemExit(1)

    print(f"Loaded saved session from {STATE_FILE}")
    print(f"  -> title: {data['chosen_title']}")
    print(f"  -> outline sections: {len(data['plan_result'].get('outline', []))}")
    print(f"  -> slides: {len(data['content_result'].get('slides', []))}")
    print(f"  -> labs: {len(data.get('labs_result', {}).get('labs', [])) if data.get('labs_result') else 0}")
    print(f"  -> quiz questions: {len(data.get('quiz_result', {}).get('quiz', {}).get('questions', [])) if data.get('quiz_result') else 0}")

    print("\nRunning Step 7 (one API call)...")
    result = run_quality_checklist(
        title=data["chosen_title"],
        plan=data["plan_result"],
        content=data["content_result"],
        labs_result=data.get("labs_result"),
        quiz_result=data.get("quiz_result"),
    )

    print(f"\n=== OVERALL STATUS: {result['overall_status'].upper()} ===")

    if result["automated_issues"]:
        print("\n--- Automated structural issues (code-checked facts) ---")
        for issue in result["automated_issues"]:
            print(f"  ⚠️  {issue}")
    else:
        print("\n(no automated structural issues found)")

    print("\n--- Judgment-based review ---")
    for check in result["checks"]:
        status_icon = "✅" if check["status"] == "pass" else "❌"
        print(f"\n{status_icon} {check['category']}: {check['status']}")
        for issue in check.get("issues", []):
            print(f"    - {issue}")

    print(f"\n--- Summary ---\n{result['summary']}")