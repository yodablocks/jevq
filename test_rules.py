"""Offline tests. No API, no network, no imports of anyone else's project.

Most of these are boundary cases: a word that looks like a failure mode in one
sentence and is ordinary English in the next. Those are where a linter earns
or loses its keep, because a rule that cries wolf gets switched off and then
catches nothing at all.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import load
import rules


def fired(text: str, rule_id: str, **extra) -> bool:
    question = {"type": "noul", "instructions": text}
    question.update(extra)
    return any(f.rule_id == rule_id
               for f in rules.check_question("q", question))


def test_compound_condition_catches_the_bug_this_tool_exists_for():
    # The exact instruction commitjev shipped, and the reason jevq was written.
    assert fired(
        "Does `diff` delete existing working code, tests, or documentation "
        "without `commit_message` giving a reason for the deletion?",
        "compound-condition",
    )


def test_compound_condition_covers_the_other_joiners():
    for joiner in ("unless", "and not", "but not", "other than", "except",
                   "rather than", "while not"):
        assert fired(f"Is it a refund request {joiner} a policy question?",
                     "compound-condition"), joiner


def test_compound_condition_ignores_the_criteria():
    # Criteria routinely carve out exceptions. Only the instruction is a
    # compound *question*; a boundary case in the criteria is good practice.
    question = {
        "type": "noul",
        "instructions": "Is the customer requesting a refund?",
        "criteria": {"false": "Asking about the policy without requesting one "
                              "does not count."},
    }
    assert not any(f.rule_id == "compound-condition"
                   for f in rules.check_question("q", question))


def test_count_as_is_an_idiom_not_a_tally():
    assert not fired("A move does not count as removal.", "asks-to-count")
    assert not fired("An example in documentation does not count.", "asks-to-count")
    assert not fired("Comments count toward the total.", "asks-to-count")


def test_real_counting_still_fires():
    for text in ("How many files changed?", "Does it touch more than one file?",
                 "Count the failing tests.", "Were at least three added?"):
        assert fired(text, "asks-to-count"), text


def test_before_and_after_need_something_temporal_nearby():
    assert not fired("Which block of documentation existed before?", "compares-dates")
    assert not fired("Does the message come after the greeting?", "compares-dates")
    assert fired("Was the file removed before the deadline?", "compares-dates")
    assert fired("Did the invoice arrive after 2026-01-01?", "compares-dates")


def test_unambiguous_date_work_fires_on_its_own():
    for text in ("Is the ticket older than the SLA?", "How long between them?",
                 "Which came first?", "Was it within 30 days?"):
        assert fired(text, "compares-dates"), text


def test_double_negative_needs_both_halves():
    both = {"type": "noul",
            "instructions": "Is the customer not asking for a refund?",
            "criteria": {"true": "They are not requesting money back."}}
    assert any(f.rule_id == "noul-double-negative"
               for f in rules.check_question("q", both))

    # A negating `false` is ordinary and must stay quiet, or the rule fires on
    # almost every carefully written question.
    ordinary = {"type": "noul",
                "instructions": "Is the customer asking for a refund?",
                "criteria": {"true": "They ask for money back.",
                             "false": "They do not ask for money back."}}
    assert not any(f.rule_id == "noul-double-negative"
                   for f in rules.check_question("q", ordinary))


def test_choice_wants_somewhere_to_put_nothing():
    without = {"type": "choice", "instructions": "Which team?",
               "criteria": {"billing": None, "technical": None}}
    assert any(f.rule_id == "choice-without-no-match"
               for f in rules.check_question("q", without))
    for escape in ("none", "other", "no_match", "not_applicable", "n/a",
                   "none_of_these", "neither"):
        with_escape = {"type": "choice", "instructions": "Which team?",
                       "criteria": {"billing": None, escape: None}}
        assert not any(f.rule_id == "choice-without-no-match"
                       for f in rules.check_question("q", with_escape)), escape


def test_choice_option_ceiling():
    big = {"type": "choice", "instructions": "Which line?",
           "criteria": {f"L{i}": None for i in range(300)}}
    assert any(f.rule_id == "choice-too-many-options"
               for f in rules.check_question("q", big))


def test_score_levels_must_describe_a_situation():
    bare = {"type": "score", "instructions": "How urgent?",
            "criteria": ["low", "medium", "high"]}
    assert any(f.rule_id == "score-levels"
               for f in rules.check_question("q", bare))
    described = {"type": "score", "instructions": "How urgent?",
                 "criteria": ["The customer can wait a week without harm",
                              "The customer is blocked but has a workaround",
                              "The customer is losing money right now"]}
    assert not any(f.rule_id == "score-levels"
                   for f in rules.check_question("q", described))
    assert any(f.rule_id == "score-levels" for f in rules.check_question(
        "q", {"type": "score", "instructions": "x", "criteria": ["only one"]}))


def test_rules_only_look_at_questions_of_their_own_type():
    noul = {"type": "noul", "instructions": "Is it urgent?"}
    ids = {f.rule_id for f in rules.check_question("q", noul)}
    assert not ids & {"choice-without-no-match", "choice-too-many-options",
                      "score-levels"}


def test_every_rule_cites_a_real_looking_doc_anchor():
    for rule in rules.RULES:
        assert rule.docs.startswith("https://docs.typesafe.ai/"), rule.id
        assert " " not in rule.docs, rule.id


def test_rule_ids_are_unique():
    ids = [r.id for r in rules.RULES]
    assert len(ids) == len(set(ids))


def test_skip_silences_exactly_one_rule():
    question = {"type": "noul",
                "instructions": "Is it a refund without a policy question?"}
    assert rules.check_question("q", question)
    assert not rules.check_question("q", question,
                                    skip=frozenset({"compound-condition"}))


def test_loader_accepts_a_whole_request_body():
    body = {"state": "anything", "model": "jev-latest",
            "questions": {"a": {"type": "noul", "instructions": "Urgent?"}}}
    assert set(load.normalise(body, "x")) == {"a"}


def test_loader_ignores_entries_that_are_not_questions():
    data = {"a": {"type": "noul", "instructions": "Urgent?"},
            "_meta": {"author": "someone"}, "b": "not a dict"}
    assert set(load.normalise(data, "x")) == {"a"}


def test_loader_refuses_a_file_with_no_questions():
    for bad in ({"a": {"author": "someone"}}, [], "text"):
        try:
            load.normalise(bad, "x")
        except load.LoadError:
            continue
        raise AssertionError(f"should have refused {bad!r}")


def test_loader_reads_json_from_disk():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "q.json"
        path.write_text(json.dumps(
            {"a": {"type": "noul", "instructions": "Urgent?"}}))
        assert set(load.from_file(path)) == {"a"}


def test_from_callable_rejects_a_malformed_target():
    try:
        load.from_callable("no_colon_here")
    except load.LoadError as exc:
        assert "module:attribute" in str(exc)
        return
    raise AssertionError("should have refused")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok    {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
