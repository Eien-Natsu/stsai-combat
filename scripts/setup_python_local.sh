#!/usr/bin/env bash
# Provision a project-local CPython that ships development headers.
#
# build_native.py needs Python.h, which minimal images often omit because
# python3-dev is not installed. Rather than modifying the system, install an
# official python-build-standalone interpreter under .python/ (via uv) and let
# setup_linux.sh build the venv from it. Prints the interpreter path on stdout.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="${PYTHON_VERSION:-3.12}"
UV="${UV:-uv}"

if ! command -v "$UV" >/dev/null 2>&1; then
  echo "uv not found; bootstrapping it in a temporary venv" >&2
  bootstrap="$(mktemp -d)"
  trap 'rm -rf "$bootstrap"' EXIT
  python3 -m venv "$bootstrap"
  "$bootstrap/bin/pip" install --quiet uv
  UV="$bootstrap/bin/uv"
fi

export UV_PYTHON_INSTALL_DIR="$PWD/.python"
"$UV" python install "$VERSION" >&2
# uv maintains a stable "cpython-<version>-<platform>" alias next to the
# versioned directory; resolving through it avoids hardcoding a patch release.
interpreter="$(ls -d "$PWD"/.python/cpython-"$VERSION"-*/bin/python"$VERSION" 2>/dev/null | sort -V | tail -1)"
[[ -n "$interpreter" ]] || { echo "Could not locate the provisioned interpreter under .python/" >&2; exit 1; }
"$interpreter" -c 'import pathlib,sysconfig; assert (pathlib.Path(sysconfig.get_paths()["include"])/"Python.h").is_file(), "provisioned interpreter has no Python.h"' \
  || { echo "Provisioned interpreter still lacks development headers" >&2; exit 1; }
echo "$interpreter"
