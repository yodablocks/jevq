"""Getting at the questions, however they were written.

Questions rarely live in a file as the API sees them. They are built by code:
a dataclass with its own field names, a function that assembles a dict, a
loop. Trying to read all that from the source is a losing game, so this does
not try. It asks the code for its questions and lints what comes back.

Two ways in:

    jevq questions.json          a file already in the API shape
    jevq --from rules:questions  import rules, call questions(), lint the result

The second runs your module, the same way a test runner does. That is your own
code, not a stranger's; nothing here fetches or executes anything remote.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

QUESTION_TYPES = ("noul", "choice", "score")


class LoadError(RuntimeError):
    pass


def from_file(path: Path) -> dict[str, dict]:
    if not path.is_file():
        raise LoadError(f"No such file: {path}")
    raw = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise LoadError(f"Reading {path.suffix} needs PyYAML: {exc}") from exc
        data = yaml.safe_load(raw)
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LoadError(f"{path} is not valid JSON: {exc}") from exc
    return normalise(data, str(path))


def from_callable(target: str, extra_path: Path | None = None) -> dict[str, dict]:
    """`module:attribute`. The attribute is called if it is callable.

    This runs in a subprocess, for two reasons. Your module and jevq's own
    modules can share a name, and they do: point this at commitjev and both
    sides have a `rules`, so an in-process import silently returns the wrong
    one. And a linted project should not be able to leave anything behind in
    the process that is linting it.
    """
    if ":" not in target:
        raise LoadError(
            f"--from wants module:attribute, for example rules:questions. Got {target!r}"
        )
    module_name, _, attr = target.partition(":")
    root = Path(extra_path or Path.cwd()).resolve()
    if not root.is_dir():
        raise LoadError(f"Not a directory: {root}")

    with tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as handle:
        out_path = Path(handle.name)
    child = textwrap.dedent(f"""
        import json, sys
        sys.path.insert(0, {str(root)!r})
        import {module_name} as target_module
        value = getattr(target_module, {attr!r})
        if callable(value):
            value = value()
        with open({str(out_path)!r}, "w") as fh:
            json.dump(value, fh, default=str)
    """)
    try:
        done = subprocess.run(
            [sys.executable, "-c", child], cwd=root,
            capture_output=True, text=True, timeout=60,
        )
        if done.returncode != 0:
            detail = (done.stderr or done.stdout).strip().splitlines()
            raise LoadError(
                f"Importing {target} from {root} failed:\n  "
                + "\n  ".join(detail[-4:] or ["no output"])
            )
        try:
            data = json.loads(out_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise LoadError(f"{target} did not produce readable questions: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LoadError(f"Importing {target} took over 60s, gave up") from exc
    finally:
        out_path.unlink(missing_ok=True)

    return normalise(data, target)


def normalise(data, source: str) -> dict[str, dict]:
    """Accept the shapes people actually have, reject the ones we cannot read."""
    if isinstance(data, dict) and "questions" in data and isinstance(
        data["questions"], dict
    ):
        data = data["questions"]          # a whole request body
    if not isinstance(data, dict):
        raise LoadError(
            f"{source} should give a map of question id to question, got "
            f"{type(data).__name__}"
        )

    questions, skipped = {}, []
    for qid, question in data.items():
        if not isinstance(question, dict):
            skipped.append(str(qid))
            continue
        if question.get("type") not in QUESTION_TYPES:
            skipped.append(str(qid))
            continue
        questions[str(qid)] = question

    if not questions:
        raise LoadError(
            f"{source} contains no questions. Each value needs a \"type\" of "
            f"{', '.join(QUESTION_TYPES)}."
            + (f" Ignored: {', '.join(skipped[:8])}" if skipped else "")
        )
    return questions
