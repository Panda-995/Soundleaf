import importlib.util
import json
import shutil
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_version", ROOT / "scripts/verify-version.py")
version_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version_module)


def test_release_metadata_matches_source_and_tag():
    source = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert version_module.verify(ROOT, "v" + source) == source
    with pytest.raises(ValueError, match="Release tag"):
        version_module.verify(ROOT, "v0.0.0-invalid")


def test_version_gate_rejects_lockfile_drift(tmp_path):
    for filename in (
        "pyproject.toml", "compose.release.yaml", "frontend/package.json", "frontend/package-lock.json",
        "ugreen/soundleaf-app/project.yaml", "ugreen/soundleaf-app/rootfs_common/docker-compose.yaml",
    ):
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / filename, target)
    lock = tmp_path / "frontend/package-lock.json"
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["packages"][""]["version"] = "0.0.0"
    lock.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="package-lock"):
        version_module.verify(tmp_path)
