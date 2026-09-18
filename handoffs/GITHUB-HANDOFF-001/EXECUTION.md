# EXECUTION — GITHUB-HANDOFF-001

Written for the next reader, who is a fresh Chat with no memory of this session and no access to
this machine: only the files in this repository at fixed commits.

## Snapshot

| Field | Value |
| --- | --- |
| Task ID | `GITHUB-HANDOFF-001` |
| Request ID | `manual-chat-github-handoff-001` (owner-initiated in chat; no event-task ID exists) |
| Executor session ID | `manual-session-github-handoff-001` — **generated record ID**, not a native session identifier. The protocol requires a session ID per handoff; this session has no externally issued one, and the previous round's is unrecorded, so this is declared rather than invented. |
| Plan / control commit | `5c331ca8c043c951b5ea9687fc7b92b3566ee21d` |
| Code base | `e0fc584d19afe58ac10b65c93c7bcc75a2630f05` |
| Implementation branch | `agent/github-handoff-001`, branched from the code base |
| PR base | `agent/s2r-repro` (so the pull request shows only this round's increment) |
| Source review | `handoffs/BOOTSTRAP-GITHUB-ONLY/REVIEW.md` at the plan commit |
| Old task under review | `S2R-REPRO-001` / PR #3, plan `4462a7c048beebd1caed82a7c0ba1fc80d0cb16b` |
| Worktree used | `/home/node/stsai-handoff-001` (new; the pre-existing `/home/node/stsai-s2r` and `/workspaces/stsai_web` were left untouched) |
| Final HEAD | written into the pull request after the commit; this file does not contain its own commit's SHA |

## Goal and context

The next reviewer can read only what is pushed to this repository, and has no memory of any
earlier chat. PR #3 delivered a real but partly unreachable evidence set: the per-episode and
per-decision records, the package manifest and provenance, and one isolation claim that reads
like a contradiction all lived outside git — in a git-ignored `runs/` tree and inside a 12 MB
zip. This round converts those into paged, self-contained text in the repository and writes the
version map someone needs to tell which code a given command actually exercised.

This round is **not** a re-run of S2R. It changes no assertion, no tolerance, no loss, no
optimizer, no model, no test, and it does not reset the old budget.

## Execution

Two commands ran this session. Everything else is transcription or derivation from records
already in the repository, and is labelled as such throughout.

### Actually executed

Both were run from `/home/node/stsai-handoff-001`, single worker, streaming, no network.

**1. `reports/github_handoff_001/convert_s2_records.py`** — splits the two git-ignored record
files into text shards.

```
python3 reports/github_handoff_001/convert_s2_records.py \
    --evaluation /workspaces/stsai_web/runs/s2/evaluation \
    --out reports/github_handoff_001
```

| | |
| --- | --- |
| Exit code | 0 |
| Wall / user / sys | 0.25 s / 0.19 s / 0.06 s |
| Peak RSS | 34.4 MiB |
| Inputs | `episodes.jsonl.gz` sha256 `55e03a6a…154f30a`, 184546 B; `decision_latency.jsonl.gz` sha256 `c0c8ac50…49a835a3d2`, 861961 B |
| Output | 4096 episode records → 9 shards; 59812 decision records → 120 shards |

**2. `reports/github_handoff_001/derive_handoff_facts.py`** — reads the fixed commits and the
shards to produce `s2r_task_window.json`, `new_tests_run_evidence.json`, `shard_roundtrip.json`.

| | |
| --- | --- |
| Exit code | 0 |
| Wall / user / sys | 0.16 s / 0.12 s / 0.05 s |
| Peak RSS | 41.5 MiB |

**Round-trip check.** Concatenating the shards in index order reproduces the decompressed input
byte for byte, for both files (`shard_roundtrip.json`, `identical: true` for each). This is what
lets the shards stand in for the original records: the normalisation is only *where the line
breaks fall*, never the content of a line.

### Transcribed from the previous round, not re-run

T0's two targeted runs, the six cold-review steps, the 277-test pytest, the cold native build,
the counterfactual replay, the 12-observation model smoke and the 4096-episode recomputation are
all **transcribed** from PR #3's committed logs. This round executed none of them and could not
have: they are outside its authorisation. `command_versions.json` gives each one's command, cwd,
driver blob, code under test, inputs, environment and exit code, with its evidence paths.

### Derived by reading, not by measuring

`s2r_task_window.json`, `new_tests_run_evidence.json` and the two coverage tables in
`key_coverage.json` are computed from git objects and from the records themselves. They contain
no new experimental measurement.

### Not done, and why

| Item | Status | Reason |
| --- | --- | --- |
| Any training, optimisation, collection, play-out, inference | not run | Explicitly 0 for this round; only the old budget's existing usage is reported |
| Any pytest, cold build, model load, statistical bootstrap | not run | Same; and `pickle`/`.pt` files were deliberately never opened — only their hashes from the lock file are cited |
| The 17 new tests | not run | Out of scope, and running them is exactly what the *reviewer* must decide to authorise |
| GCC 14, CUDA, original-game differential | not run | Unchanged from the previous round; still `NOT_RUN` |

### Failures, skips and timeouts

None this round: both commands exited 0. The previous round's failures and gaps are preserved
rather than tidied — the two CI `FAILURE` checks on PR #3, the `NOT_RUN` items in `SUMMARY.md`
§5, the `game_differential_verified=false` flag, and the T0 assertion question that the round
handed back rather than fixed.

## Claim → evidence

Each row of the task's question table, and where its answer lives. Full paths, blob SHAs and
byte counts are in [EVIDENCE_INDEX.md](EVIDENCE_INDEX.md) and [files.json](files.json).

| Question | Answer | Where |
| --- | --- | --- |
| What did the old task do, and did it overreach? | Six commits mapped to T0–T4 with per-step diffstats; the increment `4462a7c..e0fc584` is 58 files, none under `src/`, `native/` or `configs/`. The T0 criterion fix was proposed and deliberately not applied. | `reports/github_handoff_001/s2r_task_window.json`; [clarifications.md](clarifications.md) §7 |
| Does the T0 diagnosis justify changing the assertion? | Diagnosis with gauge-direction proof, a forward-only gauge check, and the AdamW `eps` amplification arithmetic. Whether that justifies the proposed criterion change is the reviewer's call — this round takes no position. | `reports/s2r/ci_failure_analysis.md`, `reports/s2r/t0_gauge_check.json`, `reports/s2r/evidence/` (all at the code base) |
| Which version was tested? | Per-command driver blob vs code-under-test commit. Four drivers are byte-identical in both trees; `run_review.py` is not; two files exist only in the branch. | [command_versions.json](command_versions.json) |
| Did the 17 new tests run? | No evidence they ever did. Source is committed; no log, no JUnit, no exit code. The 277-test JUnit is the checkout's and does not cover them. | `reports/github_handoff_001/new_tests_run_evidence.json` |
| Is the isolation claim supported? | Supported for "no credential variable was inherited"; **not** supported for "no credential was reachable". The confusing `token_variables` field reads the parent's environment. | [clarifications.md](clarifications.md) §1 |
| How are the seven artefacts traceable? | Verbatim `MANIFEST.sha256` and `provenance.json` from the zip, matching the lock file; per-entry source hashes in the existing receipt. | `reports/github_handoff_001/package/`, `reports/s2r/input_receipt.json` |
| Is the 4096-episode recomputation complete? | All 4096 records published as shards; 2 sets × 8 policies × 256 keys, 4096 distinct, 0 duplicates, index range 0–255. | `reports/github_handoff_001/episodes/`, `key_coverage.json` |
| Do the 59812 decisions correspond to the battles? | All 59812 published as shards; every episode's decision count matches its declared count, step indices are contiguous from 0, no orphan rows, no episode without decisions. | `reports/github_handoff_001/decisions/`, `key_coverage.json` |
| Are the two cold reviews and the budget traceable? | Only the second review is in the repository (its step times sum to the 33.1 s the summary reports); the first is `EVIDENCE_NOT_AVAILABLE`. Budgets are split old-range vs this-round. | [clarifications.md](clarifications.md) §2, [budget.json](budget.json) |

## Budget

`budget_scope_id` for this round: `HANDOFF-PUBLISH-001` (text organisation only).
The old scope `S2R-REPRO` is unchanged and not reset. Full accounting, including what is
`unknown` rather than zero, is in [budget.json](budget.json). Summary:

| | Authorised | Used | Remaining |
| --- | --- | --- | --- |
| This round, CPU | 1 worker, ≤10 min cumulative | 2 commands, 0.25 s + 0.16 s CPU | effectively untouched |
| This round, memory | ≤512 MiB | 41.5 MiB peak | — |
| This round, experiments | 0 | 0 | 0 |
| Old range, targeted runs | 2 | 2 | 0 |
| Old range, complete cold reviews | 2 | 2 | 0 |

## Availability and limitations

- **The 59812-decision and 4096-episode records are now readable**, which they were not before:
  they lived in a git-ignored `runs/` tree and a 12 MB zip. The shards are the records
  themselves, not a summary of them.
- **No model weight is published, and none was loaded.** `D384_s17_selected.pt` is cited by
  hash only. A reviewer cannot inspect the weights from this repository, and this round does not
  claim the model was validated.
- **The 17 new tests remain unverifiable from the repository.** This is a real gap in PR #3's
  evidence, now stated plainly instead of implied by a test count.
- **The cold review's first run is lost to the record.** The second run is fully auditable.
- **The engine, the game differential and the coverage limits are untouched**:
  `game_differential_verified=false`, 23 card IDs and 17 encounters, no original-game comparison.
  Nothing here should be read as improving any of that.
- **`runs/`, `data/` and `logs/` are git-ignored**, so the shards are the only copies of those
  records inside the repository. Their provenance back to the ignored originals is by hash, in
  `shard_index.json`.

## Publication

Pushed branch `agent/github-handoff-001`, pull request opened against `agent/s2r-repro`. After
pushing, every new required file is read back from the remote commit and compared by Git blob
and byte digest; the result is `publish_receipt.json`, added in a second commit so that it can
name the payload commit it verified without referencing itself.

## Exit

**Status: `DELIVERED_WAITING_REVIEW`.** The material a fresh reviewer needs to work through the
question table is in the repository and read back from the remote. This is a statement about
reachability, not about the science: PR #3 is **not** reviewed, accepted or merged by this round,
and nothing here should be read as approving the T0 criterion change, the CI failure, or the S2
statistical conclusion.

Open questions for the reviewer, unchanged from PR #3 and not decided here:

1. Whether to approve the minimal T0 assertion change (`ci_failure_analysis.md` §5).
2. Whether the other five models need loading and evaluating, and at what budget.
3. Whether a GCC 14 recheck is required, and in which authorised environment.
4. What to do about the 17 tests having no run evidence.

Next role: `NEW_CHAT_REVIEWER`. This session ends here.
