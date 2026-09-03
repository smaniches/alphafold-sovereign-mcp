"""Static contract tests over release.yml, ci.yml, and the hash-locked
release-tool closure.

These prove, from the committed files alone:

- the canonical dry_run mechanism is centralized in resolve_release and every
  externally mutating job is gated on it with the fail-closed ``== 'false'``
  form (a tag push with absent inputs can never be misread as a dry run);
- the non-mutating pipeline (resolve_release -> build -> sbom) carries no
  dry_run gate, so AF-01 can be falsified against real GitHub context;
- the unprivileged PR proof job exists, holds contents: read and nothing
  else, and executes the exact release-path scripts pre-merge;
- the release toolchain lock is fully hash-pinned and resolved explicitly
  against Python 3.12, the release-runner interpreter.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import SpecifierSet
from packaging.requirements import Requirement

try:
    import tomllib
except ImportError:  # Python 3.10: tomli ships via the dev closure (nox)
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ROOT / ".github" / "workflows" / "release.yml"
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
LOCK_PATH = ROOT / "requirements" / "release-tools.txt"
INTENT_PATH = ROOT / "requirements" / "release-tools.in"
PYPROJECT_PATH = ROOT / "pyproject.toml"

RELEASE = yaml.safe_load(RELEASE_PATH.read_text(encoding="utf-8"))
CI = yaml.safe_load(CI_PATH.read_text(encoding="utf-8"))

DRY_RUN_GATE = "needs.resolve_release.outputs.dry_run == 'false'"

# The exact uv release the AF-03 paths are reviewed against. Must match the
# setup-uv `version:` in release.yml build/sbom and ci.yml release-path-proof,
# and the regeneration instructions in requirements/release-tools.in.
UV_PIN = "0.12.3"

# Jobs that publish, sign, attest, or otherwise mutate state outside the
# workflow run. Each must be gated on the one canonical dry_run output:
#   provenance           — SLSA attestation, signed via OIDC, lands in the
#                          public Rekor transparency log
#   publish-pypi         — uploads immutable artifacts to the public index
#   publish-github       — cosign (Rekor log) + creates the GitHub Release
#   publish-mcp-registry — writes to the public MCP Registry
#   dispatch-verify      — dispatches the post-publish verifier; meaningless on a dry run
EXTERNALLY_MUTATING_JOBS = (
    "provenance",
    "publish-pypi",
    "publish-github",
    "publish-mcp-registry",
    "dispatch-verify",
)

# Non-mutating jobs: read-only permissions, produce only ephemeral workflow
# artifacts. They must stay ungated so a dry_run=true dispatch still executes
# resolution, build, and SBOM verification end to end.
NON_MUTATING_JOBS = ("resolve_release", "build", "sbom")

RELEASE_PATH_SCRIPTS = (
    "scripts/install_release_tooling.sh",
    "scripts/build_release_dist.sh",
    "scripts/generate_release_sbom.sh",
    "scripts/verify_sbom_binding.py",
    "scripts/verify_sbom_negative.sh",
)


def _on(workflow: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 parses a bare `on:` key as boolean True.
    return workflow.get("on") or workflow[True]


def _run_blob(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def _normalized_if(job: dict[str, Any]) -> str:
    condition = str(job.get("if", ""))
    condition = condition.removeprefix("${{").removesuffix("}}")
    return " ".join(condition.split())


# ── release.yml: canonical dry_run ─────────────────────────────────────────


def test_dispatch_declares_boolean_dry_run_defaulting_false() -> None:
    inputs = _on(RELEASE)["workflow_dispatch"]["inputs"]
    dry_run = inputs["dry_run"]
    assert dry_run["type"] == "boolean"
    assert dry_run["default"] is False
    assert dry_run["required"] is False


def test_tag_push_trigger_is_retained() -> None:
    tags = _on(RELEASE)["push"]["tags"]
    assert "v*.*.*" in tags


def test_resolve_release_emits_canonical_dry_run_output() -> None:
    job = RELEASE["jobs"]["resolve_release"]
    assert job["outputs"]["dry_run"] == "${{ steps.dry_run.outputs.dry_run }}"

    steps = {step.get("id"): step for step in job["steps"] if step.get("id")}
    resolve_step = steps["dry_run"]
    # The raw input is delivered via env, so an absent `inputs` context on a
    # tag push renders as the empty string rather than an expression error.
    assert resolve_step["env"]["INPUT_DRY_RUN"] == "${{ inputs.dry_run }}"
    assert (
        'scripts/resolve_dry_run.sh "$GITHUB_EVENT_NAME" "$INPUT_DRY_RUN"' in (resolve_step["run"])
    )


def test_no_job_condition_reads_dry_run_input_directly() -> None:
    # The event-name switch lives in scripts/resolve_dry_run.sh. No job may
    # re-derive dry_run from the raw input: on a tag push `inputs` is absent,
    # and an ad-hoc string comparison there is exactly the fragile pattern
    # that can silently skip an ordinary tag release.
    for name, job in RELEASE["jobs"].items():
        condition = str(job.get("if", ""))
        assert "inputs.dry_run" not in condition, name
        assert "github.event.inputs" not in condition, name


def test_every_externally_mutating_job_is_gated_on_canonical_dry_run() -> None:
    for name in EXTERNALLY_MUTATING_JOBS:
        job = RELEASE["jobs"][name]
        assert _normalized_if(job) == DRY_RUN_GATE, name
        assert "resolve_release" in job["needs"], name


def test_gates_use_fail_closed_equality_not_inequality() -> None:
    # `== 'false'` skips the privileged job when the output is missing or
    # malformed; `!= 'true'` would run it. Only the fail-closed form is legal.
    for name in EXTERNALLY_MUTATING_JOBS:
        condition = _normalized_if(RELEASE["jobs"][name])
        assert "== 'false'" in condition, name
        assert "!= 'true'" not in condition, name


def test_non_mutating_pipeline_stays_executable_in_dry_run_mode() -> None:
    # AF-01 falsification requires resolve_release (and the build/SBOM chain)
    # to execute under dry_run=true against real GitHub context.
    for name in NON_MUTATING_JOBS:
        assert "if" not in RELEASE["jobs"][name], name


def test_gated_job_set_and_ungated_job_set_partition_the_workflow() -> None:
    assert set(RELEASE["jobs"]) == set(EXTERNALLY_MUTATING_JOBS) | set(NON_MUTATING_JOBS)


def test_dispatch_verify_runs_the_published_release_verifier_after_publish() -> None:
    # The verifier reads PyPI and the GitHub Release back, so it may only be
    # dispatched after both publication jobs, and it needs nothing beyond the
    # right to start a workflow run. Its dry_run gate is covered above via
    # EXTERNALLY_MUTATING_JOBS.
    job = RELEASE["jobs"]["dispatch-verify"]
    assert "publish-pypi" in job["needs"]
    assert "publish-github" in job["needs"]
    assert job["permissions"] == {"actions": "write"}
    assert "gh workflow run verify-published-release.yml" in _run_blob(job)


# ── release.yml: deterministic build/SBOM path ─────────────────────────────


def test_release_build_job_uses_locked_toolchain_scripts() -> None:
    blob = _run_blob(RELEASE["jobs"]["build"])
    assert "scripts/install_release_tooling.sh" in blob
    assert "scripts/build_release_dist.sh" in blob
    assert "uv python install 3.12" in blob


def test_release_sbom_job_binds_and_verifies_against_the_exact_wheel() -> None:
    blob = _run_blob(RELEASE["jobs"]["sbom"])
    assert "scripts/install_release_tooling.sh" in blob
    assert "scripts/generate_release_sbom.sh" in blob
    assert "scripts/verify_sbom_binding.py" in blob
    assert "scripts/verify_sbom_negative.sh" in blob


def test_release_workflow_has_no_floating_build_frontend() -> None:
    text = RELEASE_PATH.read_text(encoding="utf-8")
    assert re.search(r"\buv build\b", text) is None


# ── ci.yml: unprivileged PR proof job ──────────────────────────────────────


def test_pr_proof_job_exists_with_contents_read_only() -> None:
    job = CI["jobs"]["release-path-proof"]
    assert job["permissions"] == {"contents": "read"}


def test_pr_proof_job_holds_no_privileged_scopes() -> None:
    job = CI["jobs"]["release-path-proof"]
    permissions = job["permissions"]
    for scope in (
        "id-token",
        "attestations",
        "packages",
        "actions",
        "deployments",
        "pages",
        "pull-requests",
        "security-events",
    ):
        assert scope not in permissions, scope
    assert permissions.get("contents") == "read"
    # No deployment environment, hence no environment-scoped credentials.
    assert "environment" not in job


def test_pr_proof_job_runs_on_pull_requests() -> None:
    assert "pull_request" in _on(CI)


def test_pr_proof_job_executes_the_full_release_contract() -> None:
    blob = _run_blob(CI["jobs"]["release-path-proof"])
    for script in RELEASE_PATH_SCRIPTS:
        assert script in blob, script
    assert "uv python install 3.12" in blob


def test_pr_proof_job_is_required_by_the_all_green_gate() -> None:
    all_checks = CI["jobs"]["all-checks"]
    assert "release-path-proof" in all_checks["needs"]
    assert "needs.release-path-proof.result" in _run_blob(all_checks)


def test_pr_proof_and_release_execute_the_same_script_chain() -> None:
    # Parity guard: the pre-merge proof must not drift from the release path.
    proof_blob = _run_blob(CI["jobs"]["release-path-proof"])
    release_blob = _run_blob(RELEASE["jobs"]["build"]) + _run_blob(RELEASE["jobs"]["sbom"])
    proof_scripts = {s for s in RELEASE_PATH_SCRIPTS if s in proof_blob}
    release_scripts = {s for s in RELEASE_PATH_SCRIPTS if s in release_blob}
    assert proof_scripts == set(RELEASE_PATH_SCRIPTS)
    assert release_scripts == set(RELEASE_PATH_SCRIPTS)


def _setup_uv_versions(job: dict[str, Any]) -> list[str]:
    return [
        str(step.get("with", {}).get("version", "<missing>"))
        for step in job.get("steps", [])
        if "astral-sh/setup-uv" in str(step.get("uses", ""))
    ]


def test_af03_paths_pin_uv_exactly() -> None:
    # The AF-03 release paths must execute the reviewed uv release, never a
    # floating "latest" that can silently change the resolver underneath the
    # hash-locked toolchain. Unrelated CI jobs are deliberately not covered.
    af03_jobs = {
        "release.yml build": RELEASE["jobs"]["build"],
        "release.yml sbom": RELEASE["jobs"]["sbom"],
        "ci.yml release-path-proof": CI["jobs"]["release-path-proof"],
    }
    for label, job in af03_jobs.items():
        versions = _setup_uv_versions(job)
        assert versions, f"{label} lost its setup-uv step"
        for version in versions:
            assert version != "latest", f"{label} floats uv via 'latest'"
            assert version == UV_PIN, f"{label} pins uv {version!r}, expected {UV_PIN!r}"


# ── requirements/release-tools.{in,txt}: the hash-locked closure ───────────


def _lock_logical_lines() -> list[str]:
    text = LOCK_PATH.read_text(encoding="utf-8")
    return [line.strip() for line in re.split(r"(?<!\\)\n", text.replace("\\\n", " "))]


def _lock_requirement_lines() -> list[str]:
    return [
        line
        for line in _lock_logical_lines()
        if line and not line.startswith("#") and not line.startswith("-")
    ]


def _intent_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in INTENT_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, version = line.partition("==")
        pins[name.strip()] = version.strip()
    return pins


def test_release_tools_lock_is_fully_hash_pinned() -> None:
    lines = _lock_requirement_lines()
    assert lines, "lock file contains no requirements"
    for line in lines:
        assert "==" in line, f"unpinned requirement: {line}"
        assert "--hash=sha256:" in line, f"requirement without hash: {line}"


def test_release_tools_lock_resolved_explicitly_against_python_312() -> None:
    header = LOCK_PATH.read_text(encoding="utf-8").split("\n", 3)
    command_line = header[1]
    assert "--python-version 3.12" in command_line
    assert "--generate-hashes" in command_line


def test_release_tools_lock_resolved_wheel_only_from_clean_state() -> None:
    # --no-build forbids arbitrary sdist builds during resolution and
    # --no-cache resolves from clean state; the recorded command must carry
    # both. (?!-) keeps --no-build-isolation from satisfying the check.
    command_line = LOCK_PATH.read_text(encoding="utf-8").split("\n", 3)[1]
    assert re.search(r"--no-build(?!-)", command_line)
    assert "--no-cache" in command_line


def test_release_tooling_install_is_wheel_only_and_hash_required() -> None:
    # Consumption must mirror the wheel-only resolution: pip may neither
    # accept an unhashed artifact nor fall back to building an sdist.
    installer = (ROOT / "scripts" / "install_release_tooling.sh").read_text(encoding="utf-8")
    assert "--require-hashes" in installer
    assert "--only-binary=:all:" in installer


def test_release_tools_lock_has_no_interpreter_patch_sensitivity() -> None:
    # A python_full_version marker could flip resolution when GitHub's runner
    # supplies a different 3.12 patch release; the lock must not carry one.
    assert "python_full_version" not in LOCK_PATH.read_text(encoding="utf-8")


def test_intent_pins_cover_the_release_tool_surface_and_match_the_lock() -> None:
    pins = _intent_pins()
    assert set(pins) == {"build", "hatchling", "cyclonedx-bom"}
    lock_text = LOCK_PATH.read_text(encoding="utf-8")
    for name, version in pins.items():
        assert version, f"{name} is not an exact pin"
        assert re.search(rf"^{re.escape(name)}=={re.escape(version)} ", lock_text, re.MULTILINE), (
            f"lock does not pin {name}=={version}"
        )


def test_locked_hatchling_satisfies_pyproject_build_system() -> None:
    # --no-isolation imports the backend from the locked closure, so the
    # hatchling pin must satisfy pyproject's [build-system] requires.
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    requires = [Requirement(r) for r in pyproject["build-system"]["requires"]]
    hatchling_reqs = [r for r in requires if r.name == "hatchling"]
    assert hatchling_reqs, "pyproject build-system no longer requires hatchling"
    pinned = _intent_pins()["hatchling"]
    for requirement in hatchling_reqs:
        specifier: SpecifierSet = requirement.specifier
        assert specifier.contains(pinned), f"hatchling=={pinned} violates {requirement}"
