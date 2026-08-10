#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || -z "${1:-}" || -z "${2:-}" ]]; then
  echo "usage: $0 <tag> <resolved-commit-sha>" >&2
  exit 64
fi

tag="${1#refs/tags/}"
resolved_sha="$2"
expected_ref="refs/tags/$tag"

if [[ -z "${GITHUB_REF:-}" || -z "${GITHUB_SHA:-}" ]]; then
  echo "GitHub release context is incomplete: GITHUB_REF and GITHUB_SHA are required" >&2
  exit 65
fi

# The SLSA generic generator derives configSource/material identity from the
# workflow invocation's github.ref/github.sha, not from a later checkout.
# Therefore the workflow itself must be invoked on the exact release tag.
if [[ "$GITHUB_REF" != "$expected_ref" ]]; then
  echo "release workflow ref mismatch" >&2
  echo "expected: $expected_ref" >&2
  echo "actual:   $GITHUB_REF" >&2
  echo "dispatch release.yml with --ref '$tag' and --field tag='$tag'" >&2
  exit 66
fi

if [[ "$GITHUB_SHA" != "$resolved_sha" ]]; then
  echo "release workflow SHA mismatch" >&2
  echo "tag resolves to: $resolved_sha" >&2
  echo "workflow SHA:    $GITHUB_SHA" >&2
  exit 67
fi

printf 'release workflow context verified: %s -> %s\n' "$expected_ref" "$resolved_sha"
