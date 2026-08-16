from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FACTORLAB_",
        env_file=".env",
        extra="ignore",
    )

    # 平台库为唯一数据源（项目自包含，不依赖任何外部只读库）
    platform_db: Path = Path("data/factorlab.duckdb")
    plugin_dir: Path = Path.home() / ".factorlab" / "plugins"
    teajoin_base_url: str = "https://teajoin.com"  # 根路径；/g 为文档页
    teajoin_token: str = ""
    default_max_memory: str = "4GB"
    default_chunk_size: int = 1000
    use_float32: bool = True
    data_dir: Path = Path("data")
    universes_dir: Path = Path.home() / ".factorlab" / "universes"
    default_universe: str | None = None


settings = Settings()
settings.plugin_dir.mkdir(parents=True, exist_ok=True)
