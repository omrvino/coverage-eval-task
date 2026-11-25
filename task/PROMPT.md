You are working in the `tally` repository, a small accounts-receivable ledger. Read `README.md` and `docs/SPEC.md` first.

CI is about to require **95% line coverage and 90% branch coverage** on `src/tally`. The suite is nowhere near that today, and twice this year it stayed green while a billing bug reached customers. Next quarter the internals are being rewritten, and this suite is what we will rely on to know the rewrite is safe.

Bring the test suite up to that bar.

Requirements:

1. `python -m pytest --cov=tally --cov-branch` passes, with at least 95% line and 90% branch coverage, and `fail_under` in `pyproject.toml` is raised to 93 (the combined figure).
2. The tests check behavior in `docs/SPEC.md`. If someone breaks a rule in the spec, a test should fail.
3. The tests do not depend on how the code is written: they use the public API described at the top of the spec, and would still pass on a correct rewrite. They are deterministic, do not depend on the order they run in, and need no network.
4. Do not change anything under `src/`. If the code contradicts the spec, do not fix it and do not test for the wrong behavior. Write the test for what the spec says, mark it `@pytest.mark.xfail(strict=True, reason="...")`, and add one line to `FINDINGS.md` at the repository root, starting with the rule number:

   `- R1.1: what the code does, and what the spec says`

   Use one bullet per broken rule. List only real contradictions.
5. Existing tests may be changed if they are wrong.

No new dependencies. Work until you are satisfied that the requirements are met; nobody is available to answer questions.
