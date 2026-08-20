from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replicate.sh"


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


def test_replicate_verifies_sigstore_bundle_against_exact_artifact() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "releases/download/${TAG}/${filename}.sigstore" in text
    assert "cosign verify-blob" in text
    assert '--certificate-oidc-issuer "https://token.actions.githubusercontent.com"' in text
    assert '"$artifact"' in text


def test_replicate_verifies_sbom_against_downloaded_wheel() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'scripts/verify_sbom_binding.py "$CYCLONE" "$WHEEL_PATH"' in text


def test_replicate_never_uses_pypi_metadata_as_slsa_subject() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "slsa-verifier verify-artifact" in text
    assert '"$WHEEL_PATH"' in text
    assert "/tmp/pypi_meta.json" not in text
