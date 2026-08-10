#!/usr/bin/env bash
# Canonical dry_run resolution for the release workflow.
#
# release.yml is invoked by two event families:
#
#   1. push of refs/tags/v*        — the `inputs` context does not exist, so
#                                    every `${{ inputs.* }}` expression renders
#                                    as the empty string;
#   2. workflow_dispatch           — `inputs.dry_run` is a `type: boolean`
#                                    input that GitHub stringifies to exactly
#                                    "true" or "false" ("" only if the input
#                                    is ever removed from the workflow).
#
# This script is the single place that turns (event name, raw input) into the
# one canonical dry_run value every privileged downstream job consumes.
#
#   EVENT              RAW INPUT        OUTPUT
#   push               "" (absent)      false     ordinary tag release publishes
#   workflow_dispatch  "" (default)     false     release-please dispatch publishes
#   workflow_dispatch  "false"          false
#   workflow_dispatch  "true"           true      nothing privileged may run
#   push               non-empty        error     inputs cannot exist on push
#   workflow_dispatch  anything else    error     malformed input, fail closed
#   any other event    *                error     unsupported invocation family
#
# Fail closed: any state outside the table above aborts the workflow rather
# than guessing. A missing-input tag push must resolve to "false" (publish),
# which is why the push arm accepts only the empty string.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <github-event-name> <dry-run-input>" >&2
  echo "(pass the second argument explicitly, even when it is empty)" >&2
  exit 64
fi

event="$1"
raw="$2"

case "$event" in
  push)
    # `inputs` does not exist for tag-push events; a non-empty value here
    # means the workflow wiring changed underneath this contract.
    if [[ -n "$raw" ]]; then
      echo "dry_run input '$raw' present on a push event; inputs cannot exist here" >&2
      exit 65
    fi
    printf 'false\n'
    ;;
  workflow_dispatch)
    case "$raw" in
      true)
        printf 'true\n'
        ;;
      false | "")
        printf 'false\n'
        ;;
      *)
        echo "unrecognized dry_run input: '$raw' (expected 'true', 'false', or empty)" >&2
        exit 66
        ;;
    esac
    ;;
  *)
    echo "unsupported event for release dry_run resolution: '$event'" >&2
    exit 67
    ;;
esac
