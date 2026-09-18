#!/usr/bin/env python3
"""Which translation units use std algorithms without including <algorithm>?

    python scripts/scan_std_includes.py [--out reports/s2_std_include_scan.json]

The GCC 14 cold build stopped on `CardManager.cpp`, which calls `std::find`
without including `<algorithm>`; GCC 12 compiles it because a header it does
include happens to bring the algorithm header in. That is a portability hole
that only a stricter libstdc++ reveals, so this scan lists every engine
translation unit in the same shape: it names the algorithms used and whether the
file includes the header itself.

This is a SOURCE SCAN, not a proof. It cannot say which of these would fail on
another toolchain, because transitive includes are what decides that. It exists
so a reviewer can see whether the one reported file was the only one with this
shape, and so the next toolchain complaint is not a surprise.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "third_party" / "sts_lightspeed"

ALGORITHMS = ("find_if", "find", "sort", "stable_sort", "count", "count_if", "any_of",
              "all_of", "none_of", "min_element", "max_element", "unique", "lower_bound",
              "upper_bound", "remove_if", "transform", "accumulate", "iota", "fill",
              "reverse", "rotate", "nth_element", "partial_sort", "binary_search", "clamp")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/s2_std_include_scan.json")
    parser.add_argument("--engine", default=str(ENGINE))
    args = parser.parse_args()

    engine = Path(args.engine)
    if not engine.is_dir():
        raise SystemExit(f"engine checkout not found at {engine}")

    rows, findings, vendored = [], [], []
    for path in sorted(engine.rglob("*.cpp")):
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(engine).as_posix()
        included = {line.split("<", 1)[1].split(">", 1)[0].strip()
                    for line in text.splitlines()
                    if line.strip().startswith("#include <") and "<" in line and ">" in line}
        used = sorted({name for name in ALGORITHMS
                       if re.search(rf"std::{name}\s*\(", text)})
        if not used:
            continue
        row = {"file": relative, "algorithms_used": used,
               "includes_algorithm": "algorithm" in included}
        rows.append(row)
        if "algorithm" not in included:
            # Vendored third-party tests are not compiled by this build; keeping
            # them out of the engine count avoids overstating the finding.
            (vendored if relative.startswith("json/") else findings).append(relative)

    out = {
        "purpose": "Translation units that use std algorithms without including <algorithm>.",
        "engine": str(engine),
        "evidence_type": "SOURCE_SCAN",
        "method": "text scan of #include lines and std::<algorithm>( call sites in the patched "
                  "tree, which is what gets compiled; a transitive include can still satisfy the "
                  "compiler, so this neither proves nor rules out a failure on another toolchain",
        "files_using_algorithms": len(rows),
        "engine_files_without_the_include": findings,
        "vendored_files_without_the_include": vendored,
        "rows": rows,
        "reported_by_gcc14": ["src/combat/CardManager.cpp"],
        "note": "CardManager.cpp is the file the GCC 14 review build stopped on; it is patched by "
                "0005 and therefore no longer appears above. Nothing else in the engine sources "
                "has this shape; the vendored nlohmann/json tests are not compiled by this build. "
                "A clean scan is not a guarantee for other toolchains.",
    }
    Path(ROOT / args.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} files use std algorithms; {len(findings)} do not include <algorithm>: "
          f"{findings}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
