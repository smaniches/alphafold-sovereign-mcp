from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "replicate.sh"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def test_replicate_script_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_replicate_verifies_downloaded_release_bytes() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    # `latest` must resolve through the project endpoint; PyPI has no
    # /latest/json release route.
    assert "https://pypi.org/pypi/${PKG_NAME}/json" in text
    assert "/${VERSION}/json" in text

    # A printed PyPI digest is not verification. The script must download the
    # artifact, recompute SHA-256 locally, and compare it to PyPI metadata.
    assert 'curl -fsSL "$url" -o "$artifact"' in text
    assert 'actual_hash="$(sha256_file "$artifact")"' in text
    assert '[[ "$actual_hash" == "$expected_hash" ]]' in text


def test_replicate_is_compatible_with_stock_macos_bash() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    executable = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    assert "mapfile" not in executable
    assert 'DIST_ROWS+=("$row")' in executable


def test_replicate_resolves_the_actual_github_release_tag() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "https://api.github.com/repos/${REPO}/releases/tags/${candidate}" in text
    assert "BASH_REMATCH[1]" in text
    assert 'TAG="$(jq -er' in text


def test_replicate_verifies_sigstore_bundle_against_exact_artifact_and_tag() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'release_asset_url "${filename}.sigstore"' in text
    assert "cosign verify-blob" in text
    assert '--certificate-oidc-issuer "https://token.actions.githubusercontent.com"' in text
    assert (
        'TAG_IDENTITY="https://github.com/${REPO}/.github/workflows/release.yml@refs/tags/${TAG}"'
        in text
    )
    assert '"$artifact"' in text
    assert "refs/heads/main" not in text


def test_release_signs_and_uploads_sbom_bundles() -> None:
    text = RELEASE.read_text(encoding="utf-8")

    assert "sboms/sbom.cyclonedx.json sboms/sbom.spdx.json" in text
    assert 'cosign sign-blob --yes "$f" --bundle "${f}.sigstore"' in text
    assert "sboms/*.sigstore" in text


def test_replicate_authenticates_new_sboms_and_documents_legacy_boundary() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'SIGNED_SBOM_FIRST_RELEASE="1.4.7"' in text
    assert 'release_asset_url "sbom.cyclonedx.json.sigstore"' in text
    assert 'release_asset_url "sbom.spdx.json.sigstore"' in text
    assert "CycloneDX SBOM Sigstore verification failed" in text
    assert "SPDX SBOM Sigstore verification failed" in text
    assert "predates signed SBOM assets" in text


def test_replicate_verifies_sbom_against_downloaded_wheel_from_any_cwd() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"' in text
    assert '"$REPO_ROOT/scripts/verify_sbom_binding.py" "$CYCLONE" "$WHEEL_PATH"' in text


def test_replicate_validates_required_spdx_document_structure() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    for required in (
        ".spdxVersion",
        ".SPDXID",
        ".dataLicense",
        ".documentNamespace",
        ".creationInfo.created",
        ".creationInfo.creators",
        ".packages",
    ):
        assert required in text
    assert "required SPDX document structure" in text


def test_replicate_never_uses_pypi_metadata_as_slsa_subject() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "slsa-verifier verify-artifact" in text
    assert '"$WHEEL_PATH"' in text
    assert "/tmp/pypi_meta.json" not in text
