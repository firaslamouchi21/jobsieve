import os
import sys

os.environ.setdefault("MOCK_SEARCH", "true")
os.environ.setdefault("USE_PLAYWRIGHT", "false")
os.environ.setdefault("REQUEST_DELAY_SECONDS", "0")

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("API_TOKEN", raising=False)
