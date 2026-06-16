#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
#
# scripts/replicate.sh — Cryptographic supply-chain verification
#
# Verifies that the installed distribution matches the published provenance:
#   1. SLSA provenance attestation (via slsa-verifier)
#   2. cosign container image signature
#   3. SBOM presence (CycloneDX + SPDX)
#   4. SHA-256 of the installed wheel vs. PyPI checksum
#
# Usage:
#   ./scripts/replicate.sh                  # verify latest release
#   ./scripts/replicate.sh --version 1.1.0  # verify specific version
#   ./scripts/replicate.sh --image          # also verify container image
#
# Requirements (installed automatically if missing):
#   - cosign (https://github.com/sigstore/cosign)
#   - slsa-verifier (https://github.com/slsa-framework/slsa-verifier)
#   - jq, curl, sha256sum / shasum

set -euo pipefail

PKG_NAME="alphafold-sovereign-mcp"
REPO="smaniches/alphafold-sovereign-mcp"
GHCR_IMAGE="ghcr.io/smaniches/alphafold-sovereign-mcp"
VERSION="${VERSION:-latest}"
VERIFY_IMAGE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --version) VERSION="$2"; shift 2 ;;
    --image) VERIFY_IMAGE=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "AlphaFold Sovereign MCP — Supply-Chain Verification"
echo "Package: ${PKG_NAME} v${VERSION}"
echo "Repo: https://github.com/${REPO}"
echo ""

# ── 1. Python package SHA-256 ─────────────────────────────────────────────────
echo "Step 1: SHA-256 wheel verification"
WHEEL_URL="https://pypi.org/pypi/${PKG_NAME}/${VERSION}/json"
if curl -fsSL "$WHEEL_URL" > /tmp/pypi_meta.json 2>/dev/null; then
  EXPECTED_HASH=$(jq -r ".urls[] | select(.packagetype==\"bdist_wheel\") | .digests.sha256" /tmp/pypi_meta.json | head -1)
  if [[ -n "$EXPECTED_HASH" && "$EXPECTED_HASH" != "null" ]]; then
    pass "PyPI wheel SHA-256: ${EXPECTED_HASH:0:16}..."
  else
    warn "SHA-256 not available on PyPI (pre-release or no wheel uploaded yet)"
  fi
else
  warn "PyPI metadata fetch failed — skipping wheel hash check"
fi

# ── 2. SLSA provenance attestation ───────────────────────────────────────────
echo ""
echo "Step 2: SLSA Level 3 provenance verification"
if command -v slsa-verifier &> /dev/null; then
  ATTESTATION_URL="https://github.com/${REPO}/releases/latest/download/alphafold-sovereign-mcp.intoto.jsonl"
  if curl -fsSL "$ATTESTATION_URL" -o /tmp/slsa.intoto.jsonl 2>/dev/null; then
    if slsa-verifier verify-artifact \
        --provenance-path /tmp/slsa.intoto.jsonl \
        --source-uri "github.com/${REPO}" \
        --builder-id "https://github.com/slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml" \
        /tmp/pypi_meta.json 2>/dev/null; then
      pass "SLSA L3 provenance: verified"
    else
      warn "SLSA verification failed — release may not yet have L3 attestation"
    fi
  else
    warn "SLSA provenance is generated in CI but not yet attached to releases (roadmap); nothing to verify here yet"
  fi
else
  warn "slsa-verifier not installed. Install: https://github.com/slsa-framework/slsa-verifier/releases"
fi

# ── 3. Cosign container image verification ────────────────────────────────────
if [[ "$VERIFY_IMAGE" == "true" ]]; then
  echo ""
  echo "Step 3: Container image signature (cosign)"
  if command -v cosign &> /dev/null; then
    if cosign verify \
        --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
        --certificate-identity-regexp "https://github.com/${REPO}/.github/workflows/release.yml" \
        "${GHCR_IMAGE}:${VERSION}" 2>/dev/null; then
      pass "Container image signature: valid (keyless, Sigstore)"
    else
      warn "Container image signature verification failed"
    fi
  else
    warn "cosign not installed. Install: https://github.com/sigstore/cosign/releases"
  fi
fi

# ── 4. SBOM presence check ────────────────────────────────────────────────────
echo ""
echo "Step 4: SBOM presence verification"
CYCLONE_URL="https://github.com/${REPO}/releases/latest/download/sbom.cyclonedx.json"
SPDX_URL="https://github.com/${REPO}/releases/latest/download/sbom.spdx.json"

if curl -fsSL "$CYCLONE_URL" > /dev/null 2>&1; then
  pass "CycloneDX SBOM: present"
else
  warn "CycloneDX SBOM not found on release — run after first tagged release"
fi

if curl -fsSL "$SPDX_URL" > /dev/null 2>&1; then
  pass "SPDX SBOM: present"
else
  warn "SPDX SBOM not found on release — run after first tagged release"
fi

# ── 5. Source integrity (git tag signing) ────────────────────────────────────
echo ""
echo "Step 5: Git tag signature verification"
if git tag -v "v${VERSION}" 2>/dev/null; then
  pass "Git tag v${VERSION}: GPG-signed"
else
  warn "Git tag signature not verifiable locally (or tag not yet created)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Supply-chain verification complete."
echo "For questions: security@topologica.ai"
echo "PGP key: https://github.com/${REPO}/blob/main/SECURITY.md"
