#!/usr/bin/env bash
# Install a pinned, digest-verified mcp-publisher before OIDC publication.
# Production usage: scripts/install_mcp_publisher.sh
# Test usage:       scripts/install_mcp_publisher.sh --archive <local-archive>
set -euo pipefail

VERSION="1.8.0"
DEST="."
archive_override=""

usage() {
  echo "usage: $0 [--archive <local-archive>]" >&2
}

if [[ $# -gt 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--archive" || -z "$2" ]]; then
    usage
    exit 64
  fi
  archive_override="$2"
fi

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
platform="${os}_${arch}"

# Digests are copied from the already-verified Semantic Scholar installer for
# the same MCP Registry v1.8.0 release assets. Updating VERSION requires an
# explicit reviewed update of these repository-controlled trust anchors.
case "$platform" in
  linux_amd64)  expected_sha256="1370446bbe74d562608e8005a6ccce02d146a661fbd78674e11cc70b9618d6cf" ;;
  linux_arm64)  expected_sha256="c978982c60e1b4903a976de090f04dc4fac4a320daa50704fcad2dbc93433d62" ;;
  darwin_amd64) expected_sha256="5350f756e8408d0e22802b7f384af941448358b503eb1e1772979a61b9b99fde" ;;
  darwin_arm64) expected_sha256="e74f8846c3b5d0428cfeae3f9f520bbf9031d18e68224108c3760d60b6aaf2e0" ;;
  *)
    echo "ERROR: no pinned mcp-publisher $VERSION digest for platform $platform" >&2
    exit 65
    ;;
esac

asset="mcp-publisher_${platform}.tar.gz"
url="https://github.com/modelcontextprotocol/registry/releases/download/v${VERSION}/${asset}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
archive="$work/$asset"

if [[ -n "$archive_override" ]]; then
  cp -- "$archive_override" "$archive"
else
  curl --fail --silent --show-error --location \
    --proto '=https' --tlsv1.2 \
    --output "$archive" "$url"
fi

if command -v sha256sum >/dev/null 2>&1; then
  actual_sha256="$(sha256sum "$archive" | cut -d' ' -f1)"
else
  actual_sha256="$(shasum -a 256 "$archive" | cut -d' ' -f1)"
fi

if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  echo "mcp-publisher SHA-256 mismatch" >&2
  echo "expected: $expected_sha256" >&2
  echo "actual:   $actual_sha256" >&2
  exit 66
fi

expected_members="LICENSE
README.md
mcp-publisher"
actual_members="$(tar tzf "$archive" | LC_ALL=C sort)"
if [[ "$actual_members" != "$(printf '%s' "$expected_members" | LC_ALL=C sort)" ]]; then
  echo "ERROR: unexpected archive members in $asset" >&2
  echo "--- expected ---" >&2
  printf '%s\n' "$expected_members" >&2
  echo "--- actual ---" >&2
  printf '%s\n' "$actual_members" >&2
  exit 67
fi

tar xzf "$archive" -C "$work" mcp-publisher
install -m 0755 "$work/mcp-publisher" "$DEST/mcp-publisher"

version_output="$("$DEST/mcp-publisher" --version 2>&1)"
case "$version_output" in
  *"mcp-publisher $VERSION"*) ;;
  *)
    echo "ERROR: expected mcp-publisher $VERSION" >&2
    printf '%s\n' "$version_output" >&2
    rm -f "$DEST/mcp-publisher"
    exit 68
    ;;
esac

printf 'installed and verified mcp-publisher %s (%s)\n' "$VERSION" "$platform"
