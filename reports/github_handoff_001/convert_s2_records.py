#!/usr/bin/env python3
"""Split the S2 per-episode and per-decision records into reviewer-readable text shards.

    python reports/github_handoff_001/convert_s2_records.py \
        --evaluation <runs/s2/evaluation> --out reports/github_handoff_001

The two inputs (episodes.jsonl.gz, decision_latency.jsonl.gz) are git-ignored and
live outside the repository, so a fresh reviewer cannot read them.  This script
streams them once and writes the *same lines, byte for byte, in the same order*
into shards that fit the repository's reading budget.

Normalisation is deliberately limited to where the line breaks fall: no field is
dropped, renamed, reordered, reformatted or filtered, and no line is rewritten.
Numbers keep their original serialisation, so a shard's lines concatenated in
order reproduce the decompressed input exactly - the index records both hashes so
that this claim is checkable rather than asserted.

It also derives two coverage tables from the records themselves (which episode
keys exist, and whether the per-decision rows line up with the episodes they
claim to belong to), because "59812 decisions match the episodes step by step"
is otherwise only available as a boolean in a previous round's receipt.
"""
import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path

MAX_LINES = 500
MAX_BYTES = 200 * 1024


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def split(source, out_dir, prefix):
    """Stream `source` into shards capped by line count and byte size."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shards = []
    lines = 0
    written = 0
    shard = None
    start_line = 0
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if shard is None:
                path = out_dir / f"{prefix}_{len(shards):03d}.jsonl"
                shard = open(path, "w", encoding="utf-8", newline="")
                written = 0
                start_line = lines
            shard.write(raw)
            lines += 1
            written += len(raw.encode("utf-8"))
            if lines - start_line >= MAX_LINES or written >= MAX_BYTES:
                shard.close()
                shards.append((path, start_line, lines - start_line, written))
                shard = None
    if shard is not None:
        shard.close()
        shards.append((path, start_line, lines - start_line, written))
    return lines, shards


def entries_of(shards, repo_root):
    return [
        {
            "path": str(path.relative_to(repo_root)),
            "bytes": size,
            "sha256": sha256_file(path),
            "first_record_index": start,
            "records": count,
        }
        for path, start, count, size in shards
    ]


def read_records(paths, root):
    for entry in paths:
        with open(root / entry["path"], encoding="utf-8") as handle:
            for raw in handle:
                yield json.loads(raw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", required=True,
                        help="directory holding episodes.jsonl.gz and decision_latency.jsonl.gz")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    evaluation = Path(args.evaluation).resolve()
    out = Path(args.out).resolve()
    repo_root = out.parent.parent
    episodes_gz = evaluation / "episodes.jsonl.gz"
    decisions_gz = evaluation / "decision_latency.jsonl.gz"

    sources = {}
    for name, gz in (("episodes", episodes_gz), ("decisions", decisions_gz)):
        raw = gzip.decompress(gz.read_bytes())
        sources[name] = {
            "compressed_source_path": str(gz),
            "compressed_bytes": gz.stat().st_size,
            "compressed_sha256": sha256_file(gz),
            "decompressed_bytes": len(raw),
            "decompressed_sha256": hashlib.sha256(raw).hexdigest(),
            "decompressed_lines": raw.count(b"\n"),
        }

    episode_lines, episode_shards = split(episodes_gz, out / "episodes", "part")
    decision_lines, decision_shards = split(decisions_gz, out / "decisions", "part")
    episode_index = entries_of(episode_shards, repo_root)
    decision_index = entries_of(decision_shards, repo_root)

    # Coverage derived from the records, not from a previous round's summary.
    episode_keys = {}
    per_set_policy = {}
    declared_decisions = {}
    for record in read_records(episode_index, repo_root):
        key = (record["set"], record["policy"], record["episode_index"])
        episode_keys[key] = episode_keys.get(key, 0) + 1
        bucket = f"{record['set']}|{record['policy']}"
        stats = per_set_policy.setdefault(
            bucket, {"set": record["set"], "policy": record["policy"], "episodes": 0,
                     "declared_decisions": 0, "seen_decisions": 0, "won": 0,
                     "truncated": 0, "completed": 0})
        stats["episodes"] += 1
        stats["declared_decisions"] += record["decisions"]
        stats["won"] += int(bool(record["won"]))
        stats["truncated"] += int(bool(record["truncated"]))
        stats["completed"] += int(bool(record["completed"]))
        declared_decisions[key] = record["decisions"]

    seen_decisions = {}
    step_sequence_ok = True
    out_of_range = 0
    for record in read_records(decision_index, repo_root):
        key = (record["set"], record["policy"], record["episode_index"])
        seen_decisions[key] = seen_decisions.get(key, 0) + 1
        if record["step"] != seen_decisions[key] - 1:
            step_sequence_ok = False
        if key not in declared_decisions or record["step"] >= declared_decisions[key]:
            out_of_range += 1
    for bucket, stats in per_set_policy.items():
        stats["seen_decisions"] = sum(
            count for (s, p, _), count in seen_decisions.items()
            if f"{s}|{p}" == bucket)

    episode_key_report = {
        "distinct_keys": len(episode_keys),
        "duplicate_keys": sorted(
            f"{s}|{p}|{i}" for (s, p, i), count in episode_keys.items() if count > 1),
        "expected_keys": 2 * 8 * 256,
        "grid": sorted(per_set_policy.values(), key=lambda row: (row["set"], row["policy"])),
        "episode_index_min": min(i for (_, _, i) in episode_keys),
        "episode_index_max": max(i for (_, _, i) in episode_keys),
    }
    decision_key_report = {
        "total_rows": decision_lines,
        "declared_by_episodes": sum(declared_decisions.values()),
        "distinct_episode_keys_seen": len(seen_decisions),
        "episodes_without_any_decision": sorted(
            f"{s}|{p}|{i}" for (s, p, i) in declared_decisions if (s, p, i) not in seen_decisions),
        "episodes_with_wrong_decision_count": sorted(
            f"{s}|{p}|{i}: declared {declared_decisions[(s, p, i)]}, seen {count}"
            for (s, p, i), count in seen_decisions.items()
            if declared_decisions.get((s, p, i)) != count),
        "step_index_contiguous_from_zero_per_episode": step_sequence_ok,
        "rows_pointing_at_an_unknown_episode_or_step": out_of_range,
        "per_set_policy": sorted(per_set_policy.values(), key=lambda row: (row["set"], row["policy"])),
    }

    index = {
        "kind": "s2_record_text_shards",
        "normalisation": "none: input lines are copied verbatim, in file order; only the "
                         "line at which a shard ends is chosen here",
        "limits": {"max_lines_per_shard": MAX_LINES, "max_bytes_per_shard": MAX_BYTES},
        "sources": sources,
        "episodes": {"records": episode_lines, "shards": episode_index},
        "decisions": {"records": decision_lines, "shards": decision_index},
    }
    (out / "shard_index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "key_coverage.json").write_text(
        json.dumps({"kind": "s2_record_key_coverage",
                    "episodes": episode_key_report,
                    "decisions": decision_key_report},
                   indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"episodes  {episode_lines} records -> {len(episode_index)} shards")
    print(f"decisions {decision_lines} records -> {len(decision_index)} shards")
    print(f"episode keys {len(episode_keys)} distinct, duplicates "
          f"{len(episode_key_report['duplicate_keys'])}")
    print(f"decision linkage ok={step_sequence_ok and not out_of_range and not decision_key_report['episodes_with_wrong_decision_count']}")


if __name__ == "__main__":
    main()
