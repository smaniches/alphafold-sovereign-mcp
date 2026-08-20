#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
#
# scripts/replicate.sh — cryptographic verifier for a published release
#
# Verifies the public release surface from independently downloaded artifacts:
#   1. resolves the requested PyPI release (or the current release for `latest`)
#      and its actual GitHub Release tag;
#   2. downloads the wheel and sdist and recomputes their PyPI SHA-256 digests;
#   3. downloads each GitHub Release Sigstore bundle and verifies the exact
#      corresponding artifact against the immutable release-tag workflow identity;
#   4. downloads the CycloneDX SBOM, authenticates it when the release supports
#      signed SBOM assets, and independently verifies its root against the exact
#      downloaded wheel Name/Version/SHA-256;
#   5. authenticates the SPDX SBOM when supported and validates its required
#      SPDX document structure;
#   6. verifies SLSA provenance against the exact wheel when a provenance asset
#      is attached to the release (release attachment remains a separate roadmap item);
#   7. verifies the local git tag signature when the tag is present locally.
#
# Releases before 1.4.7 predate signed SBOM release assets. For those historical
# releases the verifier reports the limitation explicitly and checks SBOM-to-wheel
# binding/structure without claiming SBOM publisher authentication. Releases from
# 1.4.7 onward fail closed if either SBOM signature bundle is absent or invalid.
#
# Usage:
#   ./scripts/replicate.sh                  # verify latest PyPI release
#   ./scripts/replicate.sh --version 1.4.6  # verify a specific release
#   ./scripts/replicate.sh --image          # also verify a published image
#
# Required: curl, jq, python3, cosign, and sha256sum (or shasum).
# Optional: slsa-verifier for a release that carries the SLSA provenance asset.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PKG_NAME="alphafold-sovereign-mcp"
REPO="smaniches/alphafold-sovereign-mcp"
GHCR_IMAGE="ghcr.io/smaniches/alphafold-sovereign-mcp"
SIGNED_SBOM_FIRST_RELEASE="1.4.7"
VERSION="${VERSION:-latest}"
VERIFY_IMAGE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || { echo "--version requires a value" >&2; exit 64; }
      VERSION="$2"
      shift 2
      ;;
    --image)
      VERIFY_IMAGE=true
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 64
      ;;
  esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1" >&2; exit 1; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    fail "required SHA-256 utility not found (sha256sum or shasum)"
  fi
}

# Return success only for releases whose x.y.z core predates the first release
# that signs SBOM assets. Parse failures return nonzero and therefore fail closed.
legacy_unsigned_sbom_allowed() {
  python3 - "$1" "$SIGNED_SBOM_FIRST_RELEASE" <<'PY'
import re
import sys


def core(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        raise ValueError(value)
    return tuple(int(part) for part in match.groups())


try:
    current = core(sys.argv[1])
    floor = core(sys.argv[2])
except ValueError:
    raise SystemExit(2)
raise SystemExit(0 if current < floor else 1)
PY
}

for cmd in curl jq python3 cosign; do
  require_cmd "$cmd"
done

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

# Resolve `latest` through the project endpoint; PyPI has no /latest/json route.
if [[ "$VERSION" == "latest" ]]; then
  PROJECT_META="$TMP_ROOT/project.json"
  curl -fsSL "https://pypi.org/pypi/${PKG_NAME}/json" -o "$PROJECT_META" \
    || fail "could not fetch current PyPI project metadata"
  VERSION="$(jq -er '.info.version | select(type == "string" and length > 0)' "$PROJECT_META")" \
    || fail "PyPI project metadata did not contain a current version"
else
  VERSION="${VERSION#v}"
fi

# Fetch release-specific PyPI metadata so every downloaded distribution belongs
# to the requested immutable release, not merely the current project state.
RELEASE_META="$TMP_ROOT/pypi-release.json"
curl -fsSL "https://pypi.org/pypi/${PKG_NAME}/${VERSION}/json" -o "$RELEASE_META" \
  || fail "PyPI release ${VERSION} was not found"

# Resolve the actual GitHub Release tag instead of assuming PyPI's normalized
# version string is byte-identical to the tag. PEP 440 normalizes e.g.
# 1.1.0-rc1 to 1.1.0rc1, while this repository's release tags retain the hyphen.
GH_RELEASE_META="$TMP_ROOT/github-release.json"
resolve_github_release() {
  local candidate="v${VERSION}"
  if curl -fsSL "https://api.github.com/repos/${REPO}/releases/tags/${candidate}" \
      -o "$GH_RELEASE_META" 2>/dev/null; then
    return 0
  fi

  if [[ "$VERSION" =~ ^([0-9]+\.[0-9]+\.[0-9]+)(a|b|rc)([0-9]+)$ ]]; then
    candidate="v${BASH_REMATCH[1]}-${BASH_REMATCH[2]}${BASH_REMATCH[3]}"
    if curl -fsSL "https://api.github.com/repos/${REPO}/releases/tags/${candidate}" \
        -o "$GH_RELEASE_META" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}
resolve_github_release || fail "no GitHub Release corresponds to PyPI version ${VERSION}"
TAG="$(jq -er '.tag_name | select(type == "string" and length > 0)' "$GH_RELEASE_META")" \
  || fail "GitHub Release metadata did not contain a tag"

release_asset_url() {
  jq -er --arg name "$1" '
    [.assets[] | select(.name == $name) | .browser_download_url]
    | select(length == 1)
    | .[0]
  ' "$GH_RELEASE_META"
}

printf 'AlphaFold Sovereign MCP — Supply-Chain Verification\n'
printf 'Package: %s v%s\n' "$PKG_NAME" "$VERSION"
printf 'GitHub release: %s\n' "$TAG"
printf 'Repository: https://github.com/%s\n\n' "$REPO"

# Bash 3.2-compatible population; stock macOS Bash does not provide `mapfile`.
DIST_ROWS=()
while IFS= read -r row; do
  [[ -n "$row" ]] && DIST_ROWS+=("$row")
done < <(
  jq -r '.urls[]
    | select(.packagetype == "bdist_wheel" or .packagetype == "sdist")
    | [.filename, .url, .digests.sha256]
    | @tsv' "$RELEASE_META"
)
if (( ${#DIST_ROWS[@]} != 2 )); then
  fail "expected exactly one wheel and one sdist on PyPI; found ${#DIST_ROWS[@]} artifacts"
fi

WHEEL_PATH=""
echo "Step 1: PyPI artifact bytes and SHA-256"
for row in "${DIST_ROWS[@]}"; do
  IFS=$'\t' read -r filename url expected_hash <<< "$row"
  [[ -n "$filename" && -n "$url" && -n "$expected_hash" ]] \
    || fail "PyPI returned incomplete artifact metadata"

  artifact="$TMP_ROOT/$filename"
  curl -fsSL "$url" -o "$artifact" || fail "failed to download PyPI artifact $filename"
  actual_hash="$(sha256_file "$artifact")"
  [[ "$actual_hash" == "$expected_hash" ]] \
    || fail "SHA-256 mismatch for $filename: expected $expected_hash, got $actual_hash"
  pass "$filename SHA-256 matches PyPI (${actual_hash:0:16}...)"

  if [[ "$filename" == *.whl ]]; then
    [[ -z "$WHEEL_PATH" ]] || fail "multiple wheel files found"
    WHEEL_PATH="$artifact"
  fi
done
[[ -n "$WHEEL_PATH" ]] || fail "release contains no wheel"

TAG_IDENTITY="https://github.com/${REPO}/.github/workflows/release.yml@refs/tags/${TAG}"

echo ""
echo "Step 2: Sigstore release-bundle verification"
for row in "${DIST_ROWS[@]}"; do
  IFS=$'\t' read -r filename _ _ <<< "$row"
  artifact="$TMP_ROOT/$filename"
  bundle="$TMP_ROOT/${filename}.sigstore"
  bundle_url="$(release_asset_url "${filename}.sigstore")" \
    || fail "Sigstore bundle missing from GitHub Release: ${filename}.sigstore"
  curl -fsSL "$bundle_url" -o "$bundle" \
    || fail "could not download Sigstore bundle: ${filename}.sigstore"

  cosign verify-blob \
    --bundle "$bundle" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    --certificate-identity "$TAG_IDENTITY" \
    "$artifact" >/dev/null 2>&1 \
    || fail "Sigstore verification failed for $filename"
  pass "$filename Sigstore bundle verified against immutable release-tag workflow"
done

LEGACY_SBOM_AUTH=false

echo ""
echo "Step 3: CycloneDX SBOM authenticity and wheel binding"
CYCLONE="$TMP_ROOT/sbom.cyclonedx.json"
CYCLONE_URL="$(release_asset_url "sbom.cyclonedx.json")" \
  || fail "CycloneDX SBOM missing from GitHub Release ${TAG}"
curl -fsSL "$CYCLONE_URL" -o "$CYCLONE" \
  || fail "could not download CycloneDX SBOM from GitHub Release ${TAG}"

if CYCLONE_BUNDLE_URL="$(release_asset_url "sbom.cyclonedx.json.sigstore" 2>/dev/null)"; then
  CYCLONE_BUNDLE="$TMP_ROOT/sbom.cyclonedx.json.sigstore"
  curl -fsSL "$CYCLONE_BUNDLE_URL" -o "$CYCLONE_BUNDLE" \
    || fail "could not download CycloneDX Sigstore bundle"
  cosign verify-blob \
    --bundle "$CYCLONE_BUNDLE" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    --certificate-identity "$TAG_IDENTITY" \
    "$CYCLONE" >/dev/null 2>&1 \
    || fail "CycloneDX SBOM Sigstore verification failed"
  pass "CycloneDX SBOM authenticated to immutable release-tag workflow"
elif legacy_unsigned_sbom_allowed "$VERSION"; then
  LEGACY_SBOM_AUTH=true
  warn "${TAG} predates signed SBOM assets; CycloneDX publisher authenticity is not established"
else
  fail "CycloneDX Sigstore bundle missing from release ${TAG}"
fi

python3 "$REPO_ROOT/scripts/verify_sbom_binding.py" "$CYCLONE" "$WHEEL_PATH" >/dev/null \
  || fail "CycloneDX SBOM is not bound to the downloaded wheel"
pass "CycloneDX root identity and SHA-256 are bound to the exact wheel"

echo ""
echo "Step 4: SPDX release asset authenticity and structure"
SPDX="$TMP_ROOT/sbom.spdx.json"
SPDX_URL="$(release_asset_url "sbom.spdx.json")" \
  || fail "SPDX SBOM missing from GitHub Release ${TAG}"
curl -fsSL "$SPDX_URL" -o "$SPDX" \
  || fail "could not download SPDX SBOM from GitHub Release ${TAG}"

if SPDX_BUNDLE_URL="$(release_asset_url "sbom.spdx.json.sigstore" 2>/dev/null)"; then
  SPDX_BUNDLE="$TMP_ROOT/sbom.spdx.json.sigstore"
  curl -fsSL "$SPDX_BUNDLE_URL" -o "$SPDX_BUNDLE" \
    || fail "could not download SPDX Sigstore bundle"
  cosign verify-blob \
    --bundle "$SPDX_BUNDLE" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    --certificate-identity "$TAG_IDENTITY" \
    "$SPDX" >/dev/null 2>&1 \
    || fail "SPDX SBOM Sigstore verification failed"
  pass "SPDX SBOM authenticated to immutable release-tag workflow"
elif legacy_unsigned_sbom_allowed "$VERSION"; then
  LEGACY_SBOM_AUTH=true
  warn "${TAG} predates signed SBOM assets; SPDX publisher authenticity is not established"
else
  fail "SPDX Sigstore bundle missing from release ${TAG}"
fi

jq -e '
  (.spdxVersion | type == "string" and test("^SPDX-2\\.[0-9]+$")) and
  (.SPDXID == "SPDXRef-DOCUMENT") and
  (.dataLicense == "CC0-1.0") and
  (.name | type == "string" and length > 0) and
  (.documentNamespace | type == "string" and length > 0) and
  (.creationInfo | type == "object") and
  (.creationInfo.created | type == "string" and length > 0) and
  (.creationInfo.creators | type == "array" and length > 0) and
  (.packages | type == "array" and length > 0)
' "$SPDX" >/dev/null || fail "SPDX release asset is missing required SPDX document structure"
pass "SPDX SBOM has the required SPDX document structure"

echo ""
echo "Step 5: SLSA provenance (when attached to the GitHub Release)"
PROVENANCE="$TMP_ROOT/alphafold-sovereign-mcp.intoto.jsonl"
if PROVENANCE_URL="$(release_asset_url "alphafold-sovereign-mcp.intoto.jsonl" 2>/dev/null)"; then
  curl -fsSL "$PROVENANCE_URL" -o "$PROVENANCE" \
    || fail "could not download attached SLSA provenance"
  if command -v slsa-verifier >/dev/null 2>&1; then
    if slsa-verifier verify-artifact \
        --provenance-path "$PROVENANCE" \
        --source-uri "github.com/${REPO}" \
        --builder-id "https://github.com/slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml" \
        "$WHEEL_PATH" >/dev/null 2>&1; then
      pass "SLSA provenance verified against the exact wheel"
    else
      fail "SLSA provenance asset exists but verification failed"
    fi
  else
    warn "SLSA provenance is attached, but slsa-verifier is not installed"
  fi
else
  warn "SLSA provenance is generated during release but is not yet attached as a release asset"
fi

if [[ "$VERIFY_IMAGE" == "true" ]]; then
  echo ""
  echo "Step 6: Container image signature"
  image="${GHCR_IMAGE}:${VERSION}"
  if cosign verify \
      --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
      --certificate-identity "${TAG_IDENTITY}" \
      "$image" >/dev/null 2>&1; then
    pass "Container image signature verified: $image"
  else
    fail "container image signature verification failed: $image"
  fi
fi

echo ""
echo "Step 7: Local git tag signature (when the tag is present)"
if git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/${TAG}" >/dev/null 2>&1; then
  if git -C "$REPO_ROOT" tag -v "$TAG" >/dev/null 2>&1; then
    pass "Git tag ${TAG} is locally GPG-verifiable"
  else
    warn "Git tag ${TAG} exists locally but its signature is not verifiable with the local keyring"
  fi
else
  warn "Git tag ${TAG} is not present in this local clone"
fi

echo ""
if [[ "$LEGACY_SBOM_AUTH" == "true" ]]; then
  warn "Supply-chain verification complete with documented legacy SBOM-authentication boundary for ${PKG_NAME} ${VERSION}."
else
  pass "Supply-chain verification complete for ${PKG_NAME} ${VERSION}."
fi
