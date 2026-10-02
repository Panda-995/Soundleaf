"""Package public deployment files from a fixed allowlist, without data or secrets."""

import importlib.util
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_version", root / "scripts/verify-version.py")
versions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(versions)
version = versions.verify(root)
output = root / "release-artifacts" / version
output.mkdir(parents=True, exist_ok=True)
target = output / f"Soundleaf-{version}-deploy.zip"
files = {
    "compose.release.yaml": "compose.yaml",
    ".env.example": ".env.example",
    "README.md": "README.md",
    "CHANGELOG.md": "CHANGELOG.md",
    "LICENSE": "LICENSE",
    "ugreen/README.md": "ugreen/README.md",
    "ugreen/soundleaf-app/project.yaml": "ugreen/project.yaml",
    "frontend/public/privacy-policy.html": "privacy-policy.html",
    "docs/发布说明-v1.2.0.md": "RELEASE.md",
}
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for source, destination in files.items():
        archive.write(root / source, destination)
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert set(archive.namelist()) == set(files.values())
print(target)
