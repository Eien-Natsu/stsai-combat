# EVIDENCE_INDEX — GITHUB-HANDOFF-001

Reader: a fresh Chat that can read only this repository, has no local tools and no memory of any
earlier session. Everything indexed below is UTF-8 text in a fixed commit, paged so it can be
read in pieces.

## Snapshot

| Field | Value |
| --- | --- |
| Task / request | `GITHUB-HANDOFF-001` / `manual-chat-github-handoff-001` |
| Plan / control commit | `5c331ca8c043c951b5ea9687fc7b92b3566ee21d` |
| Code base (evidence source) | `e0fc584d19afe58ac10b65c93c7bcc75a2630f05` — PR #3, `agent/s2r-repro` |
| Deliverable commit | the payload commit named in `publish_receipt.json` and in the pull request |
| Old task under review | `S2R-REPRO-001`, plan `4462a7c048beebd1caed82a7c0ba1fc80d0cb16b` |
| Package provenance head | `253e3914a2da95bd5984b45c1559635f5f1621c3` |

**Read in this order:** [EXECUTION.md](EXECUTION.md) → the question table below → the raw records
in `reports/github_handoff_001/` → [budget.json](budget.json) → `publish_receipt.json`.

Evidence levels used below, kept apart on purpose:

- `EXECUTED_HERE` — this round ran it; `NOT_AVAILABLE` — the repository cannot show it;
- `TRANSCRIBED` — the previous round ran it and its log is committed, but this round did not repeat it;
- `DERIVED_FROM_RECORDS` — computed by reading fixed files, with the script committed;
- `SOURCE_READ` — read out of committed source, no run involved.

Nothing in this index is a new experimental result. This round ran no training, no pytest, no
cold build, no model load, no bootstrap, and opened no `.pt` or pickle file.

---

## Question table

### C01 — What did the old task do, and did it stay inside its plan?

| | |
| --- | --- |
| Fixed commits | plan `4462a7c…`, head `e0fc584…`, base `de266c4…`, checkout `253e391…` |
| Paths | `reports/github_handoff_001/s2r_task_window.json`; `clarifications.md` §7; `reports/s2r/SUMMARY.md`; old plan at `4462a7c:NEXT_ACTIONS.md` |
| Method | `derive_handoff_facts.py`; `git diff --numstat`, `git rev-parse`, `git merge-base --is-ancestor` |
| Result | Six commits map to T0–T4 with per-step diffstats. The increment `4462a7c..e0fc584` is **58 files, +6837/−50**, and every path is under `reports/s2r/` (51), `review/` (3), `tests/` (2) or `scripts/` (2) — none under `src/`, `native/`, `configs/`. T0 forbade changing the criterion; the round proposed a fix and did not apply it, ending BLOCKED. |
| Level | `DERIVED_FROM_RECORDS` |
| Limitation | Whether a change is "in scope" is a judgement, not a fact. The diffstats bound what was touched; they do not certify intent. Note that a `253e391..e0fc584` diff shows large `scripts/*.py` deletions that belong to upstream commits `5284add`/`152d78f`, which pre-date the old plan — do not attribute them to this task. |

### C02 — Does the T0 diagnosis justify changing the assertion?

| | |
| --- | --- |
| Fixed commit | `e0fc584…` |
| Paths | `reports/s2r/ci_failure_analysis.md` (§1 facts, §2 targeted runs, §3 per-parameter table, §4.1 gauge proof, §4.2 AdamW `eps` amplification, §5 the proposed fix); `reports/s2r/t0_gauge_check.json`; `reports/s2r/t0_gauge_check.py`; `reports/s2r/t0_partition_diagnose.py`; `reports/s2r/t0_runs_summary.json`; `reports/s2r/evidence/t0_run1_stdout.txt`, `t0_run1_exit.txt`, `t0_run1_historical_env.json`, `t0_run2_stdout.txt`, `t0_run2_exit.txt`, `t0_run2_cpu_torch.json`; `reports/s2r/evidence/ci_run_35369602279.log` and its `.gz` twin |
| Method | Two targeted runs in an isolated CPU environment, timeout 60 s each, on unmodified `stsai.training.train` with a synthetic fixture. Forward-only gauge check with no optimiser step. |
| Result | Both runs exit 0 and pass locally. `policy.2.bias` is a gauge direction (a constant added to every masked logit, cancelled by `log_softmax`): a ±0.5 forward shift changes loss by 0.0. Its measured gradient −2.7e−08 is a float32 cancellation residual, ~5 orders below every informative parameter; `AdamW(eps=1e-8)` amplifies it by `du/dg ≈ 2.25e3`, turning a 2% residual wobble into the observed 1.3e-06 parameter difference. The assertion assumes bit-reproducible parameters; that assumption fails on this direction. |
| Level | `TRANSCRIBED` — the receipts are committed, this round re-ran nothing |
| Limitation | This index records the diagnosis, **not** its adequacy. Whether it justifies the proposed criterion change is exactly what the reviewer must decide, and neither round has decided it. Two things remain open: the CI runner's CPU model is unrecorded, so the failing run cannot be reproduced bit for bit (only the mechanism can); and the local margin was only 8–14×, so local green does not establish that CI will be green. |

### C03 — Which version was actually under test?

| | |
| --- | --- |
| Fixed commits | `e0fc584…` (branch), `253e391…` (checkout), `2cc0c75…` (CI head) |
| Paths | `handoffs/GITHUB-HANDOFF-001/command_versions.json`; `reports/github_handoff_001/s2r_task_window.json` → `driver_versions`; `review/run_review.py` (lines ~42, ~112, ~151, ~209, ~240) |
| Method | Read the dispatch logic, then compare blob SHAs across trees |
| Result | `run_review.py` resolves its siblings from `Path(__file__).parent`, so `offline_native_build.py`, `counterfactual_replay.py` and `model_smoke.py` ran from the **branch**, not the checkout — though all four are byte-identical in both trees, so it makes no difference for them. `run_review.py` itself **differs** (`e83ff22d…` branch vs `4a46fe89…` checkout; the branch adds `--jobs`), and the package ships the older copy. `check_review_inputs.py` and `package_contract.py` exist **only** in the branch, so the validator was never part of the reviewed tree. `pytest` ran with `cwd`=checkout, so the tested `src/`, `tests/` and `scripts/gen_intent_table.py` are the checkout's. |
| Level | `SOURCE_READ` + `DERIVED_FROM_RECORDS` |
| Limitation | The worktree is clean at `e0fc584` *today*; the round did not record tree state at the moment each command ran. The four byte-identical drivers make that moot for those; for `run_review.py` it is an inference, though the only way the branch's `--jobs` flag could have been accepted is if the branch copy ran. |

### C04 — Did the 17 new tests ever run?

| | |
| --- | --- |
| Fixed commit | `e0fc584…` |
| Paths | `reports/github_handoff_001/new_tests_run_evidence.json`; `tests/test_review_inputs.py` (14 test functions, blob `77dd746a…`); `tests/test_run_review_jobs.py` (3 test functions, blob `8e14c708…`); `reports/s2r/t3/junit.xml` |
| Method | `git show` of both files at the head; substring search of the committed JUnit; search for any tracked log mentioning either filename |
| Result | **No run evidence exists.** The JUnit in the repository is `tests="277" failures="0" errors="0" skipped="0"`, timestamped `2026-09-18T17:09:19Z`, produced against the `253e391` checkout — a tree that predates both files and contains neither. No stdout, JUnit or exit code for the 17 tests is tracked anywhere. |
| Level | `DERIVED_FROM_RECORDS` |
| Limitation | Absence of a log is not evidence of failure. It means the repository cannot show these tests passed, and the 277-test figure must not be read as covering them. This is a real gap in PR #3's evidence and is called out rather than smoothed over. |

### C05 — Is the isolation claim supported?

| | |
| --- | --- |
| Fixed commit | `e0fc584…` |
| Paths | `handoffs/GITHUB-HANDOFF-001/clarifications.md` §1; `reports/s2r/t3_cold_review.py` lines **51** (`home = out / "isolated-home"`), **58–60** (the literal child `env` dict), **68–69** (`subprocess.run(..., env=env)`), **95–96** (`ssh_dir_exists`, `gh_config_exists` against the isolated home), **97–98** (`token_variables` read from the parent's `os.environ`); `reports/s2r/t3/cold_review.json` → `environment`; `reports/s2r/SUMMARY.md` §4 |
| Method | `SOURCE_READ` of the driver that produced the receipt, against the receipt itself |
| Result | The apparent contradiction resolves: `token_variables: ["ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_MESSAGING_TOKEN"]` is the **parent** process's environment, recorded to show what needed scrubbing. Every child received the explicit dict, and `env=` replaces rather than extends, so those names were not inherited. Supported claim: *the reviewed commands inherited no credential variable and used none.* Unsupported claim: *no credential was reachable* — the child shares the user and filesystem, and `ssh_dir_exists`/`gh_config_exists` are computed against the empty isolated home, so both being `false` proves the scrub worked, not that the real `~/.ssh` is unreachable. SUMMARY.md §4 already states the container-level limit honestly. |
| Level | `SOURCE_READ` |
| Limitation | Environment scrubbing is not a sandbox. No credential **value** appears anywhere in the delivered material — only two variable names the previous round's own driver wrote into its receipt. This round read no token, and asks for none. |

### C06 — How are the seven recovered artefacts traceable?

| | |
| --- | --- |
| Fixed commits | `e0fc584…`, package provenance `253e391…` |
| Paths | `reports/github_handoff_001/package/MANIFEST.sha256` (2993 B, 33 entries, verbatim); `reports/github_handoff_001/package/provenance.json` (9070 B, verbatim); `reports/s2r/artifact_lock.json`; `reports/s2r/input_receipt.json` (`entries`, 28 items, `gaps: []`, `checkpoint_hash_semantics`) |
| Method | Extracted the two files from the zip unmodified and re-hashed them |
| Result | Both extracted files match their `MANIFEST.sha256` entries exactly (`provenance.json` = `5754d0b4…`, `INDEX.md` = `bee629dd…`, `known_limitations.md` = `1a2dbd87…`, `commands_and_limits.md` = `c0467b8f…`, `command_log.txt` = `414b9bef…`, `semantic_compatibility.json` = `93fa711c…`). The zip is 12308133 B, SHA-256 `92a07276…`. All 7 previously-missing inputs were recovered byte-identically from `/workspaces/stsai_web`; `gaps` is now empty. The two D384_s17 hashes differ **by design** — `ce9ff924…` is the optimizer-free inference export, `7d758857…` is the training checkpoint that still carries optimizer state — and the receipt says a match would have meant a mislabelling. |
| Level | `DERIVED_FROM_RECORDS` |
| Limitation | `artifact_lock.json`'s field `package_manifest_sha256` holds the **zip's** hash, not the `MANIFEST.sha256` file's (`36a07ef7…`). The value is right; only the name misleads. See `clarifications.md` §3. |

### C07 — Is the 4096-episode recomputation complete?

| | |
| --- | --- |
| Fixed commit | `e0fc584…`; source records from the S2 evaluation |
| Paths | `reports/github_handoff_001/episodes/part_000…008.jsonl` (4096 lines); `reports/github_handoff_001/key_coverage.json` → `episodes`; `reports/github_handoff_001/shard_index.json`; `reports/s2r/t3/recomputed_s2.json`; `reports/s2r/t3/comparison.json` |
| Method | One streaming pass over `episodes.jsonl.gz`, counting keys and writing shards |
| Result | 2 sets × 8 policies × 256 = **4096 expected, 4096 distinct, 0 duplicates**, `episode_index` in 0…255. Per-group episode and truncated counts are tabulated in `key_coverage.json`. The round's independent recomputation reports 98 numeric fields matching `s2_paired_summary.json` bit for bit at a pre-declared 1e-9 tolerance (max difference 0.0), and the verdict is unchanged: still *insufficient evidence* under the pre-registered rule, joint mean 0.0093522135, 95% interval [−0.0034831543, 0.0233042806] spanning zero. |
| Level | `DERIVED_FROM_RECORDS` for the coverage; `TRANSCRIBED` for the recomputation |
| Limitation | Coverage proves the records are all present and uniquely keyed. It does **not** re-verify the round's own recomputation — that would be a new statistical run, which this round is not authorised to perform. The comparison figure is quoted, not re-derived. |

### C08 — Do the 59812 decisions correspond to the battles?

| | |
| --- | --- |
| Fixed commit | `e0fc584…` |
| Paths | `reports/github_handoff_001/decisions/part_000…119.jsonl` (59812 lines); `reports/github_handoff_001/key_coverage.json` → `decisions`; `reports/s2r/t3/input_receipt.json` → check `decision_records` |
| Method | One streaming pass: per-episode row counts, step-index contiguity from 0, and every row's `(set, policy, episode_index, step)` resolved against the episode records |
| Result | 59812 rows; every episode's actual row count equals its declared `decisions`; step indices are contiguous from 0 within each episode; **no** episode lacks decisions; **no** row points at an unknown episode or an out-of-range step. `declared_by_episodes` = 59812. This is the linkage the previous round asserted as the boolean "59812 decisions match the episodes step by step" — now shown as the underlying table. |
| Level | `DERIVED_FROM_RECORDS` |
| Limitation | This verifies internal consistency between two shipped files. It says nothing about whether either matches what the engine produced; that link runs through the engine, which this round did not build or run. |

### C09 — Are the two cold reviews and both budgets traceable?

| | |
| --- | --- |
| Fixed commits | `e0fc584…`; package `253e391…` |
| Paths | `reports/s2r/t3/cold_review.json`; `reports/s2r/t3/step_logs/` (six `.command.txt`, six `.stdout.log`, six `.stderr.log`, plus `pytest.log`, `build.log`, `configure.log`, `driver.log`, `offline_build_stdout.log`); `reports/s2r/t3/review_receipt.json`; `handoffs/GITHUB-HANDOFF-001/budget.json` |
| Method | Read the receipt; sum the per-step elapsed times and compare with the summary's prose |
| Result | The committed receipt is the **second** review: `1.2 + 0.1 + 0.0 + 1.2 + 27.9 + 2.7 = 33.1 s`, which is the "33.1 s" SUMMARY.md reports. All six steps exit 0. The **first** review (31.4 s) has no receipt, no per-step log and no exit code in this repository. Budgets are recorded in two separate scopes and never netted: `S2R-REPRO` closed at targeted runs 2/2 and cold reviews 2/2 with **no** reset, and `HANDOFF-PUBLISH-001` used 0.41 s of CPU and 41.5 MiB peak against a 10-minute / 512 MiB ceiling. |
| Level | `DERIVED_FROM_RECORDS` |
| Limitation | The first review is `EVIDENCE_NOT_AVAILABLE`, not `PASS`. The summary's "about 3 minutes total" and "10–20 s each" for the T0 runs are approximations; `budget.json` lists them under `unknowns_not_zeros` rather than rounding them into a figure. |

---

## Raw records delivered this round

| Path | Records | Shards | SHA-256 of the compressed source | Level |
| --- | --- | --- | --- | --- |
| `reports/github_handoff_001/episodes/` | 4096 per-episode | 9 (`part_000`…`part_008`) | `55e03a6a…154f30a` (184546 B) | `EXECUTED_HERE` |
| `reports/github_handoff_001/decisions/` | 59812 per-decision | 120 (`part_000`…`part_119`) | `c0c8ac50…49a835a3d2` (861961 B) | `EXECUTED_HERE` |

Shards are ≤500 lines and ≤200 KiB. The lines are the input's, verbatim and in order; the split
is the only transformation. `shard_roundtrip.json` records that concatenating the shards
reproduces the decompressed input exactly, for both files, and `shard_index.json` carries each
shard's path, byte count, digest and record range plus both the compressed and decompressed
digest of each source. Per-file detail is in [files.json](files.json).

## Evidence already in git at the code base — referenced, not duplicated

`reports/s2r/SUMMARY.md`, `ci_failure_analysis.md`, `input_receipt.json`, `artifact_lock.json`,
`t0_gauge_check.{py,json}`, `t0_partition_diagnose.py`, `t0_runs_summary.json`,
`evidence/` (CI log and both T0 run receipts), `t3/` (cold review, review receipt, JUnit,
recomputation, comparison, counterfactual, model smoke, native build receipt, step logs),
`t3_cold_review.py`, `t3_compare.py`. All are readable at
`e0fc584d19afe58ac10b65c93c7bcc75a2630f05`; this round copies none of them.

## Not available

| Item | Status | Effect on what a reviewer can conclude |
| --- | --- | --- |
| A run log for the 17 new tests | `NOT_AVAILABLE` | Cannot confirm they execute; cannot treat the 277-test figure as covering them |
| The first cold review's per-step receipt | `NOT_AVAILABLE` | Only one of the two reviews can be audited |
| The failing CI runner's CPU model | `NOT_AVAILABLE` | The precise CI residual is unreproducible; only the mechanism is established |
| Model weights and any inspection of them | `NOT_AVAILABLE` | Weights are cited by hash only; no claim of model validation is made |
| GCC 14 / CUDA / original-game differential | `NOT_RUN` (unchanged) | `game_differential_verified=false` stands; no G3 evidence exists |
| Any new experiment | `NOT_RUN` by design | Every strength and statistics figure in this index is quoted from a previous round |
