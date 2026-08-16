import os

import pytest

# 平台库（main 工作树 data/factorlab.duckdb，只读引用——M4a 起唯一数据源；
# 旧只读库（date/code 列）已废弃：无 stock_basic/adj_factor 等平台表）
REAL_DB = "C:/Users/ThinkPad/quant-platform/data/factorlab.duckdb"


@pytest.fixture
def real_db_path():
    if not os.path.exists(REAL_DB):
        pytest.skip(f"真实数据库不存在: {REAL_DB}")
    return REAL_DB
