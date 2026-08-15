import polars as pl
from expr_codegen import codegen_exec

from factorlab.engine.partitions import reject_future_shifts, validate_partition_calls
from factorlab.factor.ast_gate import validate_formula
from factorlab.ops.platform_ops import expand_platform_macros, register_platform_ops
from factorlab.ops.polars_ta_wrappers import register_polars_ta_ops


def compute_formula(
    df: pl.DataFrame,
    formula: str,
    asset: str = "code",
    date: str = "date",
) -> pl.DataFrame:
    validate_formula(formula)
    formula = expand_platform_macros(formula)  # 薄封装 → ts_ 表达式，保证按 asset 分区
    register_polars_ta_ops()  # 幂等；保证分区校验能识别 ts_/cs_/ta_ 算子
    register_platform_ops()
    validate_partition_calls(formula)
    reject_future_shifts(formula)
    result = codegen_exec(
        df.lazy(),
        formula,
        over_null="partition_by",
        style="polars",
        date=date,
        asset=asset,
    ).collect()
    if "signal" not in result.columns:
        raise ValueError("因子脚本必须定义输出列 signal")
    return result.select([date, asset, "signal"]).sort([date, asset])
