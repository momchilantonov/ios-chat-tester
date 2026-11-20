"""Test plans: Markdown tables with the columns  Flow | User prompt | Expected | Result.

The planner agent writes them with an empty Result column; the tester fills Result with
`success`, `fail: <what happened>` or `blocked: <why>`. Each `##` section is one conversation.
"""

from __future__ import annotations

import re
from typing import Any

STATUSES = ("success", "fail", "blocked")
_PIPE = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> list[str]:
    inner = line.strip()
    inner = inner.removeprefix("|")
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip() for c in _PIPE.split(inner)]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return (
        bool(cells)
        and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c)
        and any(cells)
    )


def _columns(cells: list[str]) -> dict[str, int] | None:
    low = [c.lower() for c in cells]
    cols: dict[str, int] = {}
    for i, c in enumerate(low):
        if "flow" in c and "flow" not in cols:
            cols["flow"] = i
        elif ("prompt" in c or "user" in c) and "prompt" not in cols:
            cols["prompt"] = i
        elif "expected" in c and "expected" not in cols:
            cols["expected"] = i
        elif "result" in c and "result" not in cols:
            cols["result"] = i
    return cols if len(cols) == 4 else None


def parse_plan(text: str) -> dict[str, Any]:
    """Rows are numbered 1..N across the whole file, in order."""
    lines = text.splitlines()
    title = ""
    section = ""
    rows: list[dict[str, Any]] = []
    cols: dict[str, int] | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
        elif stripped.startswith("## "):
            section = stripped[3:].strip()
            cols = None
        if stripped.startswith("|"):
            if cols is None:
                found = _columns(_cells(stripped))
                if found and i + 1 < len(lines) and _is_separator(lines[i + 1]):
                    cols = found
                    i += 2
                    continue
            elif not _is_separator(stripped):
                cells = _cells(stripped)
                cells += [""] * (max(cols.values()) + 1 - len(cells))
                rows.append(
                    {
                        "row": len(rows) + 1,
                        "section": section,
                        "line": i,
                        "flow": cells[cols["flow"]],
                        "prompt": cells[cols["prompt"]],
                        "expected": cells[cols["expected"]],
                        "result": cells[cols["result"]],
                        "_result_col": cols["result"],
                        "_ncols": len(cells),
                    }
                )
        else:
            cols = None  # any non-table line ends the table
        i += 1
    sections: list[str] = []
    for r in rows:
        if r["section"] not in sections:
            sections.append(r["section"])
    return {"title": title, "rows": rows, "sections": sections}


def format_result(status: str, note: str = "") -> str:
    status = status.lower().strip()
    if status not in STATUSES:
        raise ValueError("status must be one of {}".format(", ".join(STATUSES)))
    note = " ".join((note or "").split())
    if status != "success" and not note:
        raise ValueError(
            "{} needs a note ({})".format(
                status, "what happened instead" if status == "fail" else "why"
            )
        )
    # success evidence goes to the report
    text = status if status == "success" else f"{status}: {note}"
    return text.replace("|", "\\|")


def fill_results(text: str, results: dict[int, str]) -> str:
    """Return the plan with the Result cell of each row set (rows missing from results are left as they are)."""
    plan = parse_plan(text)
    lines = text.splitlines()
    for r in plan["rows"]:
        if r["row"] not in results:
            continue
        cells = _cells(lines[r["line"]])
        cells += [""] * (r["_ncols"] - len(cells))
        cells[r["_result_col"]] = results[r["row"]]
        lines[r["line"]] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


_POSITIONAL = re.compile(
    r"^(tap|select)\s+(the\s+)?(first|second|third|fourth|last|\d+(st|nd|rd|th))\s+"
    r"(option|row|item|card|button|one)\b",
    re.IGNORECASE,
)
_EMPTY_SELECTION = re.compile(
    r"empty selection|nothing selected|no selection|without select|none selected|"
    r"\(disabled\)|while disabled",
    re.IGNORECASE,
)


def lint_plan(plan: dict[str, Any]) -> list[str]:
    """Problems an unattended run would trip over. The planner fixes them before it replies."""
    out: list[str] = []
    rows = plan["rows"]
    for r in rows:
        prompt = r["prompt"].strip()
        if _POSITIONAL.match(prompt):
            out.append(
                f"row {r['row']}: {prompt!r} - name the row by its visible text from the mock data "
                "(e.g. `select NAME · 1234`), not by position"
            )
        if re.match(
            r"^(tap|select)\b", prompt, re.IGNORECASE
        ) and _EMPTY_SELECTION.search(prompt):
            out.append(
                f"row {r['row']}: {prompt!r} - a disabled control is never a step; an empty selection "
                'is reached by typing (e.g. "none of them")'
            )
    if any(re.match(r"^select\b", r["prompt"].strip(), re.IGNORECASE) for r in rows):
        if not any(
            re.match(r"^type:", r["prompt"].strip(), re.IGNORECASE) for r in rows
        ):
            out.append(
                "picker without a typed-option row: add `type: <a row's visible text>` (typing the name "
                "instead of tapping it)"
            )
        reentry = False
        for sec in plan["sections"]:
            typed = [
                r["prompt"].strip().casefold()
                for r in rows
                if r["section"] == sec
                and not re.match(
                    r"^(tap|select|swipe|wait|type:)\b",
                    r["prompt"].strip(),
                    re.IGNORECASE,
                )
            ]
            if len(typed) != len(set(typed)):
                reentry = True
        if not reentry:
            out.append(
                "picker without a re-entry: add a conversation that starts the flow again (the same start "
                "prompt) after it finished or was cancelled"
            )
    return out


def public_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in r.items() if not k.startswith("_") and k != "line"}
        for r in plan["rows"]
    ]
