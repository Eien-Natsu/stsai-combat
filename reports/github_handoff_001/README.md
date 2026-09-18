# reports/github_handoff_001 — the S2 records, made readable

These files exist so that a reviewer with no access to the execution machine can read the
evidence PR #3 delivered. Before this round, the per-episode and per-decision records lived only
in a git-ignored `runs/` tree (`/workspaces/stsai_web/runs/s2/evaluation/`) and inside a 12 MB
zip, so "4096 episodes" and "59812 decisions" were claims backed by nothing a reviewer could
open. They are open now.

Start with `handoffs/GITHUB-HANDOFF-001/EVIDENCE_INDEX.md`; this file only explains the layout.

## What is here

| Path | What it is |
| --- | --- |
| `episodes/part_000.jsonl` … `part_008.jsonl` | all 4096 per-episode records, in file order |
| `decisions/part_000.jsonl` … `part_119.jsonl` | all 59812 per-decision records, in file order |
| `shard_index.json` | per-shard path, bytes, SHA-256, record range; plus input digests |
| `key_coverage.json` | the 2×8×256 episode grid and the decision-to-episode linkage |
| `shard_roundtrip.json` | proof the shards concatenate back to the decompressed input |
| `s2r_task_window.json` | the old task's commits mapped to T0–T4, with diffstats |
| `new_tests_run_evidence.json` | what the repository can and cannot show about the 17 new tests |
| `package/` | verbatim `MANIFEST.sha256` and `provenance.json` from the zip, plus four more documents |
| `convert_s2_records.py`, `derive_handoff_facts.py`, `make_files_json.py` | the scripts that produced the above |

## Normalisation: there is none

The shards are the input lines copied verbatim, in the input's order. The only thing this round
decided is **where each shard ends** — at 500 lines or 200 KiB, whichever comes first. No field
was dropped, renamed, reordered or reformatted; no number was re-serialised; no record was
filtered. Numbers therefore keep their original text, so a shard's `utility` or `ms` value is the
byte sequence the S2 run wrote, not a round-trip through a different float formatter.

Because the split is the only transformation, it is checkable rather than asserted:
`shard_roundtrip.json` records that concatenating the shards in index order reproduces the
decompressed input byte for byte, and `shard_index.json` carries both the compressed and the
decompressed digest of each source.

| Source | Compressed | Decompressed | SHA-256 (compressed) | Records |
| --- | --- | --- | --- | --- |
| `episodes.jsonl.gz` | 184546 B | 1404811 B | `55e03a6a…154f30a` | 4096 → 9 shards |
| `decision_latency.jsonl.gz` | 861961 B | 8323805 B | `c0c8ac50…49a835a3d2` | 59812 → 120 shards |

Both digests match `reports/s2r/artifact_lock.json` and the zip's `MANIFEST.sha256`, which is how
these shards are tied back to the delivered package rather than to some other copy.

## Reproducing

```bash
python3 reports/github_handoff_001/convert_s2_records.py \
    --evaluation /workspaces/stsai_web/runs/s2/evaluation \
    --out reports/github_handoff_001
python3 reports/github_handoff_001/derive_handoff_facts.py --out reports/github_handoff_001
python3 reports/github_handoff_001/make_files_json.py
```

The first command needs the ignored `runs/` tree; the other two need only this repository. A
reviewer cannot run any of them from a clone and does not need to — the outputs are committed.

## What these records do not show

They are S2's evaluation output, so they inherit S2's limits: `game_differential_verified=false`,
23 card IDs and 17 encounters rather than the full game, and both `dev_old256` and `dev_probe256`
already used as development sets. Nothing in this directory is new evidence about strength, and
the paired comparison's conclusion is unchanged — under the pre-registered rule the fixed-budget
contrast is still *insufficient evidence*, its 95% interval still spanning zero.
