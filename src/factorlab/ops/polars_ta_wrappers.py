"""Register polars_ta operator families (wq / ta / tdx) into the operator registry."""

from polars_ta.prefix import ta, tdx, wq

from factorlab.ops.registry import factor_op


_WQ_TS = (
    "ts_delay", "ts_delta", "ts_mean", "ts_std_dev", "ts_sum", "ts_product",
    "ts_min", "ts_max", "ts_median", "ts_rank", "ts_zscore",
    "ts_corr", "ts_covariance", "ts_skewness", "ts_kurtosis",
)

_WQ_CS = (
    "cs_rank", "cs_zscore", "cs_demean", "cs_scale", "cs_quantile",
    "cs_mad_zscore",
)

_TA_NAMES = ("ts_RSI", "ts_ATR", "ts_MACD", "ts_WILLR", "ts_TRIX")
_TDX_NAMES = ("ts_BIAS", "ts_KDJ", "ts_BOLL", "ts_RSV")

# polars_ta 0.5.17 变更：cs_regression_resid 更名为 cs_resid；CCI 移入 tdx 族。
_WQ_ALIASES = {"cs_regression_resid": wq.cs_resid}
_TA_ALIASES = {"ts_CCI": tdx.ts_CCI}


def register_polars_ta_ops() -> None:
    for name in _WQ_TS:
        factor_op(name, kind="ts", version="0.1.0")(getattr(wq, name))
    for name in _WQ_CS:
        factor_op(name, kind="cs", version="0.1.0")(getattr(wq, name))
    for name, func in _WQ_ALIASES.items():
        factor_op(name, kind="cs", version="0.1.0")(func)
    for name in _TA_NAMES:
        factor_op(name, kind="ta", version="0.1.0")(getattr(ta, name))
    for name, func in _TA_ALIASES.items():
        factor_op(name, kind="ta", version="0.1.0")(func)
    for name in _TDX_NAMES:
        factor_op(name, kind="ta", version="0.1.0")(getattr(tdx, name))
