from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts" / "resolve_release_tag.sh"
CONTEXT_VERIFIER = ROOT / "scripts" / "verify_release_context.sh"
INSTALLER = ROOT / "scripts" / "install_mcp_publisher.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo_with_tag_behind_head(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Release Integrity Test")
    _git(repo, "config", "user.email", "release-integrity@example.invalid")

    tracked = repo / "tracked.txt"
    tracked.write_text("tagged release\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "tagged")
    tagged_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "v1.2.3")

    tracked.write_text("workflow dispatch ref has drifted\n", encoding="utf-8")
    _git(repo, "commit", "-am", "later branch head")
    head_sha = _git(repo, "rev-parse", "HEAD")
    assert head_sha != tagged_sha
    return repo, tagged_sha, head_sha


def _verify_context(
    tag: str,
    resolved_sha: str,
    github_ref: str,
    github_sha: str,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(GITHUB_REF=github_ref, GITHUB_SHA=github_sha)
    return subprocess.run(
        ["bash", str(CONTEXT_VERIFIER), tag, resolved_sha],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_mismatched_dispatch_resolves_tag_commit_not_current_head(tmp_path: Path) -> None:
    repo, tagged_sha, head_sha = _repo_with_tag_behind_head(tmp_path)

    result = subprocess.run(
        ["bash", str(RESOLVER), "v1.2.3"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == tagged_sha
    assert result.stdout.strip() != head_sha


def test_resolver_peels_annotated_tag_to_commit(tmp_path: Path) -> None:
    repo, _tagged_sha, _head_sha = _repo_with_tag_behind_head(tmp_path)
    _git(repo, "tag", "-a", "v2.0.0", "-m", "annotated", "HEAD~1")
    expected = _git(repo, "rev-parse", "v2.0.0^{commit}")

    result = subprocess.run(
        ["bash", str(RESOLVER), "refs/tags/v2.0.0"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == expected


def test_resolver_rejects_missing_tag(tmp_path: Path) -> None:
    repo, _tagged_sha, _head_sha = _repo_with_tag_behind_head(tmp_path)

    result = subprocess.run(
        ["bash", str(RESOLVER), "v9.9.9"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "does not resolve to a commit" in result.stderr


def test_release_context_accepts_exact_tag_and_sha() -> None:
    sha = "a" * 40
    result = _verify_context("v1.2.3", sha, "refs/tags/v1.2.3", sha)

    assert result.returncode == 0
    assert "release workflow context verified" in result.stdout


def test_release_context_rejects_dispatch_on_branch_even_if_tag_input_resolves() -> None:
    sha = "a" * 40
    result = _verify_context("v1.2.3", sha, "refs/heads/main", sha)

    assert result.returncode != 0
    assert "release workflow ref mismatch" in result.stderr


def test_release_context_rejects_sha_different_from_tag_target() -> None:
    resolved_sha = "a" * 40
    workflow_sha = "b" * 40
    result = _verify_context("v1.2.3", resolved_sha, "refs/tags/v1.2.3", workflow_sha)

    assert result.returncode != 0
    assert "release workflow SHA mismatch" in result.stderr


def test_publisher_installer_fails_closed_on_wrong_digest(tmp_path: Path) -> None:
    fake_archive = tmp_path / "mcp-publisher_linux_amd64.tar.gz"
    fake_archive.write_bytes(b"not the approved publisher archive")

    result = subprocess.run(
        ["bash", str(INSTALLER), "--archive", str(fake_archive)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "SHA-256 mismatch" in result.stderr
    assert not (tmp_path / "mcp-publisher").exists()


def test_release_workflow_uses_resolved_sha_and_no_mutable_publisher() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ref: ${{ needs.resolve_release.outputs.sha }}" in workflow
    assert 'bash scripts/verify_release_context.sh "$tag" "$sha"' in workflow
    assert "registry/releases/latest" not in workflow
    assert "bash scripts/install_mcp_publisher.sh" in workflow
