# FactorLab M1 平台骨架实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `factorlab` 项目骨架，实现 YAML Spec 校验、因子脚本 AST 白名单、算子插件注册，以及一条最小 `expr_codegen` 因子计算路径，并暴露 `lint` 和 `op` CLI。

**Architecture:** 采用 `src/factorlab` 包结构；`expr_codegen` 负责把受限 Python 因子块转成 Polars 执行图，`polars_ta` 提供算子，平台只做 Spec 模型、AST 安全门、算子注册与 CLI 编排。

**Tech Stack:** Python 3.13、Pydantic v2、Typer、Polars、expr_codegen、polars_ta、pytest。

**Spec:** `docs/superpowers/specs/2026-08-15-factor-dsl-platform-design.md`

## Global Constraints

- Python 必须为 3.13；包结构必须使用 `src/factorlab`。
- 依赖最低版本：`polars>=1.38`、`duckdb>=1.5`、`pyarrow>=24`、`pydantic>=2.12`、`expr-codegen>=0.16.6`、`polars-ta>=0.5.17`、`typer>=0.27`、`rich>=14`、`psutil>=7.2`。
- 目标机器约 16 GB 物理内存且无页面文件；本阶段只处理小样本测试，不加载全 A 数据。
- 因子脚本默认输出列为 `signal`；以 `_` 开头的变量视为中间变量。
- 所有测试用 `pytest`，配置 `pythonpath = ["src"]`。
- 任何实现步骤前先写失败测试，再写最小实现，最后运行测试并提交。
- 不修改 `C:\Users\ThinkPad\quant-data` 下任何文件。

## File Structure

- `pyproject.toml`：项目元数据、依赖、`factorlab` 命令入口、pytest 配置。
- `src/factorlab/__init__.py`：包版本。
- `src/factorlab/config.py`：Pydantic Settings，路径、teajoin、默认内存/分块配置。
- `src/factorlab/spec.py`：YAML Spec 数据模型与校验。
- `src/factorlab/factor/ast_gate.py`：因子脚本 AST 白名单。
- `src/factorlab/factor/errors.py`：DSL/校验错误。
- `src/factorlab/ops/registry.py`：`factor_op` 装饰器、别名、查询。
- `src/factorlab/ops/plugins.py`：用户插件目录、增删、发现加载。
- `src/factorlab/engine/compute.py`：最小因子计算适配器。
- `src/factorlab/cli/main.py`：Typer CLI。

---

### Task 1: 项目骨架与 CLI smoke

**Files:**
- Create: `pyproject.toml`
- Create: `src/factorlab/__init__.py`
- Create: `src/factorlab/config.py`
- Create: `src/factorlab/cli/__init__.py`
- Create: `src/factorlab/cli/main.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `factorlab.__version__ == "0.1.0"`；`factorlab.config.settings`；`factorlab.cli.main.app`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from factorlab import __version__
from factorlab.cli.main import app


runner = CliRunner()


def test_version_command_prints_package_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_version_command_prints_package_version -v`
Expected: FAIL，原因是 `factorlab` 包或 `app` 尚不存在。

- [ ] **Step 3: Write minimal implementation**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "factorlab"
version = "0.1.0"
description = "Personal factor DSL computation platform"
requires-python = ">=3.13"
dependencies = [
    "polars>=1.38",
    "duckdb>=1.5",
    "pyarrow>=24",
    "pyyaml>=6",
    "pydantic>=2.12",
    "pydantic-settings>=2.14",
    "expr-codegen>=0.16.6",
    "polars-ta>=0.5.17",
    "typer>=0.27",
    "rich>=14",
    "fastapi>=0.136",
    "uvicorn>=0.45",
    "jinja2>=3.1",
    "plotly>=6.7",
    "requests>=2.32",
    "psutil>=7.2",
]

[project.optional-dependencies]
talib = ["TA-Lib>=0.7.1"]
dev = ["pytest>=8", "pytest-cov>=6"]

[project.scripts]
factorlab = "factorlab.cli.main:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Create `src/factorlab/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/factorlab/config.py`:

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FACTORLAB_",
        env_file=".env",
        extra="ignore",
    )

    quant_db: Path = Path("C:/Users/ThinkPad/quant-data/quant.duckdb")
    plugin_dir: Path = Path.home() / ".factorlab" / "plugins"
    teajoin_base_url: str = "https://teajoin.com/g"
    teajoin_token: str = ""
    default_max_memory: str = "4GB"
    default_chunk_size: int = 1000
    use_float32: bool = True


settings = Settings()
settings.plugin_dir.mkdir(parents=True, exist_ok=True)
```

Create `src/factorlab/cli/__init__.py`:

```python
```

Create `src/factorlab/cli/main.py`:

```python
import typer

from factorlab import __version__


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """factorlab 因子 DSL 计算平台"""


@app.command()
def version() -> None:
    typer.echo(__version__)
```

- [ ] **Step 4: Install editable and run test**

Run:
```powershell
python -m pip install -e .
pytest tests/test_cli.py::test_version_command_prints_package_version -v
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/factorlab tests/test_cli.py
git commit -m "chore: scaffold factorlab package and CLI entrypoint"
```

---

### Task 2: YAML Spec 模型与校验

**Files:**
- Create: `src/factorlab/spec.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Produces: `FactorSpec`、`UniverseSpec`、`DateRange`、`OperatorMacro`、`SubFactorSpec`、`CombineSpec`、`load_spec(path)`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_spec.py`:

```python
import pytest
import yaml

from factorlab.spec import FactorSpec, load_spec


def make_spec(tmp_path, **overrides):
    data = {
        "name": "demo_factor",
        "category": "custom",
        "direction": 1,
        "universe": {"codes": ["000001.SZ", "600519.SH"]},
        "date": {"start": "2020-01-01", "end": "2021-01-01"},
        "formula": "signal = close / open - 1",
    }
    data.update(overrides)
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_load_valid_spec(tmp_path):
    spec = load_spec(make_spec(tmp_path))
    assert spec.name == "demo_factor"
    assert spec.universe.codes == ["000001.SZ", "600519.SH"]


def test_rejects_missing_direction(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(tmp_path, direction=None))


def test_rejects_universe_both_codes_and_rules(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(tmp_path, universe={"codes": ["000001.SZ"], "rules": {"exclude_st": True}}))


def test_rejects_formula_and_factors_together(tmp_path):
    with pytest.raises(ValueError):
        load_spec(make_spec(
            tmp_path,
            factors=[{"name": "a", "formula": "signal = close"}],
            combine={"method": "equal_weight"},
        ))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_spec.py -v`
Expected: FAIL，原因是 `factorlab.spec` 尚不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/spec.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
PROCESS_PATTERN = r"^[a-z_][a-z0-9_]*(\(.*\))?$"


class UniverseSpec(BaseModel):
    codes: list[str] | None = None
    rules: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one_universe(self) -> "UniverseSpec":
        if (self.codes is None) == (self.rules is None):
            raise ValueError("universe.codes 与 universe.rules 必须二选一")
        return self


class DateRange(BaseModel):
    start: str | None = None
    end: str | None = None


class OperatorMacro(BaseModel):
    params: list[str] = Field(default_factory=list)
    formula: str


class SubFactorSpec(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    formula: str
    process: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_process_names(self) -> "SubFactorSpec":
        for item in self.process:
            if not __import__("re").match(PROCESS_PATTERN, item):
                raise ValueError(f"非法 process 项: {item}")
        return self


class CombineSpec(BaseModel):
    method: Literal["ic_weight", "equal_weight", "weight_sum"]
    weights: list[float] | None = None


class FactorSpec(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    category: Literal["ohlcv_core", "ohlcv_retail", "valuation", "custom"]
    direction: Literal[1, -1]
    description: str = ""
    universe: UniverseSpec
    date: DateRange = Field(default_factory=DateRange)
    target: Literal["forward_return_5d", "forward_return_20d"] = "forward_return_5d"
    process: list[str] = Field(default_factory=list)
    operators: dict[str, OperatorMacro] = Field(default_factory=dict)
    formula: str | None = None
    factors: list[SubFactorSpec] | None = None
    combine: CombineSpec | None = None

    @model_validator(mode="after")
    def _validate_script(self) -> "FactorSpec":
        if (self.formula is None) == (self.factors is None):
            raise ValueError("formula 与 factors 必须二选一")
        if self.factors is not None and self.combine is None:
            raise ValueError("使用 factors 时必须提供 combine")
        for item in self.process:
            if not __import__("re").match(PROCESS_PATTERN, item):
                raise ValueError(f"非法 process 项: {item}")
        return self


def load_spec(path: str | Path) -> FactorSpec:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FactorSpec.model_validate(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_spec.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/spec.py tests/test_spec.py
git commit -m "feat: add YAML factor spec model and validation"
```

---

### Task 3: 因子脚本 AST 白名单

**Files:**
- Create: `src/factorlab/factor/__init__.py`
- Create: `src/factorlab/factor/errors.py`
- Create: `src/factorlab/factor/ast_gate.py`
- Test: `tests/test_ast_gate.py`

**Interfaces:**
- Produces: `FactorDSLError(message, line, col)`；`validate_formula(source: str) -> None`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_ast_gate.py`:

```python
import pytest

from factorlab.factor.ast_gate import validate_formula
from factorlab.factor.errors import FactorDSLError


def test_allows_def_import_assignment_and_ternary():
    source = '''
from polars_ta.prefix.wq import ts_delay, ts_mean

def mom(x, n):
    return ts_delay(x, n) / ts_delay(x, 2 * n) - 1

_m = ts_mean(close, 20)
signal = _m if _m > 0 else -_m
'''
    validate_formula(source)


def test_rejects_for_loop():
    with pytest.raises(FactorDSLError):
        validate_formula("for i in range(10):\n    pass\n")


def test_rejects_os_import():
    with pytest.raises(FactorDSLError):
        validate_formula("import os\nsignal = close\n")


def test_rejects_eval_call():
    with pytest.raises(FactorDSLError):
        validate_formula("signal = eval('close')\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ast_gate.py -v`
Expected: FAIL，原因是 `factorlab.factor.ast_gate` 尚不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/factor/__init__.py`:

```python
```

Create `src/factorlab/factor/errors.py`:

```python
class FactorDSLError(Exception):
    def __init__(self, message: str, line: int | None = None, col: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col

    def __str__(self) -> str:
        if self.line is None:
            return self.message
        location = f"{self.line}"
        if self.col is not None:
            location += f":{self.col}"
        return f"{location}: {self.message}"
```

Create `src/factorlab/factor/ast_gate.py`:

```python
from __future__ import annotations

import ast

from factorlab.factor.errors import FactorDSLError


ALLOWED_NODES = {
    ast.Module,
    ast.Import,
    ast.ImportFrom,
    ast.alias,
    ast.FunctionDef,
    ast.ClassDef,
    ast.Assign,
    ast.AnnAssign,
    ast.Expr,
    ast.Return,
    ast.arguments,
    ast.arg,
    ast.Name,
    ast.Constant,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Call,
    ast.Attribute,
    ast.IfExp,
    ast.Subscript,
    ast.Tuple,
    ast.List,
    ast.Load,
    ast.Store,
    ast.keyword,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
}

ALLOWED_IMPORT_PREFIXES = (
    "polars",
    "polars_ta.prefix.",
    "factorlab.ops.",
)

FORBIDDEN_CALLS = {"eval", "exec", "open", "compile", "__import__"}


def _is_allowed_import(module: str | None) -> bool:
    return module is not None and module.startswith(ALLOWED_IMPORT_PREFIXES)


def validate_formula(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise FactorDSLError(f"语法错误: {exc.msg}", exc.lineno, exc.offset) from exc

    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            raise FactorDSLError(
                f"不支持的语法节点: {type(node).__name__}",
                getattr(node, "lineno", None),
                getattr(node, "col_offset", None),
            )

        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_allowed_import(alias.name):
                    raise FactorDSLError(
                        f"禁止导入模块: {alias.name}",
                        node.lineno,
                        node.col_offset,
                    )

        if isinstance(node, ast.ImportFrom):
            if not _is_allowed_import(node.module):
                raise FactorDSLError(
                    f"禁止导入模块: {node.module}",
                    node.lineno,
                    node.col_offset,
                )

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                raise FactorDSLError(
                    f"禁止调用函数: {node.func.id}",
                    node.lineno,
                    node.col_offset,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ast_gate.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/factor tests/test_ast_gate.py
git commit -m "feat: add AST whitelist for factor formula code"
```

---

### Task 4: 算子注册表与用户插件管理

**Files:**
- Create: `src/factorlab/ops/__init__.py`
- Create: `src/factorlab/ops/registry.py`
- Create: `src/factorlab/ops/plugins.py`
- Test: `tests/test_ops.py`

**Interfaces:**
- Produces: `OperatorDef`、`factor_op(name, kind, version, aliases=())`、`get_op(name)`、`list_ops()`、`canonical_name(name, kind)`、`add_plugin(path, plugin_dir, force=False)`、`remove_plugin(name, plugin_dir)`、`discover_plugins(plugin_dir)`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_ops.py`:

```python
import textwrap

import polars as pl

from factorlab.ops import plugins, registry


def write_plugin(plugin_dir, name="dummy_op"):
    plugin_dir.mkdir(parents=True, exist_ok=True)
    path = plugin_dir / "my_ops.py"
    path.write_text(textwrap.dedent(f'''
        import polars as pl
        from factorlab.ops.registry import factor_op

        @factor_op("{name}", kind="ts", version="0.1.0")
        def {name}(x: pl.Expr, n: int) -> pl.Expr:
            return x.rolling_mean(window_size=n)
    '''), encoding="utf-8")
    return path


def test_add_and_list_plugin_operator(tmp_path):
    registry.reset_registry()
    plugin_dir = tmp_path / "plugins"
    plugins.add_plugin(write_plugin(plugin_dir), plugin_dir=plugin_dir)
    assert registry.get_op("dummy_op").version == "0.1.0"
    assert "ts_dummy_op" in plugins.list_enabled_operators(plugin_dir)


def test_remove_plugin_disables_operator(tmp_path):
    registry.reset_registry()
    plugin_dir = tmp_path / "plugins"
    plugins.add_plugin(write_plugin(plugin_dir), plugin_dir=plugin_dir)
    plugins.remove_plugin("dummy_op", plugin_dir=plugin_dir)
    assert "dummy_op" not in plugins.list_enabled_operators(plugin_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ops.py -v`
Expected: FAIL，原因是 `factorlab.ops` 尚不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/ops/__init__.py`:

```python
```

Create `src/factorlab/ops/registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import polars as pl


OperatorKind = Literal["el", "ts", "cs", "gp", "ta"]


@dataclass(frozen=True)
class OperatorDef:
    name: str
    kind: OperatorKind
    version: str
    func: Callable[..., pl.Expr]
    doc: str = ""


_REGISTRY: dict[str, OperatorDef] = {}
_ALIASES: dict[str, str] = {}


def reset_registry() -> None:
    _REGISTRY.clear()
    _ALIASES.clear()


def factor_op(
    name: str,
    kind: OperatorKind,
    version: str,
    aliases: tuple[str, ...] = (),
) -> Callable:
    def decorator(func: Callable[..., pl.Expr]) -> Callable[..., pl.Expr]:
        op = OperatorDef(
            name=name,
            kind=kind,
            version=version,
            func=func,
            doc=func.__doc__ or "",
        )
        _REGISTRY[name] = op
        for alias in aliases:
            _ALIASES[alias] = name
        return func

    return decorator


def canonical_name(name: str, kind: OperatorKind) -> str:
    prefix = {"ts": "ts_", "cs": "cs_", "gp": "gp_", "ta": "ta_"}.get(kind, "")
    return name if not prefix or name.startswith(prefix) else f"{prefix}{name}"


def get_op(name: str) -> OperatorDef:
    target = _ALIASES.get(name, name)
    try:
        return _REGISTRY[target]
    except KeyError as exc:
        raise KeyError(f"未知算子: {name}") from exc


def list_ops() -> list[OperatorDef]:
    return sorted(_REGISTRY.values(), key=lambda op: op.name)
```

Create `src/factorlab/ops/plugins.py`:

```python
from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path

from factorlab.ops import registry


MANIFEST = "manifest.json"


def _manifest_path(plugin_dir: Path) -> Path:
    return plugin_dir / MANIFEST


def _load_manifest(plugin_dir: Path) -> dict:
    path = _manifest_path(plugin_dir)
    if not path.exists():
        return {"operators": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(plugin_dir: Path, manifest: dict) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    _manifest_path(plugin_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _scan_plugin_ast(source: str) -> None:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "open", "compile", "__import__"}:
                raise ValueError(f"插件禁止调用: {node.func.id}")
        if isinstance(node, ast.Import):
            bad = [a.name for a in node.names if a.name.split(".")[0] in {"os", "sys", "subprocess", "socket", "shutil"}]
            if bad:
                raise ValueError(f"插件禁止导入: {bad}")


def _import_plugin(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(f"factorlab_plugin_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法加载插件: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def add_plugin(path: str | Path, plugin_dir: Path, force: bool = False) -> list[str]:
    source_path = Path(path)
    if not source_path.exists() or source_path.suffix != ".py":
        raise ValueError("插件路径必须存在且为 .py 文件")

    source = source_path.read_text(encoding="utf-8")
    _scan_plugin_ast(source)

    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(plugin_dir)
    existing = {item["name"] for item in manifest["operators"]}

    before = {op.name for op in registry.list_ops()}
    _import_plugin(source_path)
    new_names = {op.name for op in registry.list_ops()} - before
    if not new_names:
        raise ValueError("插件未注册任何新算子")

    conflicts = new_names & existing
    if conflicts and not force:
        raise ValueError(f"算子已存在: {sorted(conflicts)}，使用 --force 覆盖")

    dest = plugin_dir / source_path.name
    shutil.copyfile(source_path, dest)
    for name in new_names:
        op = registry.get_op(name)
        item = {
            "name": name,
            "version": op.version,
            "file": dest.name,
            "enabled": True,
        }
        manifest["operators"] = [x for x in manifest["operators"] if x["name"] != name]
        manifest["operators"].append(item)
    _save_manifest(plugin_dir, manifest)
    return sorted(new_names)


def remove_plugin(name: str, plugin_dir: Path) -> None:
    manifest = _load_manifest(plugin_dir)
    matched = [item for item in manifest["operators"] if item["name"] == name]
    if not matched:
        raise KeyError(f"未找到算子: {name}")
    for item in matched:
        item["enabled"] = False
    _save_manifest(plugin_dir, manifest)


def discover_plugins(plugin_dir: Path) -> None:
    manifest = _load_manifest(plugin_dir)
    for item in manifest["operators"]:
        if not item.get("enabled", True):
            continue
        path = plugin_dir / item["file"]
        if path.exists():
            _import_plugin(path)


def list_enabled_operators(plugin_dir: Path) -> set[str]:
    manifest = _load_manifest(plugin_dir)
    return {item["name"] for item in manifest["operators"] if item.get("enabled", True)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ops.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/ops tests/test_ops.py
git commit -m "feat: add operator registry and plugin lifecycle"
```

---

### Task 5: 最小因子计算路径

**Files:**
- Create: `src/factorlab/engine/__init__.py`
- Create: `src/factorlab/engine/compute.py`
- Test: `tests/test_compute.py`

**Interfaces:**
- Produces: `compute_formula(df: pl.DataFrame, formula: str, asset: str = "code", date: str = "date") -> pl.DataFrame`。

- [ ] **Step 1: Write the failing test**

Create `tests/test_compute.py`:

```python
import polars as pl

from factorlab.engine.compute import compute_formula


def test_compute_formula_returns_signal_column():
    df = pl.DataFrame({
        "date": ["2020-01-01", "2020-01-01", "2020-01-01"],
        "code": ["A", "B", "C"],
        "close": [10.0, 20.0, 30.0],
        "open": [9.0, 19.0, 29.0],
    })
    formula = '''
from polars_ta.prefix.wq import ts_delay
signal = ts_delay(close, 1)
'''
    result = compute_formula(df, formula)
    assert result.columns == ["date", "code", "signal"]
    assert result.height == 3
    assert result["signal"].null_count() == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_compute.py -v`
Expected: FAIL，原因是 `factorlab.engine.compute` 尚不存在。

- [ ] **Step 3: Write minimal implementation**

Create `src/factorlab/engine/__init__.py`:

```python
```

Create `src/factorlab/engine/compute.py`:

```python
import polars as pl
from expr_codegen import codegen_exec

from factorlab.factor.ast_gate import validate_formula


def compute_formula(
    df: pl.DataFrame,
    formula: str,
    asset: str = "code",
    date: str = "date",
) -> pl.DataFrame:
    validate_formula(formula)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_compute.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/engine tests/test_compute.py
git commit -m "feat: add minimal expr_codegen compute adapter"
```

---

### Task 6: CLI lint 命令

**Files:**
- Modify: `src/factorlab/cli/main.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_spec`、`validate_formula`。
- Produces: `factorlab lint <spec>` 命令。

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
import yaml


def test_lint_valid_spec(tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump({
        "name": "demo",
        "category": "custom",
        "direction": 1,
        "universe": {"codes": ["000001.SZ"]},
        "formula": "signal = close / open - 1",
    }, allow_unicode=True), encoding="utf-8")
    result = runner.invoke(app, ["lint", str(spec)])
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_lint_rejects_forbidden_import(tmp_path):
    spec = tmp_path / "bad.yaml"
    spec.write_text(yaml.safe_dump({
        "name": "bad",
        "category": "custom",
        "direction": 1,
        "universe": {"rules": {"exclude_st": True}},
        "formula": "import os\nsignal = close",
    }, allow_unicode=True), encoding="utf-8")
    result = runner.invoke(app, ["lint", str(spec)])
    assert result.exit_code != 0
    assert "禁止导入" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_lint_valid_spec -v`
Expected: FAIL，原因是 `lint` 命令尚不存在。

- [ ] **Step 3: Write minimal implementation**

Modify `src/factorlab/cli/main.py`:

```python
from pathlib import Path

import typer
from rich.console import Console

from factorlab import __version__
from factorlab.factor.ast_gate import validate_formula
from factorlab.spec import load_spec


app = typer.Typer(no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """factorlab 因子 DSL 计算平台"""


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def lint(spec_path: Path) -> None:
    """校验 YAML Spec 与 factor formula AST。"""
    spec = load_spec(spec_path)
    formulas = [spec.formula] if spec.formula is not None else [item.formula for item in spec.factors or []]
    for formula in formulas:
        validate_formula(formula)
    console.print(f"OK {spec.name}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_lint_valid_spec tests/test_cli.py::test_lint_rejects_forbidden_import -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/cli/main.py tests/test_cli.py
git commit -m "feat: add factorlab lint command"
```

---

### Task 7: CLI op 管理命令

**Files:**
- Modify: `src/factorlab/cli/main.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `registry.list_ops/get_op/canonical_name`、`plugins.discover_plugins/add_plugin/remove_plugin`、`config.settings.plugin_dir`。
- Produces: `factorlab op list`、`factorlab op doc <name>`、`factorlab op add <path> [--force]`、`factorlab op remove <name>`。

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
import textwrap

from factorlab.ops import registry


def test_op_list_empty(monkeypatch, tmp_path):
    registry.reset_registry()
    monkeypatch.setattr("factorlab.config.settings.plugin_dir", tmp_path)
    result = runner.invoke(app, ["op", "list"])
    assert result.exit_code == 0


def test_op_add_and_remove(tmp_path):
    registry.reset_registry()
    plugin_path = tmp_path / "my_op.py"
    plugin_path.write_text(textwrap.dedent('''
        import polars as pl
        from factorlab.ops.registry import factor_op

        @factor_op("cli_dummy", kind="el", version="0.1.0")
        def cli_dummy(x: pl.Expr) -> pl.Expr:
            return x
    '''), encoding="utf-8")

    from factorlab.config import settings
    original = settings.plugin_dir
    settings.plugin_dir = tmp_path
    try:
        add = runner.invoke(app, ["op", "add", str(plugin_path)])
        assert add.exit_code == 0
        remove = runner.invoke(app, ["op", "remove", "cli_dummy"])
        assert remove.exit_code == 0
    finally:
        settings.plugin_dir = original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_op_list_empty -v`
Expected: FAIL，原因是 `op` 子命令尚不存在。

- [ ] **Step 3: Write minimal implementation**

Modify `src/factorlab/cli/main.py`:

```python
from factorlab.config import settings
from factorlab.ops import plugins, registry


op_app = typer.Typer(no_args_is_help=True)
app.add_typer(op_app, name="op")


@op_app.command("list")
def op_list() -> None:
    plugins.discover_plugins(settings.plugin_dir)
    rows = [
        {
            "name": op.name,
            "kind": op.kind,
            "version": op.version,
        }
        for op in registry.list_ops()
    ]
    console.print(rows)


@op_app.command("doc")
def op_doc(name: str) -> None:
    plugins.discover_plugins(settings.plugin_dir)
    op = registry.get_op(name)
    console.print(f"{op.name} ({op.kind}, {op.version})")
    console.print(op.doc or "no doc")


@op_app.command("add")
def op_add(path: Path, force: bool = False) -> None:
    names = plugins.add_plugin(path, plugin_dir=settings.plugin_dir, force=force)
    console.print(f"registered: {', '.join(names)}")


@op_app.command("remove")
def op_remove(name: str) -> None:
    plugins.remove_plugin(name, plugin_dir=settings.plugin_dir)
    console.print(f"disabled: {name}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::test_op_list_empty tests/test_cli.py::test_op_add_and_remove -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/factorlab/cli/main.py tests/test_cli.py
git commit -m "feat: add factorlab op management commands"
```

---

### Task 8: M1 端到端测试与 README

**Files:**
- Modify: `README.md`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: 前序所有模块。
- Produces: M1 可验证的端到端流程。

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_m1_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "lint", "op"):
        assert command in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_m1_cli_help_lists_commands -v`
Expected: FAIL，除非帮助输出已包含全部命令。

- [ ] **Step 3: Write minimal README**

Create or replace `README.md`:

```markdown
# factorlab

个人因子 DSL 计算平台。M1 目前提供：

- `factorlab version`
- `factorlab lint <spec.yaml>`
- `factorlab op list|doc|add|remove`

因子脚本是受白名单限制的 Python 代码块，最终输出列为 `signal`。
```

- [ ] **Step 4: Run full M1 test suite**

Run:
```powershell
pytest -q
```
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_cli.py
git commit -m "docs: document M1 CLI surface"
```

---

## Self-Review

- Spec coverage: 本计划覆盖 spec 的 `YAML Spec 模型`、`AST 白名单`、`算子注册/插件`、`最小 expr_codegen 计算路径`、`lint` 与 `op` CLI。数据层、process 链、评估、Web、内存执行器、Alpha 语料对拍留到 M2-M6。
- Placeholder scan: 无 TODO/TBD；每个代码步骤均给出实现。
- Type consistency: `FactorSpec.formula/factors`、`validate_formula(source: str) -> None`、`compute_formula(df, formula, asset, date)`、`registry.get_op/list_ops`、`plugins.add_plugin/remove_plugin/discover_plugins` 在任务间名称一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-15-factorlab-m1-foundation.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks.
2. Inline Execution - execute tasks in this session using executing-plans with checkpoints.

Which approach?
