#!/usr/bin/env bash
# Negative SBOM/wheel substitution tests: prove that the independent verifier
# (scripts/verify_sbom_binding.py) fails closed under artifact substitution.
#
# Given a genuine (sbom, wheel) pair, this script first requires the positive
# control to pass, then requires the verifier to REJECT each of:
#
#   1. a substituted wheel (same filename, different bytes);
#   2. an SBOM whose root SHA-256 was replaced with another valid digest;
#   3. an SBOM whose root component name was substituted;
#   4. an SBOM whose root component version was substituted.
#
# Any tampered case that verifies successfully is a fatal defect in the
# release contract, and this script exits non-zero.
#
# usage: verify_sbom_negative.sh <sbom.cyclonedx.json> <wheel-or-dist-dir> [--python <interpreter>]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERIFIER="$ROOT/scripts/verify_sbom_binding.py"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <sbom.cyclonedx.json> <wheel-or-dist-dir> [--python <interpreter>]" >&2
  exit 64
fi

sbom="$1"
wheel_arg="$2"
shift 2
python_bin="python3"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      python_bin="${2:?--python requires a value}"
      shift 2
      ;;
    *)
      echo "usage: $0 <sbom.cyclonedx.json> <wheel-or-dist-dir> [--python <interpreter>]" >&2
      exit 64
      ;;
  esac
done

if [[ -d "$wheel_arg" ]]; then
  shopt -s nullglob
  wheels=("$wheel_arg"/*.whl)
  shopt -u nullglob
  if [[ ${#wheels[@]} -ne 1 ]]; then
    echo "expected exactly one wheel in $wheel_arg, found ${#wheels[@]}" >&2
    exit 65
  fi
  wheel="${wheels[0]}"
else
  wheel="$wheel_arg"
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "== positive control: genuine sbom + genuine wheel must verify =="
"$python_bin" "$VERIFIER" "$sbom" "$wheel"

expect_rejection() {
  local label="$1" tampered_sbom="$2" tampered_wheel="$3"
  if "$python_bin" "$VERIFIER" "$tampered_sbom" "$tampered_wheel" >"$workdir/out.log" 2>&1; then
    echo "FATAL: verifier ACCEPTED tampered case: $label" >&2
    cat "$workdir/out.log" >&2
    exit 1
  fi
  echo "rejected as required: $label"
}

# Case 1: substituted wheel — same filename, different content.
mkdir -p "$workdir/wheel"
cp "$wheel" "$workdir/wheel/$(basename "$wheel")"
printf 'substituted-content' >>"$workdir/wheel/$(basename "$wheel")"
expect_rejection "substituted wheel (content differs)" "$sbom" "$workdir/wheel/$(basename "$wheel")"

# Cases 2-4: substituted SBOM fields.
tamper_sbom() {
  local field="$1" out="$2"
  SBOM_IN="$sbom" SBOM_OUT="$out" TAMPER_FIELD="$field" "$python_bin" - <<'PY'
import hashlib
import json
import os

sbom = json.loads(open(os.environ["SBOM_IN"], encoding="utf-8").read())
component = sbom["metadata"]["component"]
field = os.environ["TAMPER_FIELD"]
if field == "hash":
    for entry in component["hashes"]:
        if entry["alg"] == "SHA-256":
            entry["content"] = hashlib.sha256(b"substituted artifact").hexdigest()
elif field == "name":
    component["name"] = "substituted-package"
elif field == "version":
    component["version"] = "0.0.0"
else:
    raise SystemExit(f"unknown tamper field: {field}")
open(os.environ["SBOM_OUT"], "w", encoding="utf-8").write(json.dumps(sbom))
PY
}

tamper_sbom hash "$workdir/sbom-hash.json"
expect_rejection "SBOM root SHA-256 substituted" "$workdir/sbom-hash.json" "$wheel"

tamper_sbom name "$workdir/sbom-name.json"
expect_rejection "SBOM root component name substituted" "$workdir/sbom-name.json" "$wheel"

tamper_sbom version "$workdir/sbom-version.json"
expect_rejection "SBOM root component version substituted" "$workdir/sbom-version.json" "$wheel"

echo "all negative substitution cases rejected; verifier fails closed"
