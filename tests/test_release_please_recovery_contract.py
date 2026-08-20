"""Fail-closed contracts for Release Please recovery behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-please.yml"
WORKFLOW = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _on(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the workflow trigger mapping despite YAML 1.1's `on` coercion."""
    return workflow.get("on") or workflow[True]


def _step(step_id: str) -> dict[str, Any]:
    for step in WORKFLOW["jobs"]["release-please"]["steps"]:
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"missing workflow step id {step_id!r}")


def _named_step(name: str) -> dict[str, Any]:
    for step in WORKFLOW["jobs"]["release-please"]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"missing workflow step {name!r}")


def test_release_please_retains_push_and_manual_retry_triggers() -> None:
    triggers = _on(WORKFLOW)
    assert triggers["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in triggers


def test_pending_release_detection_is_singleton_and_fail_closed() -> None:
    run = _step("mode")["run"]

    assert "--state merged" in run
    assert '--label "autorelease: pending"' in run
    assert "pending_count > 1" in run
    assert "exit 1" in run
    assert "recovery_only=true" in run
    assert "pending_pr=$pending_pr" in run


def test_recovery_mode_cannot_open_another_release_pr() -> None:
    release = _step("release")
    assert release["with"]["skip-github-pull-request"] == (
        "${{ steps.mode.outputs.recovery_only }}"
    )


def test_recovery_fails_unless_release_is_actually_created() -> None:
    guard = _named_step("Require pending-release recovery to create a release")
    condition = " ".join(str(guard["if"]).split())

    assert "steps.mode.outputs.recovery_only == 'true'" in condition
    assert "steps.release.outputs.release_created != 'true'" in condition
    assert "exit 1" in guard["run"]


def test_publication_dispatch_still_requires_release_created() -> None:
    dispatch = _named_step("Dispatch build + sign + PyPI publish (release.yml)")
    assert dispatch["if"] == "${{ steps.release.outputs.release_created }}"
    assert "gh workflow run release.yml" in dispatch["run"]
