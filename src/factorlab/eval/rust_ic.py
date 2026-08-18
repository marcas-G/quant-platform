from __future__ import annotations

import polars as pl

from factorlab.eval.alignment import align_weekly


def evaluate_factor_weekly(
    panel: pl.DataFrame,
    factor_name: str,
    direction: int,
    target: str = "forward_return_5d",
    weekly: pl.DataFrame | None = None,
) -> dict:
    """周频评估：日频面板 → 周频对齐 → quant_core.evaluate_factor。

    内部传给 quant_core 的 factor 恒为 "_factor"（其内部列名约定，文档未记载）；
    factor_name 仅作显示名回填到结果的 factor_name 字段。

    - 列检查先于周频对齐：缺列时抛 ValueError（不依赖 align_weekly 的 dtype 错误）。
    - signal/target 为 null 的行在桥接层过滤——quant_core 拒绝 None
      （实测 TypeError: must be real number）；停牌补全行与尾部无未来数据的
      forward 行均属此列，不会进入评估。NaN 不属 null，quant_core 容忍（实测）。
    - 空面板（列齐全）直接透传，quant_core 返回全 nan 结构（实测不崩溃）。
    - direction 原样透传 int（约定 1/-1；0 实测按 -1 处理，属 quant_core 内部语义）。
    - weekly：调用方已对齐的周频面板（如 CLI 的 align_weekly 结果）——重复对齐
      大面板（千万行）在低内存机器上 segfault，复用避免。
    """
    import quant_core

    required = {"date", "code", "signal", target}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"评估面板缺少列: {sorted(missing)}")

    weekly = align_weekly(panel) if weekly is None else weekly
    weekly = weekly.filter(pl.col("signal").is_not_null() & pl.col(target).is_not_null())

    dates = weekly["date"].dt.strftime("%Y-%m-%d").to_list()
    codes = weekly["code"].to_list()
    signals = weekly["signal"].to_list()
    fwd = weekly[target].to_list()
    result = quant_core.evaluate_factor(dates, codes, signals, fwd, "_factor", int(direction))
    result["factor_name"] = factor_name
    return result
