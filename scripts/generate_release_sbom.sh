#!/usr/bin/env bash
# Generate the release CycloneDX SBOM from the exact built wheel and its real
# runtime environment, then bind SHA-256(wheel) into the SBOM root component.
#
#   1. identify exactly one wheel in the dist directory;
#   2. install that wheel (with its runtime dependencies) into a dedicated
#      Python 3.12 environment, so the SBOM documents the dependency tree the
#      wheel actually resolves;
#   3. run the hash-locked cyclonedx-py against that environment, seeding the
#      root component from pyproject.toml (PEP 621) with reproducible output;
#   4. bind the wheel digest into the root component via
#      scripts/bind_sbom_wheel.py, which fails closed if the SBOM root
#      identity does not match the wheel's METADATA.
#
# Independent verification is deliberately NOT done here — that is
# scripts/verify_sbom_binding.py, a separate implementation.
#
# usage: generate_release_sbom.sh [--python <interpreter>] [--tools-env <dir>]
#                                 [--sbom-env <dir>] [--dist <dir>] [--output <file>]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="python3.12"
tools_env="$ROOT/.release-tools"
sbom_env="$ROOT/.sbom-env"
dist_dir="$ROOT/dist"
output="$ROOT/sbom.cyclonedx.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      python_bin="${2:?--python requires a value}"
      shift 2
      ;;
    --tools-env)
      tools_env="${2:?--tools-env requires a value}"
      shift 2
      ;;
    --sbom-env)
      sbom_env="${2:?--sbom-env requires a value}"
      shift 2
      ;;
    --dist)
      dist_dir="${2:?--dist requires a value}"
      shift 2
      ;;
    --output)
      output="${2:?--output requires a value}"
      shift 2
      ;;
    *)
      echo "usage: $0 [--python <interpreter>] [--tools-env <dir>] [--sbom-env <dir>] [--dist <dir>] [--output <file>]" >&2
      exit 64
      ;;
  esac
done

cyclonedx="$tools_env/bin/cyclonedx-py"
if [[ ! -x "$cyclonedx" ]]; then
  echo "cyclonedx-py missing from $tools_env; run scripts/install_release_tooling.sh first" >&2
  exit 65
fi

minor="$("$python_bin" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [[ "$minor" != "3.12" ]]; then
  echo "SBOM environment requires the Python 3.12 release interpreter; got $minor" >&2
  exit 66
fi

shopt -s nullglob
wheels=("$dist_dir"/*.whl)
shopt -u nullglob
if [[ ${#wheels[@]} -ne 1 ]]; then
  echo "expected exactly one wheel in $dist_dir, found ${#wheels[@]}" >&2
  exit 67
fi
wheel="${wheels[0]}"
echo "SBOM subject wheel: $wheel"

# The SBOM environment contains the exact wheel and its resolved runtime
# dependencies — nothing else. The SBOM tool itself runs from the separate
# hash-locked tooling venv so its own dependencies never leak into the SBOM.
"$python_bin" -m venv --clear "$sbom_env"
"$sbom_env/bin/python" -m pip install --quiet --no-cache-dir "$wheel"

"$cyclonedx" environment "$sbom_env/bin/python" \
  --pyproject "$ROOT/pyproject.toml" \
  --mc-type library \
  --output-reproducible \
  -o "$output"

"$tools_env/bin/python" "$ROOT/scripts/bind_sbom_wheel.py" "$output" "$wheel"
