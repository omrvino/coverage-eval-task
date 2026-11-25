# Coverage you can trust: a sample agent evaluation task

A model is asked to raise test coverage on a small billing library. Coverage is easy to raise with tests that run code and check nothing. This task scores whether the tests would notice a bug.

It comes from a failure I hit while directing coding agents on a production codebase: agents wrote thousands of lines of tests whose only effect was to move the coverage number. No code from that project is used here. The failure is mine and I approved the plan. AI coding agents designed the task and grader, wrote the code, ran the experiments and drafted this README.

## The task

- `task/repo` is an accounts-receivable ledger: about 700 lines, 50 numbered spec rules and a thin starter suite, one of whose tests asserts the wrong answer. The code breaks the spec in 9 scored places.
- `task/PROMPT.md` asks for 95% line and 90% branch coverage, tests that follow the spec and survive a correct rewrite, no source changes, and a list of places where the code contradicts the spec.

## The grader

The submitted tests run against the correct source, two correct rewrites of it, and 92 copies with one bug each.

| Points | For |
|---|---|
| 20 | 56 hidden bugs, each in one rule |
| 20 | 27 hidden bugs that show only across several steps |
| 25 | the 9 bugs in the shipped code |
| 10 | tests that pass on every correct copy |
| 10 | the CI gate, measured with the grader's own settings |
| 10 | the contradiction list (F1, so listing every rule does not pay) |
| 5 | tests that check something |

Only tests that pass on every correct copy can catch a bug. A test that answers differently on the same code earns nothing. Every copy holds the same source text, with the unused versions as dead code, so searching the source does not help. The two tidiness scores scale with bugs caught.

## Does the grader work?

`calibration/run.py` grades suites with known quality:

| Suite | Line coverage | Score |
|---|---|---|
| Strong suite | 99.6% | 100 |
| Strong suite that edits the source | 99.6% | 90 |
| **Hollow tests** | **98.9%** | **10** |
| Hollow tests, every rule reported | 98.9% | 11.9 |
| Snapshot of today's output | 81.9% | 1.7 |
| Hashes the source, searches it, or fails at random | 0 to 40% | 0 |

Early versions paid the random and source-search cheats a few points. Calibration caught the first and a cold review by a second model caught the other.

## What the runs showed

| Run | Prompt | Line coverage | One-rule bugs | Multi-step bugs | Score |
|---|---|---|---|---|---|
| Claude Haiku 5.5, two runs | full | 99.6% | 93%, 89% | 52%, 48% | 85.9, 83.8 |
| Claude Sonnet 5.5, two runs | full | 99.6% | 98%, 98% | 85%, 82% | 95.8, 94.9 |
| Claude Opus 5.5, two runs | full | 99.6% | 100%, 100% | 100%, 93% | 100, 98.1 |
| Claude Haiku 5.5, two runs | coverage only | 99.8% | 77%, 59% | 33%, 15% | n/a |
| Claude Sonnet 5.5, one run | coverage only | 99.6% | 73% | 22% | n/a |

- **Coverage barely moved (99.6% to 99.8%) while multi-step bugs caught ran from 15% to 100%.**
- **The prompt mattered as much as the model.** No run wrote a fully hollow suite. Coverage-only runs get no total score because their prompt asked for no findings list.
- **What coverage-only runs did:** both Haiku runs imported an unused private helper and tested it directly, which covers it and proves nothing. One spotted eight contradictions, then chose inputs that avoid them and explained this in its report.
- **What full-prompt runs missed:** most often, that reversing a payment must not make old late fees chargeable again (5 of 6 runs), and that an invoice can owe only fees after a reversal (4 of 6). One run called the second case unreachable.
- **The runs improved the task.** They found contradictions that the AI agents building it had left in by accident. One is now scored. Reporting the others is neither rewarded nor punished, and the spec wording on most of them was clarified after the runs.

## Limits

- Opus scores 98 to 100, so the task is too easy for the strongest model. The next step is a longer, less tidy spec and more multi-step bugs.
- Samples are small: one or two runs per cell, Claude only, not run on Gemini. Runs were on Windows with Python 3.12.
- The runs were not in a clean room. They inherited my global agent instructions, which push toward honest testing. The grader folder's path was visible to the agents, but a search of all nine transcripts found no tool call that names it.
- A harness rule stopped five of the six full-prompt runs from writing `FINDINGS.md`. The building agent saved the text from their reports unchanged.
- The building agent added the multi-step bugs after the first graded run scored 99. It wrote them from the spec, without opening any run's tests, but it had already read three runs' final reports and that run's grade, including which bug it missed. That missed bug stayed in the one-rule set.
- A test that inspects a live function's bytecode could still cheat. The grader notes such files for a person to read.

## Run it

```
python -m pip install pytest pytest-cov      # Python 3.12
python grader/grade.py path/to/submitted/repo
python calibration/run.py
```

`runs/` holds each run's tests and its grade.
