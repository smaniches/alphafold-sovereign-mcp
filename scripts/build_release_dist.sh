#!/usr/bin/env bash
# Build the release wheel + sdist with the hash-locked toolchain and build
# isolation disabled, then require that exactly one wheel and exactly one
# sdist were produced.
#
# --no-isolation makes the PEP 517 frontend import the build backend
# (hatchling) from the verified .release-tools closure instead of resolving
# a floating backend version at build time — that is what makes the built
# artifact a product of the locked toolchain.
#
# usage: build_release_dist.sh [--env-dir <dir>] [--outdir <dir>]
#   --env-dir  tooling venv from install_release_tooling.sh (default: .release-tools)
#   --outdir   output directory; must not already contain distributions
#              (default: dist)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$ROOT/.release-tools"
outdir="$ROOT/dist"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-dir)
      env_dir="${2:?--env-dir requires a value}"
      shift 2
      ;;
    --outdir)
      outdir="${2:?--outdir requires a value}"
      shift 2
      ;;
    *)
      echo "usage: $0 [--env-dir <dir>] [--outdir <dir>]" >&2
      exit 64
      ;;
  esac
done

venv_python="$env_dir/bin/python"
if [[ ! -x "$venv_python" ]]; then
  echo "release tooling venv missing at $env_dir; run scripts/install_release_tooling.sh first" >&2
  exit 65
fi

# "exactly one built wheel" is only decidable if nothing pre-existing can be
# confused with this build's output.
if [[ -d "$outdir" ]]; then
  stale="$(find "$outdir" -maxdepth 1 \( -name '*.whl' -o -name '*.tar.gz' \) -print -quit)"
  if [[ -n "$stale" ]]; then
    echo "output directory $outdir already contains distributions (e.g. $stale);" >&2
    echo "remove them so the built wheel can be identified unambiguously" >&2
    exit 66
  fi
fi

"$venv_python" -m build --no-isolation --sdist --wheel --outdir "$outdir" "$ROOT"

shopt -s nullglob
wheels=("$outdir"/*.whl)
sdists=("$outdir"/*.tar.gz)
shopt -u nullglob

if [[ ${#wheels[@]} -ne 1 ]]; then
  echo "expected exactly one built wheel in $outdir, found ${#wheels[@]}" >&2
  exit 67
fi
if [[ ${#sdists[@]} -ne 1 ]]; then
  echo "expected exactly one built sdist in $outdir, found ${#sdists[@]}" >&2
  exit 68
fi

echo "built wheel: ${wheels[0]}"
echo "built sdist: ${sdists[0]}"
