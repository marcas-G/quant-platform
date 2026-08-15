import os

import pytest

REAL_DB = "C:/Users/ThinkPad/quant-data/quant.duckdb"


@pytest.fixture
def real_db_path():
    if not os.path.exists(REAL_DB):
        pytest.skip(f"真实数据库不存在: {REAL_DB}")
    return REAL_DB
