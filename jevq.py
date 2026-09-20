#!/usr/bin/env python3
"""jevq: read a Jev question the way its documented failure modes would.

    jevq questions.json
    jevq --from rules:questions -C ../commitjev
    jevq --from rules:questions --json

It never calls the API. Every rule encodes something TypeSafe documents about
Jev, so checking costs nothing and needs no labelled data.

What it cannot do is tell you whether a question separates the cases you care
about. Only labelled data does that. This catches the mistakes you could have
seen by reading.

Exit status is 0 when clean, 1 when something warns, 2 when the run failed.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import load
import report
import rules


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jevq",
        description="Check Jev question definitions against the model's "
                    "documented failure modes. No API calls.",
    )
    parser.add_argument("path", nargs="?", type=Path,
                        help="a JSON or YAML file of questions")
    parser.add_argument("--from", dest="target", metavar="MODULE:ATTR",
                        help="import MODULE and lint what ATTR returns, for "
                             "example rules:questions")
    parser.add_argument("-C", "--chdir", type=Path, default=None,
                        help="directory to import from, with --from")
    parser.add_argument("--skip", default="", metavar="IDS",
                        help="comma separated rule ids to skip")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--github", action="store_true",
                        help="GitHub Actions annotations")
    parser.add_argument("--list-rules", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_rules:
        for rule in rules.RULES:
            print(f"{rule.id:<26} {rule.severity:<5} {rule.summary}")
            print(f"{'':<26} {'':<5} {rule.docs}")
        return 0

    if bool(args.path) == bool(args.target):
        print("Give either a file or --from module:attribute, not both.",
              file=sys.stderr)
        return 2

    started = time.time()
    try:
        if args.target:
            questions = load.from_callable(args.target, args.chdir)
            source = args.target
        else:
            questions = load.from_file(args.path)
            source = str(args.path)
    except load.LoadError as exc:
        print(exc, file=sys.stderr)
        return 2

    skip = frozenset(s.strip() for s in args.skip.split(",") if s.strip())
    unknown = skip - {r.id for r in rules.RULES}
    if unknown:
        print(f"Unknown rule id(s) in --skip: {', '.join(sorted(unknown))}. "
              f"See --list-rules.", file=sys.stderr)
        return 2

    findings = rules.check_all(questions, skip)
    elapsed = time.time() - started

    if args.json:
        print(report.as_json(findings, source, len(questions)))
    elif args.github:
        print(report.as_github(findings, source))
    else:
        report.terminal(findings, source, len(questions), elapsed)

    return 1 if any(f.severity == "warn" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
