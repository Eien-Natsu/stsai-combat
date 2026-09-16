#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument("--jobs",type=int,default=min(4,os.cpu_count() or 1));p.add_argument("--sanitize",action="store_true")
    args=p.parse_args()
    if args.jobs<1: raise SystemExit("jobs must be positive")
    lock=ROOT/"engine_lock.json"
    if not lock.exists(): raise SystemExit("Missing engine_lock.json; run fetch_engine.py first")
    revision=json.loads(lock.read_text())["revision"]
    upstream=ROOT/"third_party"/"sts_lightspeed"
    actual=subprocess.check_output(["git","rev-parse","HEAD"],cwd=upstream,text=True).strip()
    if actual!=revision: raise SystemExit("Upstream differs from lock")
    if subprocess.check_output(["git","status","--porcelain"],cwd=upstream,text=True).strip():
        raise SystemExit("Upstream has unrecorded changes. Commit patches and update provenance before building")
    cmake_dir=subprocess.check_output([sys.executable,"-m","pybind11","--cmakedir"],text=True).strip()
    build=ROOT/"build"/("native_ubsan" if args.sanitize else "native")
    cmd=["cmake","-S",str(ROOT/"native"),"-B",str(build),"-DCMAKE_BUILD_TYPE=Release",
         f"-DSTS_ENGINE_DIR={upstream}",f"-DSTSAI_ENGINE_REVISION={revision}",
         f"-DPython_EXECUTABLE={sys.executable}",f"-Dpybind11_DIR={cmake_dir}",
         f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={ROOT/'src'/'stsai'}",
         f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE={ROOT/'src'/'stsai'}"]
    if args.sanitize:cmd.append("-DSTSAI_SANITIZE=ON")
    subprocess.run(cmd,check=True)
    subprocess.run(["cmake","--build",str(build),"--config","Release","--parallel",str(args.jobs)],check=True)
    subprocess.run([sys.executable,"-c","import stsai._lightspeed as m; print(m.build_info())"],cwd=ROOT,check=True)
    subprocess.run([sys.executable,"-m","pytest","-q","tests/test_native.py"],cwd=ROOT,check=True)

if __name__=="__main__":main()
