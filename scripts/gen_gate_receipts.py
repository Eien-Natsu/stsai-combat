#!/usr/bin/env python3
"""Run the four S1R gates and record what actually happened.

    python scripts/gen_gate_receipts.py [--clone /tmp/...]

Every receipt line is produced by running the command here: the exit code is the
command's own, the log is its raw output, and the evidence type says whether it
was an actual run, a source argument or a declared approximation. Nothing is
copied from an earlier report, and a step that cannot run is recorded as NOT_RUN
rather than omitted.

G3 builds the extension from the offline snapshot in a fresh clone of this
repository, so "one command, new directory" is demonstrated rather than
asserted. Training is authorised only when all four gates pass.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "reports" / "s1r_gates"
PYTHON = sys.executable


def versions():
    sys.path.insert(0, str(ROOT / "src"))
    from stsai.encoding import ENCODING_REVISION
    from stsai.util import LOSS_REVISION, SCHEMA_VERSION
    out = {"encoding_revision": ENCODING_REVISION, "observation_schema": SCHEMA_VERSION,
           "loss_revision": LOSS_REVISION}
    try:
        from stsai.native import SAMPLER_REVISION
        out["sampler_revision"] = SAMPLER_REVISION
    except Exception:  # the module may not be built yet when the receipts are written
        out["sampler_revision"] = "native module not importable"
    return out


def run(item, command, log_name, cwd=ROOT, evidence_type="ACTUAL_RUN", env=None):
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / log_name
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env)
    log.write_text(f"$ {' '.join(map(str, command))}\n\n{result.stdout}\n{result.stderr}",
                   encoding="utf-8")
    tail = [line for line in (result.stdout + result.stderr).strip().splitlines() if line.strip()]
    return {"item": item, "command": " ".join(map(str, command)), "exit_code": result.returncode,
            "status": "PASS" if result.returncode == 0 else "FAIL", "log": str(log.relative_to(ROOT)),
            "evidence_type": evidence_type, "summary": tail[-1][:200] if tail else ""}


def pytest_item(item, node_ids, log_name, evidence_type="ACTUAL_RUN"):
    command = [PYTHON, "-m", "pytest", "-q"] + node_ids
    return run(item, command, log_name, evidence_type=evidence_type)


def g1():
    return [
        pytest_item("four legal attack-base states encode differently and are normalized",
                    ["tests/test_encoding_public_range.py"], "g1_encoding_states.txt"),
        pytest_item("the reviewer's red-light sensitivity case now passes",
                    ["tests/test_review_gate.py::test_public_attack_base_reaches_encoder"],
                    "g1_review_gate.txt"),
        pytest_item("the native adapter may not omit the memory; hidden values are refused",
                    ["tests/test_encoding_public_range.py::"
                     "test_a_native_observation_may_not_omit_the_memory",
                     "tests/test_encoding_public_range.py::"
                     "test_only_the_public_interval_reaches_the_encoder",
                     "tests/test_encoding_public_range.py::"
                     "test_a_backend_without_the_parameter_declares_it_absent"],
                    "g1_contract.txt"),
        pytest_item("a checkpoint from the older encoding is refused",
                    ["tests/test_entry_contracts.py::"
                     "test_a_missing_revision_is_treated_as_the_old_one_not_the_current_one"],
                    "g1_old_weights.txt"),
    ]


def g2():
    return [
        run("the declared series applies in order to a clean locked checkout",
            [PYTHON, "scripts/patch_series_receipt.py"], "g2_patch_series.txt"),
        pytest_item("content, not filenames: extra bytes, removed fragments, half-applied series, "
                    "untracked files are all refused",
                    ["tests/test_engine_tree_check.py"], "g2_tree_check.txt"),
        run("the offline snapshot is PRE_PATCH and ships every licence",
            [PYTHON, "-c",
             "import json;m=json.load(open('native_sources_manifest.json'));"
             "print(m['patch_state'][:60]);"
             "print([f['path'] for f in m['files'] if 'LICENSE' in f['path']]);"
             "assert all(f['patch_state']=='PRE_PATCH' for f in m['files'] "
             "if f['origin']=='sts_lightspeed');"
             "assert any('pybind11' in f['path'] for f in m['files']);"
             "assert m['engine']['patch_order']"],
            "g2_snapshot.txt"),
    ]


def g3(clone_source):
    """Build and test from a fresh clone, in the reviewed order."""
    work = Path(tempfile.mkdtemp(prefix="stsai-g3-"))
    clone = work / "repo"
    subprocess.run(["git", "clone", "-q", str(clone_source), str(clone)], check=True)
    receipt_dir = LOGS
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = receipt_dir / "g3_review_receipt.json"
    command = [PYTHON, str(ROOT / "review" / "run_review.py"), "--repo", str(clone),
               "--sources", str(ROOT / "native_sources.tar.gz"), "--work", str(work / "review"),
               "--receipt", str(receipt)]
    log = LOGS / "g3_review_run.txt"
    result = subprocess.run(command, capture_output=True, text=True)
    log.write_text(f"$ {' '.join(map(str, command))}\n\n{result.stdout}\n{result.stderr}",
                   encoding="utf-8")
    items = [{"item": "offline build, import, intent, native pytest and counterfactual from a "
                      "fresh clone", "command": " ".join(map(str, command)),
              "exit_code": result.returncode, "status": "PASS" if result.returncode == 0 else "FAIL",
              "log": str(log.relative_to(ROOT)), "evidence_type": "ACTUAL_RUN",
              "summary": (result.stdout.strip().splitlines() or [""])[-1][:200]}]
    if receipt.is_file():
        detail = json.loads(receipt.read_text())
        for row in detail["steps"]:
            items.append({"item": f"review step: {row['step']}", "command": "run_review.py",
                          "exit_code": 0 if row["status"] == "PASS" else (2 if row["status"] == "NOT_RUN" else 1),
                          "status": row["status"], "log": str(log.relative_to(ROOT)),
                          "evidence_type": "ACTUAL_RUN", "summary": row["note"][:200]})
    shutil.rmtree(work, ignore_errors=True)
    return items


def g4():
    return [
        pytest_item("all heads share one batch",
                    ["tests/test_entry_contracts.py::test_every_head_must_share_one_batch",
                     "tests/test_entry_contracts.py::"
                     "test_loss_numerators_rejects_a_broadcasting_decision_mask",
                     "tests/test_entry_contracts.py::test_the_accepting_batch_still_works"],
                    "g4_batch.txt"),
        pytest_item("the three checkpoint entry points refuse a native checkpoint with no sampler",
                    ["tests/test_entry_contracts.py::"
                     "test_every_entry_point_refuses_a_native_checkpoint_with_no_sampler_revision",
                     "tests/test_entry_contracts.py::test_load_checkpoint_rejects_stale_semantics",
                     "tests/test_entry_contracts.py::"
                     "test_warm_start_and_resume_reject_the_same_stale_semantics"],
                    "g4_checkpoint.txt"),
        pytest_item("the reviewer's ambiguity trace and the same-turn lifecycle case",
                    ["tests/test_ambiguity_regression.py",
                     "tests/test_louse_hidden_base.py"], "g4_regression.txt"),
        pytest_item("the audit is labelled coverage, and every field states its evidence kind",
                    ["tests/test_native_coverage.py::"
                     "test_the_field_audit_does_not_decide_categories_by_scan"],
                    "g4_audit.txt"),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/gate_receipts.json")
    parser.add_argument("--clone", default=None,
                        help="repository to clone for G3; defaults to this working tree")
    args = parser.parse_args()

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    baseline = json.loads((ROOT / "reports" / "s1r_protocol.json").read_text())["baseline"]
    gates = {"G1_input": g1(), "G2_provenance": g2(),
             "G3_execution": g3(Path(args.clone or ROOT)), "G4_contracts": g4()}
    for name, items in gates.items():
        failed = [i for i in items if i["status"] == "FAIL"]
        not_run = [i for i in items if i["status"] == "NOT_RUN"]
        gates[name] = {"items": items,
                       "status": "FAIL" if failed else ("NOT_RUN" if not_run else "PASS")}
        print(f"{gates[name]['status']:7s} {name}")
        for item in items:
            print(f"    {item['status']:7s} {item['item'][:90]}")

    all_pass = all(gate["status"] == "PASS" for gate in gates.values())
    receipt = {
        "purpose": "S1R gate receipts. Every line is a command run for this file.",
        "baseline": baseline, "head": head,
        "versions": versions(),
        "resource_limits": json.loads((ROOT / "reports" / "s1r_protocol.json").read_text())["resource_limits"],
        "gates": gates,
        "claim": "unverified simulator pilot with a declared sampling approximation; "
                 "game_differential_verified=false",
        "training_authorised": all_pass,
        "verdict": "PASS" if all_pass else "BLOCKED",
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"{receipt['verdict']}: wrote {out}")
    raise SystemExit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
