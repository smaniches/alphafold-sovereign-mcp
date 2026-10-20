#!/usr/bin/env python3
"""Fail-closed reconciliation of immutable PyPI and GitHub Release assets.

Existing files are never overwritten. Reuse requires matching distribution
digests, GitHub asset bytes, and Sigstore publisher identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from release_spdx import normalized, require, wheel_identity


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def distributions(dist: Path) -> dict[str, Path]:
    wheels = sorted(dist.glob("*.whl"))
    archives = sorted(dist.glob("*.tar.gz"))
    require(len(wheels) == len(archives) == 1, "expected one wheel and sdist")
    return {path.name: path for path in (*wheels, *archives)}


def package_version(tag: str) -> str:
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)(?:-(a|b|rc)(\d+))?", tag)
    require(match is not None, f"unsupported release tag {tag!r}")
    return match.group(1) + (match.group(2) or "") + (match.group(3) or "")


def request_json(url: str, token: str | None = None) -> dict | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "alphafold-sovereign-release-verifier",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise ValueError(f"publication lookup HTTP {error.code}: {url}") from error


def check_pypi(dist: Path, tag: str, metadata: dict | None, require_present: bool) -> bool:
    files = distributions(dist)
    (name, version), _ = wheel_identity(dist)
    expected_version = package_version(tag)
    require(
        (name, version) == ("alphafold-sovereign-mcp", expected_version),
        "tag/version does not match built wheel",
    )
    sdist = next(filename for filename in files if filename.endswith(".tar.gz"))
    stem = sdist.removesuffix(".tar.gz")
    distribution, separator, published_version = stem.rpartition("-")
    require(
        bool(separator) and normalized(distribution) == name and published_version == version,
        "sdist filename does not match wheel identity",
    )
    if metadata is None:
        require(not require_present, "expected PyPI release is not published")
        return False
    require(isinstance(metadata, dict), "invalid PyPI response")
    info = metadata.get("info", {})
    require(
        normalized(info.get("name", "")) == name and info.get("version") == version,
        "wrong PyPI project/version",
    )
    urls = metadata.get("urls")
    require(
        isinstance(urls, list) and len(urls) == 2,
        "PyPI must contain exactly one wheel and one sdist",
    )
    remote: dict[str, str] = {}
    categories: set[str] = set()
    for item in urls:
        require(isinstance(item, dict), "invalid PyPI artifact")
        filename, category = item.get("filename"), item.get("packagetype")
        require(
            isinstance(filename, str) and category in ("bdist_wheel", "sdist"),
            "unexpected PyPI artifact",
        )
        require(filename not in remote, "duplicate PyPI artifact")
        digests = item.get("digests")
        require(isinstance(digests, dict), "missing PyPI digest")
        remote[filename] = digests.get("sha256")
        categories.add(category)
    require(
        categories == {"bdist_wheel", "sdist"},
        "PyPI wheel/sdist pair incomplete",
    )
    require(remote.keys() == files.keys(), "PyPI filename mismatch")
    for filename, path in files.items():
        require(
            remote[filename] == sha256(path),
            f"PyPI SHA-256 mismatch: {filename}",
        )
    return True


def release_paths(dist: Path, sboms: Path) -> dict[str, Path]:
    files = distributions(dist)
    for name in ("sbom.cyclonedx.json", "sbom.spdx.json"):
        path = sboms / name
        require(path.is_file(), f"missing release SBOM: {path}")
        files[name] = path
    return files


def download_asset(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "alphafold-sovereign-release-verifier"},
    )
    # Browser URLs are public. Never attach a GitHub API token to a CDN.
    with (
        urllib.request.urlopen(request, timeout=60) as source,
        destination.open("wb") as output,
    ):
        while chunk := source.read(1 << 20):
            output.write(chunk)


def verify_signature(bundle: Path, artifact: Path, repo: str, tag: str) -> None:
    identity = f"https://github.com/{repo}/.github/workflows/release.yml@refs/tags/{tag}"
    command = [
        "cosign",
        "verify-blob",
        "--bundle",
        str(bundle),
        "--certificate-oidc-issuer",
        "https://token.actions.githubusercontent.com",
        "--certificate-identity",
        identity,
        str(artifact),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    require(
        result.returncode == 0,
        f"existing Sigstore bundle fails verification: {artifact.name}",
    )


def check_github_assets(
    files: dict[str, Path],
    assets: list[dict],
    repo: str,
    tag: str,
    *,
    downloader=None,
    signature_verifier=None,
) -> list[str]:
    """Verify all existing assets before any upload or signing."""
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) is not None,
        "invalid repository",
    )
    require(
        re.fullmatch(r"v\d+\.\d+\.\d+(?:-(?:a|b|rc)\d+)?", tag) is not None,
        "invalid release tag",
    )
    require(isinstance(assets, list), "invalid release asset list")
    expected = {*files, *(f"{name}.sigstore" for name in files)}
    seen: set[str] = set()
    missing = set(expected)
    if downloader is None:
        downloader = download_asset
    if signature_verifier is None:
        signature_verifier = verify_signature
    url_prefix = f"https://github.com/{repo}/releases/download/{tag}/"
    for asset in assets:
        require(isinstance(asset, dict), "invalid GitHub asset")
        name = asset.get("name")
        url = asset.get("browser_download_url")
        require(
            isinstance(name, str) and name in expected and name not in seen,
            f"unknown/duplicate GitHub Release asset: {name!r}",
        )
        require(
            isinstance(url, str) and url == url_prefix + name,
            f"wrong release asset location: {name!r}",
        )
        seen.add(name)
        missing.remove(name)
        with tempfile.TemporaryDirectory(prefix="release-readback-") as temp:
            downloaded = Path(temp) / "asset"
            downloader(url, downloaded)
            require(downloaded.is_file(), f"failed downloading {name}")
            base = name.removesuffix(".sigstore")
            if name.endswith(".sigstore"):
                signature_verifier(downloaded, files[base], repo, tag)
            else:
                require(
                    sha256(downloaded) == sha256(files[name]),
                    f"GitHub asset SHA-256 mismatch: {name}",
                )
    # Race protection: later upload uses no --clobber, so new collisions fail.
    return sorted(missing)


def plan_github(dist: Path, sboms: Path, tag: str, repo: str) -> dict:
    files = release_paths(dist, sboms)
    response = request_json(
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        os.environ.get("GH_TOKEN"),
    )
    exists = response is not None
    if exists:
        require(
            isinstance(response, dict) and response.get("tag_name") == tag,
            "wrong GitHub Release tag",
        )
        assets = response.get("assets")
    else:
        assets = []
    missing = check_github_assets(files, assets, repo, tag)
    return {
        "exists": exists,
        "missing": missing,
        "tag": tag,
        "repo": repo,
    }


def paths_from_plan(plan: dict, files: dict[str, Path]) -> list[Path]:
    names = plan.get("missing")
    require(
        isinstance(names, list) and len(names) == len(set(names)),
        "invalid release plan",
    )
    expected = {*files, *(f"{name}.sigstore" for name in files)}
    require(set(names) <= expected, "unexpected release plan asset")
    paths = []
    for name in names:
        if name.endswith(".sigstore"):
            path = Path(f"{files[name.removesuffix('.sigstore')]}.sigstore")
        else:
            path = files[name]
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    pypi = actions.add_parser("pypi")
    pypi.add_argument("dist", type=Path)
    pypi.add_argument("tag")
    pypi.add_argument("--require-present", action="store_true")
    pypi.add_argument("--github-output", type=Path)
    github = actions.add_parser("github")
    github.add_argument("dist", type=Path)
    github.add_argument("sboms", type=Path)
    github.add_argument("tag")
    github.add_argument("repo")
    github.add_argument("plan", type=Path)
    sign = actions.add_parser("sign")
    sign.add_argument("dist", type=Path)
    sign.add_argument("sboms", type=Path)
    sign.add_argument("plan", type=Path)
    listing = actions.add_parser("paths")
    listing.add_argument("dist", type=Path)
    listing.add_argument("sboms", type=Path)
    listing.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "pypi":
            version = package_version(args.tag)
            url = f"https://pypi.org/pypi/alphafold-sovereign-mcp/{version}/json"
            # An already-published release must match immediately.
            # Only post-upload 404 propagation is retried.
            for attempt in range(12 if args.require_present else 1):
                metadata = request_json(url)
                if metadata is not None or not args.require_present:
                    break
                if attempt < 11:
                    time.sleep(10)
            present = check_pypi(args.dist, args.tag, metadata, args.require_present)
            if args.github_output is not None:
                with args.github_output.open("a", encoding="utf-8") as output:
                    output.write(f"present={str(present).lower()}\n")
            print(f"PyPI reconciliation PASS: {version}, present={present}")
        elif args.action == "github":
            plan = plan_github(args.dist, args.sboms, args.tag, args.repo)
            args.plan.write_text(
                json.dumps(plan, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"GitHub Release reconciliation PASS: {plan}")
        else:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            files = release_paths(args.dist, args.sboms)
            paths = paths_from_plan(plan, files)
            if args.action == "paths":
                for path in paths:
                    require(path.is_file(), f"missing release asset: {path}")
                    print(path)
            else:
                for path in paths:
                    if not str(path).endswith(".sigstore"):
                        continue
                    base = Path(str(path).removesuffix(".sigstore"))
                    subprocess.run(
                        [
                            "cosign",
                            "sign-blob",
                            "--yes",
                            str(base),
                            "--bundle",
                            str(path),
                        ],
                        check=True,
                    )
                print("Only missing Sigstore bundles signed")
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        urllib.error.URLError,
        subprocess.SubprocessError,
    ) as error:
        print(
            f"Release asset reconciliation FAILED: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
