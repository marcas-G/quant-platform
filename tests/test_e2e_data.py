import pytest

from factorlab.config import settings
from factorlab.data.fetcher import TeaJoinClient, TeaJoinError
from factorlab.data.platform_db import PlatformDB
from factorlab.data.rebuild import assess_sparsity, build_final_db

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_client():
    if not settings.teajoin_token:
        pytest.skip("teajoin token 未配置（FACTORLAB_TEAJOIN_TOKEN）")
    client = TeaJoinClient(token=settings.teajoin_token)
    try:
        client.fetch("daily", {"trade_date": "20240102"}, fields=["trade_date"])
    except TeaJoinError as exc:
        pytest.skip(f"teajoin 数据源不可用（如 token 到期）：{exc}")
    return client


def test_live_fetch_daily(live_client, tmp_path):
    df = live_client.fetch("daily", {"trade_date": "20240102"}, fields=["trade_date", "ts_code", "close"])
    assert df.height > 3000  # 全市场单日 3000+ 只


def test_live_sparsity_pipeline(live_client, tmp_path):
    db = PlatformDB(tmp_path / "staging.duckdb")
    for table in ("daily", "daily_basic", "adj_factor"):
        df = live_client.fetch(table, {"trade_date": "20240102"})
        if df.height:
            db.upsert(table, df, keys=["trade_date", "ts_code"])
    assert set(db.list_tables()) >= {"daily"}
    sparsity = assess_sparsity(db)
    assert "null_ratio" in sparsity["daily"]["close"]
    result = build_final_db(db, tmp_path / "final.duckdb")
    assert "daily" in result["tables"]
