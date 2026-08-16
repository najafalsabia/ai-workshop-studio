"""
Local SQLite storage for finished workshops — so a completed workshop
package (plan + content + labs + quiz) never gets lost between sessions,
and past workshops can be browsed and reopened later, not just the very
last one (unlike temp_session_state.json, which only ever holds one).

This is LOCAL-ONLY by design: one file (workshops.db) sitting next to the
other Backend files on this machine. No server, no account, no network —
sqlite3 is part of Python's standard library. If the project ever needs
shared/multi-user storage later, that's a genuinely different piece of
infrastructure (a hosted database) — this module intentionally doesn't
try to be that.

No LLM calls here — pure storage, same role as notebook_builder.py /
quiz_doc_builder.py / kahoot_export.py, just for "save the whole
workshop" instead of "export one file".
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

from config import WORKSHOP_DB_PATH as DB_PATH


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """
    Creates the workshops table if it doesn't exist yet. Safe to call every
    time before any operation below — CREATE TABLE IF NOT EXISTS is a
    no-op on an already-initialized database, so callers never need to
    worry about "did I set this up yet".
    """
    conn = get_connection(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workshops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            audience TEXT,
            age TEXT,
            duration TEXT,
            created_at TEXT NOT NULL,
            plan_json TEXT,
            content_json TEXT,
            labs_json TEXT,
            quiz_json TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_workshop(
    title: str,
    audience: str,
    age: str,
    duration: str,
    plan: dict,
    content: dict,
    labs: dict | None,
    quiz: dict,
    db_path: Path = DB_PATH,
) -> int:
    """
    Saves one COMPLETE workshop as a new row (never overwrites an existing
    one — every save is a new entry, so nothing is lost if you save
    twice). Meant to be called once, at the point the trainer has an
    approved quiz and is ready to export (Step 7) — not after every
    intermediate edit.

    labs may be None (a workshop with no labs is still valid to save).
    Returns the new row's id, so the caller can immediately load/reference
    this exact saved workshop afterward.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute(
        """
        INSERT INTO workshops
            (title, audience, age, duration, created_at, plan_json, content_json, labs_json, quiz_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            audience,
            age,
            duration,
            datetime.now().isoformat(timespec="seconds"),
            json.dumps(plan, ensure_ascii=False),
            json.dumps(content, ensure_ascii=False),
            json.dumps(labs, ensure_ascii=False) if labs is not None else None,
            json.dumps(quiz, ensure_ascii=False),
        ),
    )
    conn.commit()
    workshop_id = cursor.lastrowid
    conn.close()
    return workshop_id


def list_workshops(db_path: Path = DB_PATH) -> list[dict]:
    """
    Returns a lightweight summary of every saved workshop, most recent
    first — just enough to show a picker/history list (id, title,
    audience, duration, created_at). Does NOT include the full JSON
    blobs, since a history list showing 20 workshops shouldn't have to
    load 20 full slide decks into memory — call load_workshop(id) to get
    the full data for one specific workshop.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT id, title, audience, duration, created_at FROM workshops ORDER BY created_at DESC, id DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def load_workshop(workshop_id: int, db_path: Path = DB_PATH) -> dict:
    """
    Loads ONE full workshop by id — every field, JSON blobs parsed back
    into real dicts, ready to drop straight into session state.

    Raises ValueError (with the id in the message) if no workshop with
    that id exists, rather than returning None and letting a caller
    silently treat a missing workshop as an empty one.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM workshops WHERE id = ?", (workshop_id,)).fetchone()
    conn.close()

    if row is None:
        raise ValueError(f"No workshop found with id={workshop_id}.")

    return {
        "id": row["id"],
        "title": row["title"],
        "audience": row["audience"],
        "age": row["age"],
        "duration": row["duration"],
        "created_at": row["created_at"],
        "plan": json.loads(row["plan_json"]) if row["plan_json"] else None,
        "content": json.loads(row["content_json"]) if row["content_json"] else None,
        "labs": json.loads(row["labs_json"]) if row["labs_json"] else None,
        "quiz": json.loads(row["quiz_json"]) if row["quiz_json"] else None,
    }


def delete_workshop(workshop_id: int, db_path: Path = DB_PATH) -> None:
    """Permanently removes one saved workshop by id. No confirmation here — the caller's UI should ask first."""
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("DELETE FROM workshops WHERE id = ?", (workshop_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    # Self-test — uses a throwaway temp database file (never touches the
    # real workshops.db), no API keys or network needed.

    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = Path(tmp_dir) / "test_workshops.db"

        mock_plan = {"learning_objectives": ["Learn X"], "outline": [{"section": "Intro", "duration_minutes": 30}]}
        mock_content = {"slides": [{"slide_number": 1, "slide_title": "Welcome"}]}
        mock_labs = {"labs": [{"title": "Lab 1", "lab_type": "coding"}]}
        mock_quiz = {"quiz": {"title": "Final Quiz", "questions": [{"question": "Q1?", "options": ["a", "b", "c", "d"], "correct_answer": "a", "difficulty": "easy"}]}}

        print("=== Test 1: save_workshop returns a new id ===")
        id1 = save_workshop(
            "Beyond Syntax", "CS students", "18-24", "3 hours",
            mock_plan, mock_content, mock_labs, mock_quiz, db_path=test_db
        )
        print(f"saved with id={id1}")
        assert id1 == 1

        print("\n=== Test 2: saving again creates a SECOND row, doesn't overwrite ===")
        id2 = save_workshop(
            "A Different Workshop", "High schoolers", "15-18", "2 hours",
            mock_plan, mock_content, None, mock_quiz, db_path=test_db
        )
        print(f"saved with id={id2}")
        assert id2 == 2 and id2 != id1

        print("\n=== Test 3: list_workshops shows both, most recent first ===")
        summaries = list_workshops(db_path=test_db)
        for s in summaries:
            print(" ", s)
        assert len(summaries) == 2
        assert summaries[0]["id"] == id2  # most recent first

        print("\n=== Test 4: load_workshop returns the full data, JSON parsed back to dicts ===")
        loaded = load_workshop(id1, db_path=test_db)
        print(" title:", loaded["title"])
        print(" plan:", loaded["plan"])
        print(" labs:", loaded["labs"])
        assert loaded["plan"] == mock_plan
        assert loaded["quiz"] == mock_quiz
        assert loaded["labs"] == mock_labs

        print("\n=== Test 5: a workshop saved with labs=None loads back as None (not a crash) ===")
        loaded2 = load_workshop(id2, db_path=test_db)
        assert loaded2["labs"] is None
        print(" labs:", loaded2["labs"], "(correct)")

        print("\n=== Test 6: loading a non-existent id raises a clear error ===")
        try:
            load_workshop(9999, db_path=test_db)
            raise AssertionError("Should have raised ValueError")
        except ValueError as e:
            print(" Correctly raised:", e)

        print("\n=== Test 7: delete_workshop removes exactly one row ===")
        delete_workshop(id1, db_path=test_db)
        remaining = list_workshops(db_path=test_db)
        print(" remaining:", [w["id"] for w in remaining])
        assert len(remaining) == 1 and remaining[0]["id"] == id2

        print("\n=== Test 8: the .db file actually exists on disk ===")
        assert os.path.isfile(test_db)
        print(" file exists:", test_db)

    print("\nAll self-tests passed.")
