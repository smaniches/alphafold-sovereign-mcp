#!/usr/bin/env bash
# Install one pinned, digest-verified mcp-publisher release.
# Usage: scripts/install-mcp-publisher.sh [destination-directory]
set -euo pipefail

VERSION=1.8.0
DEST="${1:-.}"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
platform="${os}_${arch}"

case "$platform" in
    linux_amd64)  expected_sha256=1370446bbe74d562608e8005a6ccce02d146a661fbd78674e11cc70b9618d6cf ;;
    linux_arm64)  expected_sha256=c978982c60e1b4903a976de090f04dc4fac4a320daa50704fcad2dbc93433d62 ;;
    darwin_amd64) expected_sha256=5350f756e8408d0e22802b7f384af941448358b503eb1e1772979a61b9b99fde ;;
    darwin_arm64) expected_sha256=e74f8846c3b5d0428cfeae3f9f520bbf9031d18e68224108c3760d60b6aaf2e0 ;;
    *)
        echo "ERROR: no pinned mcp-publisher $VERSION digest for platform $platform" >&2
        exit 1
        ;;
esac

asset="mcp-publisher_${platform}.tar.gz"
url="https://github.com/modelcontextprotocol/registry/releases/download/v${VERSION}/${asset}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    --output "$work/$asset" "$url"

if command -v sha256sum >/dev/null 2>&1; then
    actual_sha256="$(sha256sum "$work/$asset" | cut -d' ' -f1)"
else
    actual_sha256="$(shasum -a 256 "$work/$asset" | cut -d' ' -f1)"
fi

if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "ERROR: digest mismatch for $asset" >&2
    echo "expected: $expected_sha256" >&2
    echo "actual:   $actual_sha256" >&2
    exit 1
fi

expected_members="LICENSE
README.md
mcp-publisher"
actual_members="$(tar tzf "$work/$asset" | LC_ALL=C sort)"
if [ "$actual_members" != "$(printf '%s' "$expected_members" | LC_ALL=C sort)" ]; then
    echo "ERROR: unexpected archive members in $asset" >&2
    exit 1
fi

mkdir -p "$DEST"
tar xzf "$work/$asset" -C "$DEST" mcp-publisher
chmod +x "$DEST/mcp-publisher"

version_output="$("$DEST/mcp-publisher" --version 2>&1)"
case "$version_output" in
    *"mcp-publisher $VERSION"*) ;;
    *)
        echo "ERROR: expected mcp-publisher $VERSION" >&2
        printf '%s\n' "$version_output" >&2
        exit 1
        ;;
esac
