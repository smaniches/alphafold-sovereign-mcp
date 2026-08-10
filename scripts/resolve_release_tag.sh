#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "${1:-}" ]]; then
  echo "usage: $0 <tag>" >&2
  exit 64
fi

tag="$1"
case "$tag" in
  refs/tags/*) tag_ref="$tag" ;;
  *) tag_ref="refs/tags/$tag" ;;
esac

if ! git check-ref-format "$tag_ref" >/dev/null 2>&1; then
  echo "invalid release tag ref: $tag" >&2
  exit 65
fi

# Resolve both lightweight and annotated tags to the commit they identify.
# Prefixing with refs/tags/ prevents a branch/ref-name collision, while
# ^{commit} peels annotated tags and rejects tags that do not identify a commit.
sha="$(git rev-parse --verify "${tag_ref}^{commit}")" || {
  echo "release tag does not resolve to a commit: $tag" >&2
  exit 66
}

if ! git cat-file -e "${sha}^{commit}" 2>/dev/null; then
  echo "resolved object is not a commit: $sha" >&2
  exit 67
fi

printf '%s\n' "$sha"
