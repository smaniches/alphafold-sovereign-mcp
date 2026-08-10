#!/usr/bin/env bash
# Install the exact hash-locked release/build/SBOM tool closure into a
# dedicated virtual environment, then verify the installed tool versions
# against the pins declared in requirements/release-tools.in.
#
# Python 3.12 is the mandatory release-runner interpreter (release.yml
# installs 3.12 for the build/SBOM path), so this script refuses any other
# minor version. The lock pins package versions and artifact hashes, never
# an interpreter patch release: any Python 3.12.x satisfies it.
#
# usage: install_release_tooling.sh [--python <interpreter>] [--env-dir <dir>]
#   --python   interpreter to build the venv from (default: python3.12)
#   --env-dir  venv location (default: .release-tools in the repo root)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$ROOT/requirements/release-tools.txt"
INTENT="$ROOT/requirements/release-tools.in"

python_bin="python3.12"
env_dir="$ROOT/.release-tools"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      python_bin="${2:?--python requires a value}"
      shift 2
      ;;
    --env-dir)
      env_dir="${2:?--env-dir requires a value}"
      shift 2
      ;;
    *)
      echo "usage: $0 [--python <interpreter>] [--env-dir <dir>]" >&2
      exit 64
      ;;
  esac
done

if ! command -v "$python_bin" >/dev/null 2>&1 && [[ ! -x "$python_bin" ]]; then
  echo "python interpreter not found: $python_bin" >&2
  exit 65
fi

minor="$("$python_bin" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
full="$("$python_bin" -c 'import platform; print(platform.python_version())')"
if [[ "$minor" != "3.12" ]]; then
  echo "release tooling requires the Python 3.12 release interpreter; got $full" >&2
  exit 66
fi
echo "release tooling interpreter: Python $full ($python_bin)"

if [[ ! -f "$LOCK" || ! -f "$INTENT" ]]; then
  echo "missing release tooling lock ($LOCK) or intent file ($INTENT)" >&2
  exit 67
fi

"$python_bin" -m venv --clear "$env_dir"
venv_python="$env_dir/bin/python"

# --require-hashes makes pip refuse any artifact whose SHA-256 is not in the
# lock, and refuse any dependency the lock does not list at all;
# --only-binary=:all: refuses to fall back to building any sdist, matching
# the wheel-only (--no-build) resolution the lock was compiled with. This is
# the fail-closed install of the exact release-tool closure.
"$venv_python" -m pip install --quiet --no-cache-dir --require-hashes \
  --only-binary=:all: -r "$LOCK"

# Verify the intended tool versions: every `name==version` pin in the intent
# file must match the version actually importable from the fresh venv.
"$venv_python" - "$INTENT" <<'PY'
import importlib.metadata
import re
import sys

intent_path = sys.argv[1]
pins: list[tuple[str, str]] = []
with open(intent_path, encoding="utf-8") as fh:
    for line in fh:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+_-]+)", line)
        if match is None:
            sys.exit(f"intent file line is not an exact pin: {line!r}")
        pins.append((match.group(1), match.group(2)))

if not pins:
    sys.exit("intent file declares no pins; refusing to certify an empty toolchain")

failures = []
for name, wanted in pins:
    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        failures.append(f"{name}: pinned {wanted} but not installed")
        continue
    if installed != wanted:
        failures.append(f"{name}: pinned {wanted} but installed {installed}")
    else:
        print(f"verified {name}=={installed}")

if failures:
    print("release tooling version verification FAILED:", file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    sys.exit(1)
PY

echo "release tooling installed and verified in $env_dir"
