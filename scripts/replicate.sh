#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
#
# scripts/replicate.sh — cryptographic verifier for a published release
#
# Verifies the public release surface from independently downloaded artifacts:
#   1. resolves the requested PyPI release (or the current release for `latest`);
#   2. downloads the wheel and sdist and recomputes their PyPI SHA-256 digests;
#   3. downloads each GitHub Release Sigstore bundle and verifies the exact
#      corresponding artifact with cosign against this repository's release
#      workflow identity and GitHub Actions OIDC issuer;
#   4. downloads the CycloneDX SBOM and independently verifies that its root
#      component is bound to the exact downloaded wheel Name/Version/SHA-256;
#   5. validates that the SPDX release asset is parseable SPDX JSON;
#   6. verifies SLSA provenance against the exact wheel when a provenance asset
#      is attached to the release (release attachment remains a separate
#      roadmap item); and
#   7. verifies the local git tag signature when the tag is present locally.
#
# Usage:
#   ./scripts/replicate.sh                  # verify latest PyPI release
#   ./scripts/replicate.sh --version 1.4.6  # verify a specific release
#   ./scripts/replicate.sh --image          # also verify a published image
#
# Required: curl, jq, python3, cosign, and sha256sum (or shasum).
# Optional: slsa-verifier for a release that carries the SLSA provenance asset.

set -euo pipefail

PKG_NAME="alphafold-sovereign-mcp"
REPO="smaniches/alphafold-sovereign-mcp"
GHCR_IMAGE="ghcr.io/smaniches/alphafold-sovereign-mcp"
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
TAG="v${VERSION}"

printf 'AlphaFold Sovereign MCP — Supply-Chain Verification\n'
printf 'Package: %s v%s\n' "$PKG_NAME" "$VERSION"
printf 'Repository: https://github.com/%s\n\n' "$REPO"

# Fetch release-specific metadata so every downloaded artifact belongs to the
# requested immutable PyPI release, not merely the current project state.
RELEASE_META="$TMP_ROOT/pypi-release.json"
curl -fsSL "https://pypi.org/pypi/${PKG_NAME}/${VERSION}/json" -o "$RELEASE_META" \
  || fail "PyPI release ${VERSION} was not found"

mapfile -t DIST_ROWS < <(
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

echo ""
echo "Step 2: Sigstore release-bundle verification"
for row in "${DIST_ROWS[@]}"; do
  IFS=$'\t' read -r filename _ _ <<< "$row"
  artifact="$TMP_ROOT/$filename"
  bundle="$TMP_ROOT/${filename}.sigstore"
  bundle_url="https://github.com/${REPO}/releases/download/${TAG}/${filename}.sigstore"
  curl -fsSL "$bundle_url" -o "$bundle" \
    || fail "Sigstore bundle missing from GitHub Release: ${filename}.sigstore"

  tag_identity="https://github.com/${REPO}/.github/workflows/release.yml@refs/tags/${TAG}"
  main_identity="https://github.com/${REPO}/.github/workflows/release.yml@refs/heads/main"
  if cosign verify-blob \
      --bundle "$bundle" \
      --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
      --certificate-identity "$tag_identity" \
      "$artifact" >/dev/null 2>&1; then
    pass "$filename Sigstore bundle verified against tag-triggered release workflow"
  elif cosign verify-blob \
      --bundle "$bundle" \
      --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
      --certificate-identity "$main_identity" \
      "$artifact" >/dev/null 2>&1; then
    # workflow_dispatch releases run the same immutable-tag resolution path,
    # but the Fulcio workflow identity is the branch from which dispatch ran.
    pass "$filename Sigstore bundle verified against main release workflow"
  else
    fail "Sigstore verification failed for $filename"
  fi
done

echo ""
echo "Step 3: CycloneDX SBOM binding"
CYCLONE="$TMP_ROOT/sbom.cyclonedx.json"
curl -fsSL \
  "https://github.com/${REPO}/releases/download/${TAG}/sbom.cyclonedx.json" \
  -o "$CYCLONE" || fail "CycloneDX SBOM missing from GitHub Release ${TAG}"
python3 scripts/verify_sbom_binding.py "$CYCLONE" "$WHEEL_PATH" >/dev/null \
  || fail "CycloneDX SBOM is not bound to the downloaded wheel"
pass "CycloneDX root identity and SHA-256 are bound to the exact wheel"

echo ""
echo "Step 4: SPDX release asset"
SPDX="$TMP_ROOT/sbom.spdx.json"
curl -fsSL \
  "https://github.com/${REPO}/releases/download/${TAG}/sbom.spdx.json" \
  -o "$SPDX" || fail "SPDX SBOM missing from GitHub Release ${TAG}"
jq -e '.spdxVersion | strings | startswith("SPDX-")' "$SPDX" >/dev/null \
  || fail "SPDX release asset is not valid SPDX JSON"
pass "SPDX SBOM is present and parseable"

echo ""
echo "Step 5: SLSA provenance (when attached to the GitHub Release)"
PROVENANCE="$TMP_ROOT/alphafold-sovereign-mcp.intoto.jsonl"
PROVENANCE_URL="https://github.com/${REPO}/releases/download/${TAG}/alphafold-sovereign-mcp.intoto.jsonl"
if curl -fsSL "$PROVENANCE_URL" -o "$PROVENANCE" 2>/dev/null; then
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
      --certificate-identity-regexp "^https://github.com/${REPO}/.github/workflows/release.yml@refs/(tags/${TAG}|heads/main)$" \
      "$image" >/dev/null 2>&1; then
    pass "Container image signature verified: $image"
  else
    fail "container image signature verification failed: $image"
  fi
fi

echo ""
echo "Step 7: Local git tag signature (when the tag is present)"
if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null 2>&1; then
  if git tag -v "$TAG" >/dev/null 2>&1; then
    pass "Git tag ${TAG} is locally GPG-verifiable"
  else
    warn "Git tag ${TAG} exists locally but its signature is not verifiable with the local keyring"
  fi
else
  warn "Git tag ${TAG} is not present in this local clone"
fi

echo ""
echo "Supply-chain verification complete for ${PKG_NAME} ${VERSION}."
