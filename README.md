# jevq

Reads a Jev question the way the model's documented failure modes would. No
API key, no labelled data, no model call, so it runs in a hundredth of a
second and belongs in a pre-commit hook.

```
jevq questions.json                          # a file in the API shape
jevq --from rules:questions -C ../myproject  # questions built by code
jevq --list-rules
```

Exit status is 0 when clean, 1 when something warns, 2 when the run failed.
Python 3.12. PyYAML only if you feed it YAML.

## Why this direction

This ecosystem has at least four linters **powered by** Jev. None of them
lints the **Jev questions themselves**, which is the direction that matters,
because the question is the part you cannot see is broken by reading it.

The bug that prompted this is published. [commitjev](https://github.com/yodablocks/commitjev) shipped a rule asking
"does the diff delete working code **without** the message giving a reason".
That "without" joins a second condition onto the first, and Jev is documented
as answering the question you wrote, literally, which in practice meant
answering the first half. It scored 0.75 on commits that really deleted
something and **0.81 on commits that deleted nothing**, so it ranked below
chance. Finding it took a labelled fixture set and a measured investigation.
One regex would have caught it before it was ever committed.

## The rules

Every rule encodes something TypeSafe already documents, and carries the
anchor it came from.

| rule | what it looks for |
|---|---|
| `compound-condition` | "without", "unless", "and not", "but not", "other than", "except", "rather than" in the instruction |
| `asks-to-count` | "how many", "number of", "more than N", a bare "count" |
| `asks-for-arithmetic` | sums, averages, percentages, numeric comparison, hex and RGB |
| `compares-dates` | "older than", "within N days", "which came first", and "before"/"after" near anything temporal |
| `asks-to-generate` | "write", "summarize", "explain why", "translate" |
| `noul-double-negative` | the instruction negates and its `true` criterion negates again |
| `choice-without-no-match` | a Choice with nowhere to put "none of these" |
| `choice-too-many-options` | over the documented 255 |
| `score-levels` | fewer than two levels, or levels that name a label instead of describing a situation |

## Run it on the bug it was written for

[commitjev](https://github.com/yodablocks/commitjev) at `bc25e80`, before the compound question was split:

```
rules:questions  unexplained_removal
  WARN  a second condition is joined onto the first
        "without" in "...ing code, tests, or documentation without `commit_message` giving a reason..."
        https://docs.typesafe.ai/model-jaggedness/jev-1.13#literal-reading

3 findings (3 warn, 0 note), 8 questions checked, 0.02s
```

The same project today, after the split:

```
2 findings (2 warn, 0 note), 9 questions checked, 0.03s
```

That finding is gone. Two remain, and both are fair. `undisclosed_change`
really does negate twice. `single_purpose` really does contain "without", and
it is independently the weakest rule that project has left by measured
separation, so the linter is pointing at the right question for a reason it
arrived at on its own.

## How it finds questions built by code

Questions rarely sit in a file in the shape the API sees. They are built by a
dataclass with its own field names, or a function, or a loop. Reading all that
out of the source is a losing game, so `jevq` does not try. It asks the code
for its questions and lints what comes back:

```
jevq --from rules:questions -C ../commitjev
```

That runs in a subprocess, not in process, for a reason worth stating: your
module and this one can share a name, and they do. Point it at `commitjev` and
both sides have a `rules.py`, so an in-process import silently lints the wrong
one. The subprocess also means a linted project cannot leave anything behind
in the process linting it.

It executes your module, the way a test runner does. That is your own code.

## What it cannot do

- **It cannot tell you whether a question separates.** This is the important
  limit. A question can pass every rule here and still score higher on the
  cases that should say no. That takes labelled data and a measured run, and
  nothing static will ever substitute for it. `jevq` catches the mistakes you
  could have seen by reading.

- **Two rules are judgment calls, on purpose.** "Without" is sometimes a
  compound condition and sometimes just English. "More than one" is sometimes
  a count and sometimes a figure of speech. Both report at `warn` with the
  doc link rather than pretending to decide. The rule's job is to make you
  look. Silence one per run with `--skip compound-condition`.

- **The trigger lists are English and visible.** They live at the top of
  `rules.py` as plain constants. Extend them for your domain.

- **It reads the question, never the state.** A question that is perfect in
  isolation can still be wrong for the data you send it.

## The other two

Three repos, in the order the problem gets harder:

- **[jev-orderby-bench](https://github.com/yodablocks/jev-orderby-bench)**
  measures the model itself. Does `ORDER BY` over a Jev probability put rows
  in a defensible order? Six pre-registered gates on 360 labeled rows, and a
  hard probe where four of the six fail.
- **[commitjev](https://github.com/yodablocks/commitjev)** builds on it. It
  reviews commits, and ships the labelled fixtures and margins that say what
  it catches. It is also where the bug above came from.
- **jevq**, this one, catches the subset of question mistakes that are
  visible without running anything.

They are all mine, so none of them is independent corroboration of the
others. Read the numbers, not the byline.

## Files

- `jevq.py` the CLI
- `rules.py` the nine rules, their trigger lists, and the doc anchors
- `load.py` the two front ends, file and `--from`
- `report.py` terminal, `--json`, and `--github` annotations
- `test_rules.py` offline tests, `python3 test_rules.py`
- `examples/support.json` a question set with one of each mistake

MIT licensed.
