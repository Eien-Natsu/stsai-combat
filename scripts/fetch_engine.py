#!/usr/bin/env python3
"""Fetch upstream once, resolve an immutable revision, and write a local lock.
No binaries, game files, credentials or saves are downloaded/uploaded.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
URL="https://github.com/gamerpuppy/sts_lightspeed.git"

def run(*args,cwd=None):
    return subprocess.check_output(args,cwd=cwd,text=True).strip()

def main():
    p=argparse.ArgumentParser();p.add_argument("--revision",help="Optional full 40-hex reviewed upstream commit")
    args=p.parse_args();dest=ROOT/"third_party"/"sts_lightspeed";lock=ROOT/"engine_lock.json"
    if args.revision and not re.fullmatch(r"[0-9a-fA-F]{40}",args.revision):
        raise SystemExit("--revision must be a full commit hash")
    if lock.exists():
        revision=json.loads(lock.read_text())["revision"]
        if args.revision and args.revision.lower()!=revision: raise SystemExit("Existing lock differs; review/update explicitly in a new checkout")
    else:
        revision=args.revision or run("git","ls-remote",URL,"refs/heads/master").split()[0]
    fresh_clone=not dest.exists()
    if fresh_clone:
        dest.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(["git","clone","--no-checkout",URL,str(dest)],check=True)
    if not fresh_clone and run("git","status","--porcelain",cwd=dest): raise SystemExit("Upstream checkout is dirty; refusing to overwrite local work")
    subprocess.run(["git","fetch","origin",revision],cwd=dest,check=True)
    subprocess.run(["git","checkout","--detach",revision],cwd=dest,check=True)
    # The upstream bundled pybind11 is deliberately not used. Build against the
    # maintained pip pybind11 installed for this interpreter.
    subprocess.run(["git","submodule","update","--init","json"],cwd=dest,check=True)
    license_file=dest/"LICENSE.md"
    if not license_file.exists(): raise SystemExit("Missing upstream license; manual review required")
    data={"url":URL,"revision":run("git","rev-parse","HEAD",cwd=dest),
          "json_submodule":run("git","rev-parse","HEAD",cwd=dest/"json"),
          "license_sha256":hashlib.sha256(license_file.read_bytes()).hexdigest(),
          "lock_origin":"explicit_revision" if args.revision else "resolved_master_on_target_machine"}
    lock.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(data,indent=2));print("Next: python scripts/build_native.py")

if __name__=="__main__":main()
