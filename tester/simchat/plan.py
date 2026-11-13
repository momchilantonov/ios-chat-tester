"""Test plans: Markdown tables with the columns  Flow | User prompt | Expected | Result.

The planner agent writes them with an empty Result column; the tester fills Result with
`success`, `fail: <what happened>` or `blocked: <why>`. Each `##` section is one conversation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

STATUSES = ("success", "fail", "blocked")
_PIPE = re.compile(r"(?<!\\)\|")


def _cells(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip() for c in _PIPE.split(inner)]


def _is_separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c) and \
        any(cells)


def _columns(cells: List[str]) -> Optional[Dict[str, int]]:
    low = [c.lower() for c in cells]
    cols: Dict[str, int] = {}
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


def parse_plan(text: str) -> Dict[str, Any]:
    """Rows are numbered 1..N across the whole file, in order."""
    lines = text.splitlines()
    title = ""
    section = ""
    rows: List[Dict[str, Any]] = []
    cols: Optional[Dict[str, int]] = None
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
                rows.append({"row": len(rows) + 1, "section": section, "line": i,
                             "flow": cells[cols["flow"]], "prompt": cells[cols["prompt"]],
                             "expected": cells[cols["expected"]], "result": cells[cols["result"]],
                             "_result_col": cols["result"], "_ncols": len(cells)})
        else:
            cols = None  # any non-table line ends the table
        i += 1
    sections: List[str] = []
    for r in rows:
        if r["section"] not in sections:
            sections.append(r["section"])
    return {"title": title, "rows": rows, "sections": sections}


def format_result(status: str, note: str = "") -> str:
    status = status.lower().strip()
    if status not in STATUSES:
        raise ValueError("status must be one of %s" % ", ".join(STATUSES))
    note = " ".join((note or "").split())
    if status != "success" and not note:
        raise ValueError("%s needs a note (%s)" % (status, "what happened instead" if status == "fail" else "why"))
    text = status if status == "success" else "%s: %s" % (status, note)  # success evidence goes to the report
    return text.replace("|", "\\|")


def fill_results(text: str, results: Dict[int, str]) -> str:
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


def public_rows(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in r.items() if not k.startswith("_") and k != "line"} for r in plan["rows"]]
