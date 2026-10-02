import importlib.util
from pathlib import Path


def test_v1_1_0_data_upgrade(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("verify_upgrade", root / "scripts/verify-upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify(tmp_path / "upgrade", root / "tests/fixtures/store_v1_1_0.py")
