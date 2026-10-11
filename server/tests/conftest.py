import os
import shutil
from pathlib import Path

import pytest

from app.settings import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "config"


@pytest.fixture
def config_dir() -> Path:
    return CONFIG_DIR


@pytest.fixture
def model_copy(tmp_path: Path) -> Path:
    """A writable copy of config/model for tests that break the configuration on purpose."""
    target = tmp_path / "model"
    shutil.copytree(CONFIG_DIR / "model", target)
    return target


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; database tests need a PostgreSQL test database")
    return url
