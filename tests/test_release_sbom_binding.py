"""Tests for the SBOM <-> wheel binding contract:

- scripts/bind_sbom_wheel.py binds SHA-256(wheel) into the SBOM root
  component and refuses identity drift;
- scripts/verify_sbom_binding.py independently verifies root name, root
  version, and root SHA-256 against the exact wheel, failing closed on any
  substitution;
- scripts/verify_sbom_negative.sh proves the verifier rejects tampered
  artifacts, and itself fails when the positive control fails.

Synthetic wheels are built in-process so the tests are hermetic and fast.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIND = ROOT / "scripts" / "bind_sbom_wheel.py"
VERIFY = ROOT / "scripts" / "verify_sbom_binding.py"
NEGATIVE = ROOT / "scripts" / "verify_sbom_negative.sh"


def _make_wheel(directory: Path, name: str = "demo-pkg", version: str = "1.2.3") -> Path:
    stem = name.replace("-", "_").replace(".", "_").lower()
    path = directory / f"{stem}-{version}-py3-none-any.whl"
    info = f"{stem}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{stem}/__init__.py", "")
        archive.writestr(
            f"{info}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        archive.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\n")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sbom(
    path: Path,
    name: str = "demo-pkg",
    version: str = "1.2.3",
    hashes: list[dict[str, str]] | None = None,
    component: dict | None = None,
    bom_format: str = "CycloneDX",
) -> Path:
    if component is None:
        component = {"type": "library", "name": name, "version": version}
        if hashes is not None:
            component["hashes"] = hashes
    sbom = {
        "bomFormat": bom_format,
        "specVersion": "1.6",
        "metadata": {"component": component},
        "components": [],
    }
    path.write_text(json.dumps(sbom), encoding="utf-8")
    return path


def _run(script: Path, *args: str | Path) -> subprocess.CompletedProcess[str]:
    if script.suffix == ".py":
        command = [sys.executable, str(script), *map(str, args)]
    else:
        command = ["bash", str(script), *map(str, args)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _bound_pair(tmp_path: Path) -> tuple[Path, Path]:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json", hashes=[{"alg": "SHA-256", "content": _sha256(wheel)}]
    )
    return sbom, wheel


# ── verify_sbom_binding.py: positive cases ─────────────────────────────────


def test_verifier_accepts_matching_sbom_and_wheel(tmp_path: Path) -> None:
    sbom, wheel = _bound_pair(tmp_path)
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode == 0, result.stderr
    assert "SBOM binding verified" in result.stdout


def test_verifier_accepts_dist_directory_with_exactly_one_wheel(tmp_path: Path) -> None:
    sbom, _wheel = _bound_pair(tmp_path)
    result = _run(VERIFY, sbom, tmp_path)
    assert result.returncode == 0, result.stderr


def test_verifier_normalizes_project_name_spelling(tmp_path: Path) -> None:
    # METADATA "Demo.Pkg" and SBOM "demo-pkg" are the same PEP 503 project.
    wheel = _make_wheel(tmp_path, name="Demo.Pkg")
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        name="demo-pkg",
        hashes=[{"alg": "SHA-256", "content": _sha256(wheel)}],
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode == 0, result.stderr


def test_verifier_accepts_uppercase_hex_digest(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        hashes=[{"alg": "SHA-256", "content": _sha256(wheel).upper()}],
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode == 0, result.stderr


# ── verify_sbom_binding.py: substitution and malformation cases ────────────


def test_verifier_rejects_dist_directory_with_two_wheels(tmp_path: Path) -> None:
    sbom, _wheel = _bound_pair(tmp_path)
    _make_wheel(tmp_path, name="second-pkg")
    result = _run(VERIFY, sbom, tmp_path)
    assert result.returncode != 0
    assert "exactly one wheel" in result.stderr


def test_verifier_rejects_substituted_wheel_content(tmp_path: Path) -> None:
    sbom, wheel = _bound_pair(tmp_path)
    wheel.write_bytes(wheel.read_bytes() + b"substituted")
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "does not match recomputed SHA-256" in result.stderr


def test_verifier_rejects_wrong_root_hash(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        hashes=[{"alg": "SHA-256", "content": hashlib.sha256(b"other").hexdigest()}],
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "SHA-256" in result.stderr


def test_verifier_rejects_wrong_root_name(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        name="substituted-package",
        hashes=[{"alg": "SHA-256", "content": _sha256(wheel)}],
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "name" in result.stderr


def test_verifier_rejects_wrong_root_version(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        version="9.9.9",
        hashes=[{"alg": "SHA-256", "content": _sha256(wheel)}],
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "version" in result.stderr


def test_verifier_rejects_missing_root_component(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom_path = tmp_path / "sbom.json"
    sbom_path.write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "metadata": {}}),
        encoding="utf-8",
    )
    result = _run(VERIFY, sbom_path, wheel)
    assert result.returncode != 0
    assert "metadata.component" in result.stderr


def test_verifier_rejects_missing_sha256_hash(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(tmp_path / "sbom.json", hashes=[])
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "exactly one SHA-256" in result.stderr


def test_verifier_rejects_multiple_sha256_hashes(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    digest = _sha256(wheel)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        hashes=[
            {"alg": "SHA-256", "content": digest},
            {"alg": "SHA-256", "content": hashlib.sha256(b"shadow").hexdigest()},
        ],
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "exactly one SHA-256" in result.stderr


def test_verifier_rejects_non_cyclonedx_document(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        hashes=[{"alg": "SHA-256", "content": _sha256(wheel)}],
        bom_format="SPDX",
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "bomFormat" in result.stderr


def test_verifier_rejects_wheel_with_two_dist_info_metadata(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(
            "shadow_pkg-0.0.1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: shadow-pkg\nVersion: 0.0.1\n",
        )
    sbom = _make_sbom(
        tmp_path / "sbom.json", hashes=[{"alg": "SHA-256", "content": _sha256(wheel)}]
    )
    result = _run(VERIFY, sbom, wheel)
    assert result.returncode != 0
    assert "exactly one .dist-info/METADATA" in result.stderr


# ── bind_sbom_wheel.py ─────────────────────────────────────────────────────


def test_bind_writes_wheel_digest_into_root_component(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(tmp_path / "sbom.json")  # no hashes yet

    result = _run(BIND, sbom, wheel)
    assert result.returncode == 0, result.stderr

    bound = json.loads(sbom.read_text(encoding="utf-8"))
    component = bound["metadata"]["component"]
    assert component["hashes"] == [{"alg": "SHA-256", "content": _sha256(wheel)}]
    assert {"name": "smaniches:release:bound-wheel-filename", "value": wheel.name} in (
        component["properties"]
    )

    verified = _run(VERIFY, sbom, wheel)
    assert verified.returncode == 0, verified.stderr


def test_bind_refuses_conflicting_digest_and_leaves_sbom_unchanged(tmp_path: Path) -> None:
    # A pre-existing SHA-256 that disagrees with the exact wheel is evidence
    # of drift or substitution; binding must never repair it.
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        hashes=[{"alg": "SHA-256", "content": hashlib.sha256(b"conflicting").hexdigest()}],
    )
    before = sbom.read_text(encoding="utf-8")

    result = _run(BIND, sbom, wheel)
    assert result.returncode != 0
    assert "conflicts with" in result.stderr
    assert sbom.read_text(encoding="utf-8") == before, "bind must not modify on refusal"


def test_bind_refuses_multiple_existing_sha256_and_leaves_sbom_unchanged(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        hashes=[
            {"alg": "SHA-256", "content": _sha256(wheel)},
            {"alg": "SHA-256", "content": hashlib.sha256(b"shadow").hexdigest()},
        ],
    )
    before = sbom.read_text(encoding="utf-8")

    result = _run(BIND, sbom, wheel)
    assert result.returncode != 0
    assert "SHA-256" in result.stderr
    assert sbom.read_text(encoding="utf-8") == before, "bind must not modify on refusal"


def test_bind_accepts_and_preserves_an_equal_existing_digest(tmp_path: Path) -> None:
    # Uppercase hex proves preservation: the entry survives verbatim rather
    # than being rewritten with the recomputed lowercase digest.
    wheel = _make_wheel(tmp_path)
    existing = _sha256(wheel).upper()
    sbom = _make_sbom(tmp_path / "sbom.json", hashes=[{"alg": "SHA-256", "content": existing}])

    result = _run(BIND, sbom, wheel)
    assert result.returncode == 0, result.stderr

    bound = json.loads(sbom.read_text(encoding="utf-8"))
    assert bound["metadata"]["component"]["hashes"] == [{"alg": "SHA-256", "content": existing}]
    assert _run(VERIFY, sbom, wheel).returncode == 0


def test_bind_preserves_unrelated_non_sha256_hashes(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sha512_entry = {"alg": "SHA-512", "content": hashlib.sha512(b"unrelated").hexdigest()}
    sbom = _make_sbom(tmp_path / "sbom.json", hashes=[sha512_entry])

    result = _run(BIND, sbom, wheel)
    assert result.returncode == 0, result.stderr

    bound = json.loads(sbom.read_text(encoding="utf-8"))
    hashes = bound["metadata"]["component"]["hashes"]
    assert sha512_entry in hashes
    assert {"alg": "SHA-256", "content": _sha256(wheel)} in hashes
    assert _run(VERIFY, sbom, wheel).returncode == 0


def test_bind_refuses_mismatched_name(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(tmp_path / "sbom.json", name="other-package")
    before = sbom.read_text(encoding="utf-8")

    result = _run(BIND, sbom, wheel)
    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert sbom.read_text(encoding="utf-8") == before, "bind must not modify on refusal"


def test_bind_refuses_mismatched_version(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(tmp_path / "sbom.json", version="0.0.0")
    before = sbom.read_text(encoding="utf-8")

    result = _run(BIND, sbom, wheel)
    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert sbom.read_text(encoding="utf-8") == before


def test_bind_refuses_sbom_without_root_component(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = tmp_path / "sbom.json"
    sbom.write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "metadata": {}}),
        encoding="utf-8",
    )
    result = _run(BIND, sbom, wheel)
    assert result.returncode != 0
    assert "metadata.component" in result.stderr


# ── verify_sbom_negative.sh ────────────────────────────────────────────────


def test_negative_harness_passes_on_a_genuine_pair(tmp_path: Path) -> None:
    sbom, wheel = _bound_pair(tmp_path)
    result = _run(NEGATIVE, sbom, wheel, "--python", sys.executable)
    assert result.returncode == 0, result.stderr
    assert "all negative substitution cases rejected" in result.stdout


def test_negative_harness_accepts_a_dist_directory(tmp_path: Path) -> None:
    sbom, _wheel = _bound_pair(tmp_path)
    result = _run(NEGATIVE, sbom, tmp_path, "--python", sys.executable)
    assert result.returncode == 0, result.stderr


def test_negative_harness_fails_when_positive_control_fails(tmp_path: Path) -> None:
    wheel = _make_wheel(tmp_path)
    sbom = _make_sbom(
        tmp_path / "sbom.json",
        hashes=[{"alg": "SHA-256", "content": hashlib.sha256(b"not the wheel").hexdigest()}],
    )
    result = _run(NEGATIVE, sbom, wheel, "--python", sys.executable)
    assert result.returncode != 0
