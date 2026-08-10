"""Contract tests for scripts/resolve_dry_run.sh — the single canonical
dry_run resolution consumed by every privileged job in release.yml.

The critical case: a push of refs/tags/v* carries no ``inputs`` context at
all, so the workflow hands the script an empty string. That MUST resolve to
``false`` — an ordinary tag release publishes. Anything outside the script's
truth table must fail closed (non-zero exit), never guess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts" / "resolve_dry_run.sh"


def _resolve(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RESOLVER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_tag_push_with_absent_inputs_resolves_false() -> None:
    # push of refs/tags/vX.Y.Z: `inputs` does not exist, the workflow passes "".
    result = _resolve("push", "")
    assert result.returncode == 0
    assert result.stdout.strip() == "false"


def test_dispatch_with_absent_or_defaulted_input_resolves_false() -> None:
    # release-please dispatches without --field dry_run; the boolean default
    # stringifies to "false", but "" must also resolve false for robustness.
    result = _resolve("workflow_dispatch", "")
    assert result.returncode == 0
    assert result.stdout.strip() == "false"


def test_dispatch_with_explicit_false_resolves_false() -> None:
    result = _resolve("workflow_dispatch", "false")
    assert result.returncode == 0
    assert result.stdout.strip() == "false"


def test_dispatch_with_explicit_true_resolves_true() -> None:
    result = _resolve("workflow_dispatch", "true")
    assert result.returncode == 0
    assert result.stdout.strip() == "true"


def test_push_with_nonempty_input_fails_closed() -> None:
    # inputs cannot exist on a push event; a value here is a wiring error.
    result = _resolve("push", "true")
    assert result.returncode != 0
    assert "inputs cannot exist" in result.stderr


def test_dispatch_with_malformed_input_fails_closed() -> None:
    for malformed in ("garbage", "True", "TRUE", "1", "yes"):
        result = _resolve("workflow_dispatch", malformed)
        assert result.returncode != 0, f"malformed input accepted: {malformed!r}"
        assert "unrecognized dry_run input" in result.stderr


def test_unsupported_event_fails_closed() -> None:
    for event in ("schedule", "pull_request", "release", ""):
        result = _resolve(event, "")
        assert result.returncode != 0, f"unsupported event accepted: {event!r}"


def test_missing_argument_fails_closed() -> None:
    # The empty-input argument must be passed explicitly; arity is enforced.
    result = _resolve("push")
    assert result.returncode != 0
    assert "usage" in result.stderr
