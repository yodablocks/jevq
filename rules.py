"""What can go wrong in a Jev question, and how to see it without asking Jev.

Every rule here encodes something TypeSafe already documents about its own
model. None of them calls the API. That is the whole point: the failure modes
below are visible in the text of a question, so finding them should cost
nothing and need no labelled data.

What this cannot do is tell you whether a question separates the cases you
care about. Nothing short of labelled data does that. These rules catch the
mistakes you could have seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

JAGGED = "https://docs.typesafe.ai/model-jaggedness/jev-1.13"
WARN, NOTE = "warn", "note"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    question_id: str
    message: str
    docs: str
    detail: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    docs: str
    summary: str
    check: Callable[[str, dict], list[str]]   # returns one detail line per hit

    def run(self, qid: str, question: dict) -> list[Finding]:
        return [
            Finding(self.id, self.severity, qid, self.summary, self.docs, detail)
            for detail in self.check(qid, question)
        ]


# --------------------------------------------------------------- helpers

def text_of(question: dict) -> str:
    """Every piece of natural language in a question, flattened."""
    parts: list[str] = []

    def walk(value):
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for key, sub in value.items():
                if key != "type":
                    parts.append(str(key))
                    walk(sub)
        elif isinstance(value, (list, tuple)):
            for sub in value:
                walk(sub)

    walk(question.get("instructions"))
    walk(question.get("criteria"))
    return "\n".join(p for p in parts if p)


def instructions_text(question: dict) -> str:
    parts: list[str] = []

    def walk(value):
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for sub in value.values():
                walk(sub)
        elif isinstance(value, (list, tuple)):
            for sub in value:
                walk(sub)

    walk(question.get("instructions"))
    return "\n".join(parts)


def _hits(pattern: re.Pattern, haystack: str) -> list[str]:
    """Distinct matches, in order, with a little context around each."""
    seen, out = set(), []
    for m in pattern.finditer(haystack):
        word = m.group(0).strip().lower()
        if word in seen:
            continue
        seen.add(word)
        start, end = max(0, m.start() - 34), min(len(haystack), m.end() + 34)
        snippet = haystack[start:end].replace("\n", " ").strip()
        out.append(f'"{word}" in "...{snippet}..."')
    return out


# ----------------------------------------------------------------- rules

# Words that join a second condition onto the first. Jev is documented as
# answering the question you wrote, literally, and a question with two halves
# tends to get answered by its first half.
COMPOUND = re.compile(
    r"\b(without|unless|and not|but not|other than|except(?: for)?|"
    r"while not|rather than)\b", re.I
)

# "count as" and "does not count" are idioms meaning "qualify as", not a tally,
# and they turn up constantly in criteria that carve out boundary cases.
COUNTING = re.compile(
    r"\b(how many|number of|at least \w+|at most \w+|more than \w+|"
    r"fewer than \w+|exactly \w+|"
    r"(?<!not )(?<!n't )count(?:s|ed|ing)?\b(?!\s+(?:as|toward|towards)\b))",
    re.I
)

ARITHMETIC = re.compile(
    r"\b(sum|total|average|mean|median|percentage|percent|multiply|divide|"
    r"subtract|greater than|less than|hex|rgb|#[0-9a-f]{6}\b)\b", re.I
)

# Unambiguous date and duration work. "before" and "after" are deliberately not
# here on their own: "the code that existed before" is not a date comparison,
# and a rule that fires on every use of a common preposition gets switched off.
DATES = re.compile(
    r"\b(earlier than|later than|within \w+ (?:days?|weeks?|months?|years?)|"
    r"how long|duration|elapsed|which came first|older than|newer than|"
    r"days? between|most recent|chronolog\w+)\b", re.I
)

# "before"/"after" only count when something temporal is nearby.
LOOSE_DATES = re.compile(r"\b(before|after)\b", re.I)
TEMPORAL = re.compile(
    r"\b(date|dates|dated|time|times|timestamp|deadline|expir\w+|due|day|days|"
    r"week|weeks|month|months|year|years|hour|hours|minute|minutes|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2})\b", re.I
)

GENERATION = re.compile(
    r"\b(write|summari[sz]e|rewrite|explain why|generate|draft|compose|"
    r"describe in your own words|paraphrase|translate)\b", re.I
)

NEGATION = re.compile(r"\b(not|never|no longer|neither|none|cannot|isn't|"
                      r"doesn't|does not|is not)\b", re.I)

NO_MATCH_OPTION = re.compile(
    r"^(none|no[_-]?match|other|neither|unknown|not[_-]?applicable|n/?a|"
    r"nothing|no[_-]?problem|none[_-]?of[_-]?(these|the[_-]?above))$", re.I
)


def _compound(qid: str, q: dict) -> list[str]:
    return _hits(COMPOUND, instructions_text(q))


def _counting(qid: str, q: dict) -> list[str]:
    return _hits(COUNTING, text_of(q))


def _arithmetic(qid: str, q: dict) -> list[str]:
    return _hits(ARITHMETIC, text_of(q))


def _dates(qid: str, q: dict) -> list[str]:
    body = text_of(q)
    out = _hits(DATES, body)
    for m in LOOSE_DATES.finditer(body):
        window = body[max(0, m.start() - 40):m.end() + 40]
        if TEMPORAL.search(window):
            out.extend(_hits(re.compile(re.escape(m.group(0)), re.I), body))
            break
    return out


def _generation(qid: str, q: dict) -> list[str]:
    return _hits(GENERATION, instructions_text(q))


def _noul_double_negative(qid: str, q: dict) -> list[str]:
    """A Noul that negates in the instruction and again in its `true` criterion.

    A criterion containing "not" is ordinary and usually right: most careful
    `false` descriptions negate, and a `true` often carves out an exception. The
    shape worth flagging is a negative instruction whose `true` also negates,
    because then reading it means resolving two negations at once, which is the
    indirection Jev is documented as losing accuracy on.
    """
    if q.get("type") != "noul":
        return []
    true_text = (q.get("criteria") or {}).get("true")
    if not isinstance(true_text, str) or not true_text:
        return []
    instruction = instructions_text(q)
    in_instruction = NEGATION.search(instruction)
    in_true = NEGATION.search(true_text)
    if in_instruction and in_true:
        return [f'"{in_instruction.group(0)}" in the instruction and '
                f'"{in_true.group(0)}" in criteria.true']
    return []


def _choice_no_match(qid: str, q: dict) -> list[str]:
    if q.get("type") != "choice":
        return []
    options = list((q.get("criteria") or {}).keys())
    if not options:
        return []
    if any(NO_MATCH_OPTION.match(str(o)) for o in options):
        return []
    return [f"{len(options)} options, none of them a no-match outcome: "
            + ", ".join(str(o) for o in options[:6])
            + ("..." if len(options) > 6 else "")]


def _choice_too_many(qid: str, q: dict) -> list[str]:
    if q.get("type") != "choice":
        return []
    count = len(q.get("criteria") or {})
    return [f"{count} options, over the documented limit of 255"] if count > 255 else []


def _score_levels(qid: str, q: dict) -> list[str]:
    if q.get("type") != "score":
        return []
    levels = q.get("criteria") or []
    if not isinstance(levels, list):
        return []
    out = []
    if len(levels) < 2:
        out.append(f"{len(levels)} level(s); a Score needs at least two")
    bare = [str(l) for l in levels
            if isinstance(l, str) and len(str(l).split()) < 4]
    if bare:
        out.append("levels that name a label rather than describe a situation: "
                   + ", ".join(f'"{b}"' for b in bare[:5]))
    return out


RULES: tuple[Rule, ...] = (
    Rule("compound-condition", WARN, f"{JAGGED}#literal-reading",
         "a second condition is joined onto the first",
         _compound),
    Rule("asks-to-count", WARN, f"{JAGGED}#counting",
         "asks the model to count",
         _counting),
    Rule("asks-for-arithmetic", WARN, f"{JAGGED}#math-and-numbers",
         "asks for arithmetic or a numeric comparison",
         _arithmetic),
    Rule("compares-dates", WARN, f"{JAGGED}#date-and-time-comparison",
         "compares dates or durations",
         _dates),
    Rule("asks-to-generate", WARN, f"{JAGGED}#generation",
         "asks the model to produce text",
         _generation),
    Rule("noul-double-negative", WARN, f"{JAGGED}#indirection",
         "the instruction and its true criterion both negate",
         _noul_double_negative),
    Rule("choice-without-no-match", WARN, "https://docs.typesafe.ai/primitives/choice",
         "a Choice always picks something, and nothing here means none",
         _choice_no_match),
    Rule("choice-too-many-options", WARN, "https://docs.typesafe.ai/primitives/choice",
         "more options than a Choice accepts",
         _choice_too_many),
    Rule("score-levels", WARN, "https://docs.typesafe.ai/primitives/score",
         "Score levels do not stand on their own",
         _score_levels),
)


def check_question(qid: str, question: dict,
                   skip: frozenset[str] = frozenset()) -> list[Finding]:
    found = []
    for rule in RULES:
        if rule.id in skip:
            continue
        found.extend(rule.run(qid, question))
    return found


def check_all(questions: dict[str, dict],
              skip: frozenset[str] = frozenset()) -> list[Finding]:
    out = []
    for qid, question in questions.items():
        out.extend(check_question(qid, question, skip))
    return out
