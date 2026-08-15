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
