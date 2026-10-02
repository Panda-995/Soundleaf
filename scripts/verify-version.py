"""Check release metadata against pyproject.toml and export the version for CI."""

import argparse
import json
import os
import re
import tomllib
from pathlib import Path


def verify(root: Path, release_tag: str = "") -> str:
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[.-][A-Za-z0-9.-]+)?", version):
        raise ValueError("Invalid application version")
    for filename in ("frontend/package.json", "frontend/package-lock.json"):
        data = json.loads((root / filename).read_text(encoding="utf-8"))
        if data["version"] != version or data.get("packages", {}).get("", {}).get("version", version) != version:
            raise ValueError(f"{filename}: version must be {version}")
    metadata = (root / "ugreen/soundleaf-app/project.yaml").read_text(encoding="utf-8")
    if not re.search(rf"^version:\s*{re.escape(version)}\s*$", metadata, re.MULTILINE):
        raise ValueError(f"UGOS package version must be {version}")
    compose = (root / "ugreen/soundleaf-app/rootfs_common/docker-compose.yaml").read_text(encoding="utf-8")
    if not re.search(rf"^\s*image:\s*ghcr\.io/panda-995/soundleaf:{re.escape(version)}\s*$", compose, re.MULTILINE):
        raise ValueError(f"UGOS image version must be {version}")
    deployment = (root / "compose.release.yaml").read_text(encoding="utf-8")
    if not re.search(rf"^\s*image:\s*ghcr\.io/panda-995/soundleaf:{re.escape(version)}\s*$", deployment, re.MULTILINE):
        raise ValueError(f"Deployment image version must be {version}")
    if release_tag and release_tag != f"v{version}":
        raise ValueError(f"Release tag must be v{version}")
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--release-tag", default="")
    args = parser.parse_args()
    tag = args.release_tag
    if not tag and os.environ.get("GITHUB_REF_TYPE") == "tag":
        tag = os.environ.get("GITHUB_REF_NAME", "")
    version = verify(Path(__file__).resolve().parents[1], tag)
    if args.github_env:
        with args.github_env.open("a", encoding="utf-8") as stream:
            stream.write(f"APP_VERSION={version}\n")
    print(version)
