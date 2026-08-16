"""
Turns a generated coding lab's cells (plain JSON, from activities_generator's
generate_labs) into REAL .ipynb files on disk — ready to open directly in
Jupyter, VS Code, or Colab.

No LLM calls here at all — this is pure post-processing, same role as
Step 8's python-pptx export, just for notebooks instead of slides.

What it does, in plain English:
  1. Takes ONE generated "coding" lab (has trainee_notebook_cells and
     solution_notebook_cells — lists of {"cell_type": "markdown"|"code",
     "content": "..."}).
  2. Builds two real notebook files: one for the trainee (the scaffolded/
     incomplete version), one for the trainer (the full solution).
  3. Writes them to an output folder and returns their file paths, so
     whoever calls this (the web UI, later) can offer them as downloads.

This is meant to run automatically right after generate_labs() — the
person using the tool never sees or touches this code; they just get
.ipynb files ready to download.
"""

import os
import re

import nbformat
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell


def build_notebook(cells: list[dict]) -> nbformat.NotebookNode:
    """
    Turns a list of {"cell_type": "markdown"|"code", "content": "..."}
    dicts into an actual in-memory notebook object (nbformat's
    NotebookNode). Raises clearly on an unexpected cell_type rather than
    silently skipping it or guessing — a lab with a dropped cell is worse
    than one that fails loudly during generation/testing.
    """
    nb = new_notebook()
    for i, cell in enumerate(cells):
        cell_type = cell.get("cell_type")
        content = cell.get("content", "")
        if cell_type == "markdown":
            nb.cells.append(new_markdown_cell(content))
        elif cell_type == "code":
            nb.cells.append(new_code_cell(content))
        else:
            raise ValueError(
                f"Cell {i} has an unrecognized cell_type: {cell_type!r}. "
                "Expected 'markdown' or 'code'. Full cell: " + repr(cell)
            )
    return nb


def sanitize_filename(text: str, max_length: int = 60) -> str:
    """
    Turns a lab title into a safe filename: lowercased, spaces/punctuation
    replaced with underscores, trimmed to a reasonable length. Windows
    (which is what this project runs on) is picky about filename
    characters, so this strips anything that isn't a letter, digit,
    underscore, or hyphen.
    """
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return (text or "lab")[:max_length]


def save_lab_notebooks(lab: dict, output_dir: str = "generated_labs") -> dict:
    """
    Takes ONE generated "coding" lab (a single entry from generate_labs'
    "labs" list) and writes two real .ipynb files to `output_dir`: the
    trainee version and the solution version.

    Returns {"trainee_path": "...", "solution_path": "..."} — the actual
    file paths on disk, ready to hand to the person as downloads.

    Raises ValueError immediately (before writing anything) if this lab
    isn't a "coding" lab — interactive_tool labs have nothing to notebook-ify;
    callers should check lab["lab_type"] first or use
    save_all_lab_notebooks, which does that filtering automatically.
    """
    if lab.get("lab_type") != "coding":
        raise ValueError(
            f"save_lab_notebooks only works on 'coding' labs, got lab_type={lab.get('lab_type')!r}. "
            "Conceptual labs (questions/answers) don't have notebook cells to convert."
        )

    os.makedirs(output_dir, exist_ok=True)
    base_name = sanitize_filename(lab.get("title", "lab"))

    trainee_path = os.path.join(output_dir, f"{base_name}_trainee.ipynb")
    solution_path = os.path.join(output_dir, f"{base_name}_solution.ipynb")

    trainee_nb = build_notebook(lab["trainee_notebook_cells"])
    solution_nb = build_notebook(lab["solution_notebook_cells"])

    with open(trainee_path, "w", encoding="utf-8") as f:
        nbformat.write(trainee_nb, f)
    with open(solution_path, "w", encoding="utf-8") as f:
        nbformat.write(solution_nb, f)

    return {"trainee_path": trainee_path, "solution_path": solution_path}


def save_all_lab_notebooks(labs_result: dict, output_dir: str = "generated_labs") -> list[dict]:
    """
    The function meant to be called automatically right after
    generate_labs(). Runs save_lab_notebooks over every "coding" lab in
    generate_labs' output ({"labs": [...]}) and skips "interactive_tool" labs
    (nothing to notebook-ify there — those stay as questions/answers).

    Returns one entry per coding lab:
        [{"outline_index": i, "trainee_path": "...", "solution_path": "..."}]
    """
    results = []
    for lab in labs_result.get("labs", []):
        if lab.get("lab_type") == "coding":
            paths = save_lab_notebooks(lab, output_dir)
            results.append({"outline_index": lab["outline_index"], **paths})
    return results


if __name__ == "__main__":
    # Self-test — builds real .ipynb files from mock lab data (no API keys,
    # no network needed) and validates them with nbformat's own validator,
    # so this proves the FILES are actually well-formed, not just that the
    # code ran without crashing.

    import tempfile

    mock_labs_result = {
        "labs": [
            {
                "outline_index": 2,
                "lab_type": "coding",
                "title": "Refactoring AI-Generated Logic!",
                "trainee_notebook_cells": [
                    {"cell_type": "markdown", "content": "# Task: refactor the function below"},
                    {"cell_type": "code", "content": "def process(x):\n    # TODO: refactor this\n    pass"},
                ],
                "solution_notebook_cells": [
                    {"cell_type": "markdown", "content": "# Solution"},
                    {"cell_type": "code", "content": "def process(x):\n    return x.strip().lower()"},
                ],
            },
            {
                "outline_index": 5,
                "lab_type": "interactive_tool",  # should be SKIPPED — no cells to convert
                "title": "Architecture Concepts",
                "questions": [{"question": "...", "answer": "..."}],
            },
        ]
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        print("=== Test 1: save_all_lab_notebooks — skips the interactive_tool lab ===")
        results = save_all_lab_notebooks(mock_labs_result, output_dir=tmp_dir)
        print(results)
        assert len(results) == 1, "Expected only 1 result — the interactive_tool lab must be skipped"
        assert results[0]["outline_index"] == 2

        print("\n=== Test 2: the files actually exist on disk ===")
        for path_key in ("trainee_path", "solution_path"):
            path = results[0][path_key]
            exists = os.path.isfile(path)
            print(f"{path_key}: {path} -> exists={exists}")
            assert exists

        print("\n=== Test 3: the files are valid, well-formed notebooks (nbformat.validate) ===")
        for path_key in ("trainee_path", "solution_path"):
            with open(results[0][path_key], encoding="utf-8") as f:
                nb = nbformat.read(f, as_version=4)
            nbformat.validate(nb)  # raises if malformed
            print(f"{path_key}: valid, {len(nb.cells)} cells")

        print("\n=== Test 4: save_lab_notebooks rejects an interactive_tool lab directly ===")
        try:
            save_lab_notebooks(mock_labs_result["labs"][1], output_dir=tmp_dir)
            raise AssertionError("Should have raised ValueError")
        except ValueError as e:
            print("Correctly rejected:", e)

        print("\n=== Test 5: an unrecognized cell_type raises clearly ===")
        try:
            build_notebook([{"cell_type": "banana", "content": "..."}])
            raise AssertionError("Should have raised ValueError")
        except ValueError as e:
            print("Correctly rejected:", e)

        print("\n=== Test 6: filename sanitization handles punctuation/spaces safely ===")
        print(sanitize_filename("Refactoring AI-Generated Logic!"))

    print("\nAll self-tests passed.")
