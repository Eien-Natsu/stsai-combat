# clarifications — the claims in the previous round that need a precise reading

Task `GITHUB-HANDOFF-001`. Everything below is read from the fixed code base
`e0fc584d19afe58ac10b65c93c7bcc75a2630f05`. No command was re-run to write this file; where a
statement rests on the previous round's log rather than on source, it says so.

---

## 1. The isolation claim, and what `token_variables` actually reports

`reports/s2r/SUMMARY.md` §4 says the cold review ran with an explicitly constructed child
environment holding no token variable. `reports/s2r/t3/cold_review.json` then shows

```json
"token_variables": ["ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_MESSAGING_TOKEN"]
```

which reads like a contradiction. It is not, and the reason matters enough to spell out.

**Where each thing comes from.** In `reports/s2r/t3_cold_review.py`:

| Line | Code | What it is |
| --- | --- | --- |
| 51 | `home = out / "isolated-home"` | an empty directory the driver creates |
| 58–60 | `env = {"HOME": str(home), "PATH": f"{venv_bin}:/usr/local/bin:/usr/bin:/bin", "LANG": ..., "LC_ALL": ..., "TMPDIR": ..., "PYTHONDONTWRITEBYTECODE": "1"}` | the **only** environment any child gets |
| 68–69 | `subprocess.run(command, cwd=..., env=env, ...)` | every step passes that dict; `env=` replaces rather than extends, so nothing is inherited |
| 95 | `"ssh_dir_exists": (home / ".ssh").exists()` | checked against the **isolated** home |
| 96 | `"gh_config_exists": (home / ".config/gh").exists()` | likewise |
| 97–98 | `"token_variables": [k for k in os.environ if "TOKEN" in k.upper() or "KEY" in k.upper()]` | reads the **driver's own** `os.environ` — the parent |

So the two facts are about two different processes. `token_variables` is a record of what the
launching session had in its environment; it is evidence that the scrub was *necessary*, not
evidence that it failed. The child dictionary is built from literals and never copies the
parent, so those two names were not present in any reviewed process.

**What this does not establish.** The isolation is environment-variable level only. The child
runs as the same user on the same filesystem; `HOME` being an empty directory does not stop a
process from opening `/home/node/.config/gh/hosts.yml` by absolute path. `ssh_dir_exists` and
`gh_config_exists` are computed against the *empty* isolated home, so both being `false` says
the scrub worked, not that the real user's credentials are unreachable. `SUMMARY.md` §4 already
states the boundary — no docker on the machine, so no container-level isolation — and that
statement is accurate.

**Defensible form of the claim.** "The reviewed commands inherited no credential variable, and
none of them used one" is supported. "No credential was reachable from the reviewed processes"
is **not** supported and should not be written. A reviewer wanting the stronger statement needs
a container or a separate UID, which is a new round's decision, not this one's.

**Credential handling.** This round read no token value. The only occurrence of a token name
anywhere in the delivered material is the two strings above, which the previous round's own
driver wrote into its receipt. No value was printed, requested or inferred.

---

## 2. Two cold reviews happened; only the second one is in the repository

`SUMMARY.md` §4 reports two complete cold reviews, 31.4 s and 33.1 s, both green.
`reports/s2r/t3/cold_review.json` contains exactly one set of six steps, and their
`elapsed_seconds` are `1.2 + 0.1 + 0.0 + 1.2 + 27.9 + 2.7 = 33.1 s`. That is the **second**
run. The 31.4 s run's receipt and per-step logs are not tracked anywhere in the repository.

So: the final run is fully auditable per step; the first run exists only as a sentence in the
summary. This matters because the round's own budget accounting counts two reviews, and the
reviewer can only verify one of them from repository content. The first run is
`EVIDENCE_NOT_AVAILABLE`, not `PASS`.

---

## 3. `package_manifest_sha256` is the zip's hash, not the manifest file's

`reports/s2r/artifact_lock.json` names its top-level field `package_manifest_sha256` and gives

```
92a07276a2dabef7def32c80d30bdccd63a4e0ed628e26576f3c6721f8ef4d52
```

That value is the SHA-256 of the whole `stsai_s2_review_253e391.zip` (12308133 bytes). The
SHA-256 of the `MANIFEST.sha256` file *inside* the zip is
`36a07ef75f171d75387d8b483d4cace556d3a6c76d8c17cf76eaddcde2799393` (2993 bytes). Both are
reproducible from the delivered material; the field name is the only thing that is wrong. This
round publishes the manifest verbatim at
`reports/github_handoff_001/package/MANIFEST.sha256` so the distinction is checkable.

---

## 4. What the 277-test figure covers, and what it does not

`reports/s2r/t3/junit.xml` is a genuine JUnit document: `tests="277" failures="0" errors="0"
skipped="0"`, timestamped `2026-09-18T17:09:19.745440+00:00`. It was produced by `pytest tests`
run with `cwd` = the **253e391** checkout.

The round added 17 tests (`tests/test_review_inputs.py`, 14 functions;
`tests/test_run_review_jobs.py`, 3 functions) that exist only in the implementation head. They
are absent from the checkout, absent from that JUnit, and no other test log for them is tracked.
`reports/github_handoff_001/new_tests_run_evidence.json` records this with the blob SHAs and the
search that established it.

The honest reading: **the 17 new tests have no evidence of ever having run in this repository.**
That is different from saying they fail, and it is different from saying the 277 tests cover
them. The 277 are real and they are the checkout's.

---

## 5. The CI that failed and the branch that diagnosed it ran the same training code

`reports/s2r/ci_failure_analysis.md` §1 claims `git diff 2cc0c75 4462a7c -- src tests review
scripts` is empty, i.e. the failing CI tested the same source the branch holds. Re-derived from
this clone rather than taken on trust:

- `git diff --numstat 2cc0c75 4462a7c -- src tests review scripts` → no output.
- `src/stsai/training.py` blob is `2e199b0e79784e97a7591f3b2107d25b1120bf95` at `2cc0c75`
  (the CI head), at `4462a7c`, at the `253e391` checkout and at `e0fc584`.
- `tests/test_training_loss.py` blob is `eda8bec8fb2c656dcd7f409af022309f97873562` in all four.
- No commit after the T0 commit `eede818` touches `src/`.

The claim holds. The diagnostics therefore exercised the same `stsai.training` the CI did, which
is what makes the T0 root-cause argument about gauge direction a statement about the reviewed
code rather than about a local variant.

---

## 6. The `--jobs` default is new in this round

`review/run_review.py` differs between the two trees: the head copy adds `--jobs` (default 2) and
forwards it to `offline_native_build.py`, whose own default is `min(4, cpu_count)` — over the
project's two-worker budget. The package ships the older copy, which has no `--jobs` flag. A
reviewer reading the package's `review/run_review.py` is reading a file that was **not** the one
that ran; the one that ran is `e83ff22df5763ca3010bc768fafa5fe7b93202b0`.

---

## 7. Scope check against the old plan

The old plan (`4462a7c`) T0 forbids changing loss/optimizer semantics, relaxing `allclose`, and
deleting or skipping tests, and requires a BLOCKED hand-back if the criteria themselves need to
change. The head commit `e0fc584` does none of those: the T0 diagnosis is delivered as
`ci_failure_analysis.md` with a proposed fix marked "本轮**未实施**", and the round ends BLOCKED.
The increment `4462a7c..e0fc584` touches 58 files, all of them `review/`, `tests/`, `scripts/`
and `reports/s2r/` — no file under `src/`, `native/` or `configs/`. The deletions of superseded
`scripts/*.py` that appear in a `253e391..e0fc584` diff belong to the upstream branch commits
`5284add`/`152d78f`, which pre-date the old plan and are not part of this task.
