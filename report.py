"""Showing findings: for a terminal, for CI, for a machine."""

from __future__ import annotations

import json
import os
import sys

RED, YELLOW, DIM, BOLD, RESET = (
    "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)
COLOR = {"warn": RED, "note": YELLOW}


def _paint(text: str, code: str, on: bool) -> str:
    return f"{code}{text}{RESET}" if on else text


def terminal(findings: list, source: str, checked: int, elapsed: float,
             stream=sys.stdout) -> None:
    on = stream.isatty() and "NO_COLOR" not in os.environ

    by_question: dict[str, list] = {}
    for f in findings:
        by_question.setdefault(f.question_id, []).append(f)

    for qid, group in by_question.items():
        print(f"{_paint(source, DIM, on)}  {_paint(qid, BOLD, on)}", file=stream)
        for f in group:
            mark = _paint(f.severity.upper(), COLOR.get(f.severity, ""), on)
            print(f"  {mark}  {f.message}", file=stream)
            if f.detail:
                print(f"        {_paint(f.detail, DIM, on)}", file=stream)
            print(f"        {_paint(f.docs, DIM, on)}", file=stream)
        print(file=stream)

    warns = sum(1 for f in findings if f.severity == "warn")
    notes = len(findings) - warns
    summary = (f"{len(findings)} finding{'s' if len(findings) != 1 else ''}"
               f" ({warns} warn, {notes} note)" if findings else "clean")
    print(f"{summary}, {checked} question{'s' if checked != 1 else ''} checked, "
          f"{elapsed:.2f}s", file=stream)


def as_json(findings: list, source: str, checked: int) -> str:
    return json.dumps({
        "source": source,
        "questions_checked": checked,
        "findings": [
            {"rule": f.rule_id, "severity": f.severity, "question": f.question_id,
             "message": f.message, "detail": f.detail, "docs": f.docs}
            for f in findings
        ],
    }, indent=2)


def as_github(findings: list, source: str) -> str:
    """GitHub Actions annotations, so findings land on the PR."""
    return "\n".join(
        f"::{'error' if f.severity == 'warn' else 'warning'} "
        f"file={source},title={f.rule_id}::"
        f"{f.question_id}: {f.message}. {f.detail} See {f.docs}"
        for f in findings
    )
