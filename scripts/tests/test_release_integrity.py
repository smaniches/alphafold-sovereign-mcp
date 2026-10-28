"""Offline negative and positive tests for release integrity boundaries."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import release_assets
import release_spdx


class ReleaseIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        self.wheel = self.dist / "alphafold_sovereign_mcp-1.5.5-py3-none-any.whl"
        with zipfile.ZipFile(self.wheel, "w") as archive:
            archive.writestr(
                "alphafold_sovereign_mcp-1.5.5.dist-info/METADATA",
                "Name: alphafold-sovereign-mcp\nVersion: 1.5.5\n",
            )
        self.sdist = self.dist / "alphafold_sovereign_mcp-1.5.5.tar.gz"
        self.sdist.write_bytes(b"unaltered source distribution")
        digest = hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        self.cdx = {
            "bomFormat": "CycloneDX",
            "metadata": {
                "timestamp": "2026-10-20T00:00:00Z",
                "component": {
                    "bom-ref": "root",
                    "name": "alphafold-sovereign-mcp",
                    "version": "1.5.5",
                    "hashes": [{"alg": "SHA-256", "content": digest}],
                },
            },
            "components": [
                {
                    "bom-ref": "fastmcp",
                    "name": "fastmcp",
                    "version": "4.0.11",
                },
                {
                    "bom-ref": "pydantic",
                    "name": "pydantic",
                    "version": "2.14.1",
                },
            ],
            "dependencies": [
                {"ref": "root", "dependsOn": ["fastmcp"]},
                {"ref": "fastmcp", "dependsOn": ["pydantic"]},
                {"ref": "pydantic", "dependsOn": []},
            ],
        }
        self.spdx = release_spdx.spdx_document(self.cdx)

    def verify(self, *, cdx=None, spdx=None, environment=None) -> None:
        release_spdx.verify(
            self.cdx if cdx is None else cdx,
            self.spdx if spdx is None else spdx,
            self.dist,
            environment,
        )

    def test_valid_spdx_records_every_package_and_dependency(self) -> None:
        self.verify()
        self.assertEqual(len(self.spdx["packages"]), 3)
        self.assertEqual(len(self.spdx["relationships"]), 3)
        self.assertEqual(self.spdx, release_spdx.spdx_document(self.cdx))

    def test_reject_inventoried_package_without_dependency_node(self) -> None:
        # A package with a graph edge pointing at it but no node of its own
        # (fastmcp), and a leaf package with no node at all (pydantic).
        for omitted in ("fastmcp", "pydantic"):
            with self.subTest(omitted=omitted):
                bad = copy.deepcopy(self.cdx)
                bad["dependencies"] = [
                    node for node in bad["dependencies"] if node["ref"] != omitted
                ]
                with self.assertRaisesRegex(ValueError, "lacks a dependency node"):
                    release_spdx.spdx_document(bad)
                with self.assertRaisesRegex(ValueError, "lacks a dependency node"):
                    self.verify(cdx=bad)

    def test_leaf_package_with_empty_node_is_accepted(self) -> None:
        self.assertIn({"ref": "pydantic", "dependsOn": []}, self.cdx["dependencies"])
        self.verify()

    def test_reject_dangling_dependency_reference(self) -> None:
        bad = copy.deepcopy(self.cdx)
        bad["dependencies"][1]["dependsOn"] = ["not-inventoried"]
        with self.assertRaisesRegex(ValueError, "invalid dependency child"):
            self.verify(cdx=bad)

    def test_reject_missing_spdx_package(self) -> None:
        bad = copy.deepcopy(self.spdx)
        bad["packages"].pop()
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            self.verify(spdx=bad)

    def test_reject_missing_relationship(self) -> None:
        bad = copy.deepcopy(self.spdx)
        bad["relationships"].pop()
        with self.assertRaisesRegex(ValueError, "dependency graph differs"):
            self.verify(spdx=bad)

    def test_reject_forged_package_identity(self) -> None:
        bad = copy.deepcopy(self.spdx)
        bad["packages"][1]["name"] = "wrong-name"
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            self.verify(spdx=bad)

    def test_reject_forged_package_version(self) -> None:
        bad = copy.deepcopy(self.spdx)
        bad["packages"][0]["versionInfo"] = "0.0.0"
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            self.verify(spdx=bad)

    def test_reject_forged_root_wheel_hash(self) -> None:
        bad = copy.deepcopy(self.spdx)
        bad["packages"][0]["checksums"][0]["checksumValue"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.verify(spdx=bad)

    def test_reject_empty_cdx_inventory_or_graph(self) -> None:
        for field in ("components", "dependencies"):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.cdx)
                bad[field] = []
                with self.assertRaises(ValueError):
                    self.verify(cdx=bad)

    def test_reject_modified_wheel_bytes(self) -> None:
        with self.wheel.open("ab") as stream:
            stream.write(b"substituted")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.verify()

    def test_reject_missing_installed_package(self) -> None:
        env = self.root / "venv"
        (env / "bin").mkdir(parents=True)
        python = env / "bin" / "python"
        python.write_text(
            "#!/bin/sh\n"
            'printf \'%s\\n\' \'[["alphafold-sovereign-mcp","1.5.5"],'
            '["fastmcp","4.0.11"]]\'\n',
            encoding="utf-8",
        )
        python.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "environment differs"):
            self.verify(environment=env)

    def pypi_metadata(self) -> dict:
        return {
            "info": {
                "name": "alphafold-sovereign-mcp",
                "version": "1.5.5",
            },
            "urls": [
                {
                    "filename": path.name,
                    "packagetype": ("bdist_wheel" if path.suffix == ".whl" else "sdist"),
                    "digests": {"sha256": release_assets.sha256(path)},
                }
                for path in (self.wheel, self.sdist)
            ],
        }

    def test_matching_pypi_pair_and_absent_version(self) -> None:
        self.assertFalse(
            release_assets.check_pypi(self.dist, "v1.5.5", None, require_present=False)
        )
        self.assertTrue(
            release_assets.check_pypi(
                self.dist,
                "v1.5.5",
                self.pypi_metadata(),
                require_present=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "not published"):
            release_assets.check_pypi(self.dist, "v1.5.5", None, require_present=True)

    def test_reject_pypi_digest_and_file_mismatch(self) -> None:
        for kind in ("digest", "filename"):
            with self.subTest(kind=kind):
                data = self.pypi_metadata()
                if kind == "digest":
                    data["urls"][0]["digests"]["sha256"] = "0" * 64
                else:
                    data["urls"][0]["filename"] = "different.whl"
                with self.assertRaises(ValueError):
                    release_assets.check_pypi(self.dist, "v1.5.5", data, require_present=True)

    def test_partial_pypi_publish_stages_only_missing_file(self) -> None:
        for remote_kind, missing in (
            ("bdist_wheel", self.sdist),
            ("sdist", self.wheel),
        ):
            with self.subTest(remote_kind=remote_kind):
                data = self.pypi_metadata()
                data["urls"] = [item for item in data["urls"] if item["packagetype"] == remote_kind]
                to_publish = release_assets.missing_pypi_distributions(
                    self.dist, "v1.5.5", data, require_present=False
                )
                self.assertEqual([path.name for path in to_publish], [missing.name])
                staging = self.root / f"stage-{remote_kind}"
                release_assets.stage_pypi_distributions(to_publish, staging)
                self.assertEqual({path.name for path in staging.iterdir()}, {missing.name})
                self.assertEqual(
                    release_assets.sha256(staging / missing.name),
                    release_assets.sha256(missing),
                )
                with self.assertRaisesRegex(ValueError, "pair incomplete"):
                    release_assets.check_pypi(self.dist, "v1.5.5", data, require_present=True)

    def test_unpublished_pypi_stages_both_and_complete_stages_neither(self) -> None:
        for name, metadata, expected in (
            ("unpublished", None, {self.wheel.name, self.sdist.name}),
            ("complete", self.pypi_metadata(), set()),
        ):
            with self.subTest(name=name):
                missing = release_assets.missing_pypi_distributions(
                    self.dist, "v1.5.5", metadata, require_present=False
                )
                stage = self.root / f"stage-{name}"
                release_assets.stage_pypi_distributions(missing, stage)
                self.assertEqual({path.name for path in stage.iterdir()}, expected)

    def test_partial_pypi_rejects_mismatches_before_staging(self) -> None:
        for changed, expected_error in (
            ("sha256", "SHA-256 mismatch"),
            ("filename", "unknown PyPI artifact"),
            ("packagetype", "incorrect PyPI artifact type"),
            ("version", "wrong PyPI project/version"),
        ):
            with self.subTest(changed=changed):
                data = self.pypi_metadata()
                data["urls"] = data["urls"][:1]
                if changed == "sha256":
                    data["urls"][0]["digests"]["sha256"] = "0" * 64
                elif changed == "filename":
                    data["urls"][0]["filename"] = "unexpected.whl"
                elif changed == "packagetype":
                    data["urls"][0]["packagetype"] = "sdist"
                else:
                    data["info"]["version"] = "9.9.9"
                with self.assertRaisesRegex(ValueError, expected_error):
                    release_assets.missing_pypi_distributions(
                        self.dist, "v1.5.5", data, require_present=False
                    )

    def test_partial_pypi_rejects_duplicates_and_preexisting_staging(self) -> None:
        data = self.pypi_metadata()
        data["urls"] = [data["urls"][0], dict(data["urls"][0])]
        with self.assertRaisesRegex(ValueError, "duplicate PyPI artifact"):
            release_assets.missing_pypi_distributions(
                self.dist, "v1.5.5", data, require_present=False
            )
        stage = self.root / "existing-staging"
        stage.mkdir()
        with self.assertRaisesRegex(ValueError, "staging path already exists"):
            release_assets.stage_pypi_distributions([self.wheel], stage)

    def test_pypi_workflow_publishes_only_verified_missing_distributions(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("--stage-missing dist-to-publish/", workflow)
        self.assertIn("packages-dir: dist-to-publish/", workflow)
        self.assertNotIn("packages-dir: dist/", workflow)
        self.assertIn("if: steps.existing.outputs.present == 'false'", workflow)

    def github_files(self) -> dict[str, Path]:
        sboms = self.root / "sboms"
        sboms.mkdir(exist_ok=True)
        (sboms / "sbom.cyclonedx.json").write_text(json.dumps(self.cdx), encoding="utf-8")
        (sboms / "sbom.spdx.json").write_text(json.dumps(self.spdx), encoding="utf-8")
        return release_assets.release_paths(self.dist, sboms)

    def test_existing_identical_github_asset_is_not_reuploaded(self) -> None:
        files = self.github_files()
        prefix = "https://github.com/smaniches/alphafold-sovereign-mcp/releases/download/v1.5.5/"
        assets = [
            {"name": name, "state": "uploaded", "browser_download_url": prefix + name}
            for name in files
        ]

        def download(url: str, dest: Path) -> None:
            dest.write_bytes(files[url.rsplit("/", 1)[-1]].read_bytes())

        missing = release_assets.check_github_assets(
            files,
            assets,
            "smaniches/alphafold-sovereign-mcp",
            "v1.5.5",
            downloader=download,
        )
        self.assertEqual(set(missing), {f"{name}.sigstore" for name in files})

    def test_reject_changed_existing_release_asset(self) -> None:
        files = self.github_files()
        name = self.wheel.name
        assets = [
            {
                "name": name,
                "state": "uploaded",
                "browser_download_url": (
                    "https://github.com/smaniches/alphafold-sovereign-mcp/"
                    f"releases/download/v1.5.5/{name}"
                ),
            }
        ]

        def changed(url: str, dest: Path) -> None:
            dest.write_bytes(b"changed bytes")

        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            release_assets.check_github_assets(
                files,
                assets,
                "smaniches/alphafold-sovereign-mcp",
                "v1.5.5",
                downloader=changed,
            )

    def test_reject_invalid_existing_sigstore_bundle(self) -> None:
        files = self.github_files()
        name = self.wheel.name + ".sigstore"
        assets = [
            {
                "name": name,
                "state": "uploaded",
                "browser_download_url": (
                    "https://github.com/smaniches/alphafold-sovereign-mcp/"
                    f"releases/download/v1.5.5/{name}"
                ),
            }
        ]

        def download(url: str, dest: Path) -> None:
            dest.write_bytes(b"invalid signature")

        def reject_signature(*args) -> None:
            raise ValueError("invalid signature")

        with self.assertRaisesRegex(ValueError, "invalid signature"):
            release_assets.check_github_assets(
                files,
                assets,
                "smaniches/alphafold-sovereign-mcp",
                "v1.5.5",
                downloader=download,
                signature_verifier=reject_signature,
            )

    def test_reject_unknown_release_asset(self) -> None:
        files = self.github_files()
        assets = [
            {
                "name": "unexpected.zip",
                "browser_download_url": (
                    "https://github.com/smaniches/alphafold-sovereign-mcp/"
                    "releases/download/v1.5.5/unexpected.zip"
                ),
            }
        ]
        with self.assertRaisesRegex(ValueError, "unknown/duplicate"):
            release_assets.check_github_assets(
                files,
                assets,
                "smaniches/alphafold-sovereign-mcp",
                "v1.5.5",
            )

    # ---- interrupted GitHub Release creation (draft recovery) ----------

    REPO = "smaniches/alphafold-sovereign-mcp"

    def release_listing(self, *, draft: bool, names=None, tag="v1.5.5") -> dict:
        files = self.github_files()
        names = list(files) if names is None else names
        return {
            "tag_name": tag,
            "draft": draft,
            "assets": [
                {
                    "name": name,
                    "state": "uploaded",
                    "browser_download_url": (
                        "https://github.com/smaniches/alphafold-sovereign-mcp/"
                        f"releases/download/{tag}/{name}"
                    ),
                }
                for name in names
            ],
        }

    def test_find_release_prefers_public_tag_and_finds_drafts(self) -> None:
        public = self.release_listing(draft=False)
        draft = self.release_listing(draft=True)

        def fetch(url: str, token=None):
            if "/releases/tags/" in url:
                return public
            return [draft]

        self.assertEqual(release_assets.find_release(self.REPO, "v1.5.5", "t", fetch=fetch), public)

        def draft_only(url: str, token=None):
            return (
                None
                if "/releases/tags/" in url
                else [
                    {"tag_name": "v1.5.4", "draft": True},
                    draft,
                ]
            )

        self.assertEqual(
            release_assets.find_release(self.REPO, "v1.5.5", "t", fetch=draft_only),
            draft,
        )
        self.assertIsNone(release_assets.find_release(self.REPO, "v9.9.9", "t", fetch=draft_only))

    def test_find_release_rejects_duplicate_drafts_and_anonymous_lookup(self) -> None:
        draft = self.release_listing(draft=True)

        def duplicated(url: str, token=None):
            return None if "/releases/tags/" in url else [draft, dict(draft)]

        with self.assertRaisesRegex(ValueError, "multiple draft"):
            release_assets.find_release(self.REPO, "v1.5.5", "t", fetch=duplicated)
        # Drafts are invisible without a token: an anonymous miss is not proof
        # that no draft exists, so recovery must not silently create a second.
        with self.assertRaisesRegex(ValueError, "token"):
            release_assets.find_release(self.REPO, "v1.5.5", None, fetch=duplicated)

    def test_draft_with_partial_assets_resumes_by_uploading_only_missing(self) -> None:
        files = self.github_files()
        present = [self.wheel.name, self.sdist.name]
        listing = self.release_listing(draft=True, names=present)
        fetched = []

        def download(location: str, dest: Path) -> None:
            fetched.append(location)
            dest.write_bytes(files[location].read_bytes())

        plan = release_assets.plan_from_release(
            files, listing, self.REPO, "v1.5.5", downloader=download
        )
        self.assertTrue(plan["exists"])
        self.assertTrue(plan["draft"])
        self.assertEqual(sorted(fetched), sorted(present))
        self.assertEqual(
            set(plan["missing"]),
            (set(files) | {f"{n}.sigstore" for n in files}) - set(present),
        )

    def test_draft_asset_bytes_and_state_are_verified(self) -> None:
        files = self.github_files()
        listing = self.release_listing(draft=True, names=[self.wheel.name])

        def tampered(location: str, dest: Path) -> None:
            dest.write_bytes(b"truncated")

        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            release_assets.plan_from_release(
                files, listing, self.REPO, "v1.5.5", downloader=tampered
            )
        listing["assets"][0]["state"] = "starter"
        with self.assertRaisesRegex(ValueError, "not fully uploaded"):
            release_assets.plan_from_release(
                files, listing, self.REPO, "v1.5.5", downloader=tampered
            )

    def test_conflicting_or_duplicate_assets_in_draft_fail_closed(self) -> None:
        files = self.github_files()
        listing = self.release_listing(draft=True, names=[self.wheel.name] * 2)
        with self.assertRaisesRegex(ValueError, "unknown/duplicate"):
            release_assets.plan_from_release(
                files,
                listing,
                self.REPO,
                "v1.5.5",
                downloader=lambda n, d: d.write_bytes(files[n].read_bytes()),
            )
        listing = self.release_listing(draft=True, names=["rogue.bin"])
        with self.assertRaisesRegex(ValueError, "unknown/duplicate"):
            release_assets.plan_from_release(
                files,
                listing,
                self.REPO,
                "v1.5.5",
                downloader=lambda n, d: d.write_bytes(b""),
            )

    def test_published_release_plan_is_not_draft_and_wrong_tag_rejected(self) -> None:
        files = self.github_files()
        listing = self.release_listing(draft=False, names=[])
        plan = release_assets.plan_from_release(
            files, listing, self.REPO, "v1.5.5", downloader=lambda n, d: None
        )
        self.assertFalse(plan["draft"])
        with self.assertRaisesRegex(ValueError, "wrong GitHub Release tag"):
            release_assets.plan_from_release(
                files,
                self.release_listing(draft=True, tag="v1.5.4"),
                self.REPO,
                "v1.5.5",
                downloader=lambda n, d: None,
            )
        plan = release_assets.plan_from_release(
            files, None, self.REPO, "v1.5.5", downloader=lambda n, d: None
        )
        self.assertEqual((plan["exists"], plan["draft"]), (False, False))

    def test_complete_draft_rerun_needs_no_uploads_only_publication(self) -> None:
        files = self.github_files()
        names = [*files, *(f"{name}.sigstore" for name in files)]
        listing = self.release_listing(draft=True, names=names)
        plan = release_assets.plan_from_release(
            files,
            listing,
            self.REPO,
            "v1.5.5",
            downloader=lambda n, d: d.write_bytes(files[n.removesuffix(".sigstore")].read_bytes()),
            signature_verifier=lambda *args: None,
        )
        self.assertEqual((plan["draft"], plan["missing"]), (True, []))

    def test_release_workflow_stages_as_draft_and_publishes_after_readback(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("gh release create", workflow)
        create = workflow[workflow.index("gh release create") :].splitlines()[0]
        self.assertIn("--draft", create)
        self.assertNotIn("--clobber", workflow)
        self.assertIn("gh release edit", workflow)
        self.assertLess(workflow.index("release-readback.json"), workflow.index("gh release edit"))
        self.assertIn("--draft=false", workflow)

    # ---- deterministic SBOM dependency resolution ----------------------

    def test_lock_pyproject_and_release_interpreter_agree(self) -> None:
        try:
            import tomllib
        except ImportError:  # pragma: no cover - interpreter older than 3.11
            self.skipTest("tomllib requires Python 3.11+")
        root = Path(__file__).resolve().parents[2]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
        self.assertEqual(lock["requires-python"], project["project"]["requires-python"])
        self_entry = next(
            package for package in lock["package"] if package["name"] == project["project"]["name"]
        )
        self.assertEqual(self_entry["version"], project["project"]["version"])
        self.assertEqual(
            {dependency["name"] for dependency in self_entry["dependencies"]},
            {
                release_spdx.normalized(re.split(r"[\s<>=!~;\[(]", spec, 1)[0])
                for spec in project["project"]["dependencies"]
            },
        )
        # The release interpreter (3.12) must lie inside the locked range.
        self.assertTrue(project["project"]["requires-python"].startswith(">=3."))
        self.assertLessEqual(int(project["project"]["requires-python"].split(".")[1]), 12)

    def test_sbom_environment_is_resolved_from_the_locked_hashes(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "generate_release_sbom.sh").read_text(
            encoding="utf-8"
        )
        code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
        self.assertIn("uv export --locked", code)
        self.assertIn("--no-dev", code)
        self.assertIn("--no-emit-project", code)
        self.assertIn("--require-hashes", code)
        # No floating resolution: every install touching the wheel or the
        # lock is dependency-free, and the lock is installed hash-verified.
        installs = [line for line in code.splitlines() if "pip install" in line]
        self.assertTrue(installs)
        for line in installs:
            self.assertIn("--no-deps", line)
        self.assertTrue(any('"$wheel"' in line for line in installs))
        self.assertIn("pip check", code)


if __name__ == "__main__":
    unittest.main()
