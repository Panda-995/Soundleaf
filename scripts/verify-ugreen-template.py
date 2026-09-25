"""Check generated package metadata and legacy/custom mounts before publishing."""
import json
from pathlib import Path
import re
import subprocess
import sys

import yaml

root = Path(__file__).resolve().parents[1]
project = (root / "ugreen/soundleaf-app/project.yaml").read_text(encoding="utf-8")
version = re.search(r'^version: "?([^"\n]+)"?', project, re.M).group(1)
image = f"ghcr.io/panda-995/soundleaf:{version}"

package = Path(sys.argv[1])
config = json.loads((package / "config.json").read_text(encoding="utf-8"))
assert config["allowAddAccessPath"] is True
assert config["baseAccessInfo"]["portInfo"]["port"] == "8780"
params = {p["key"]: p for p in config["installParameters"]["list"]}
assert set(params) == {"DATA_PATH"}, sorted(params)
data = params["DATA_PATH"]
assert data["paramType"] == 1 and not data["multi"]
assert not data["isRequired"] and data["changeable"]
names = {p["langName"]: p["name"] for p in data["i18ns"]}
assert names == {"en-US": "Data folder", "zh-CN": "数据文件夹"}, names
zh = next(x["description"] for x in config["i18n"] if x["langName"] == "zh-CN")
assert len(re.findall(r"[\u4e00-\u9fff]", zh)) >= 100
go = sys.argv[2] if len(sys.argv) > 2 else "go"
rendered = subprocess.check_output([
    go, "run", str(root / "scripts/render-ugreen-template.go"),
    str(package / "docker-compose.tmpl"),
], encoding="utf-8")
for case in json.loads(rendered):
    service = yaml.safe_load(case["compose"])["services"]["soundleaf"]
    mounts = service["volumes"]
    assert len(mounts) == 1, (case["name"], mounts)
    mount = mounts[0]
    if isinstance(mount, str):
        source, target = mount.rsplit(":", 1)
    else:
        assert mount["type"] == "bind"
        source, target = mount["source"], mount["target"]
    assert source == case["source"] and target == "/data", case
    assert service["image"] == image
    assert service["ports"] == ["8780:8780"]
    assert service["environment"]["COOKIE_SECURE"] == "false"
    assert service["restart"] == "always"
    print(f"PASS {case['name']}: exactly one correct data mount")
print(f"PASS bilingual installer metadata, optional folder picker and {image} pinning")
