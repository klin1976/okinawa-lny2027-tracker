from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """系統全域環境設定（自動讀取 .env 與環境變數）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 服務與資料庫
    host: str = Field("0.0.0.0", alias="HOST")
    port: int = Field(8000, alias="PORT")
    api_key: str = Field("changeme", alias="API_KEY")
    database_path: str = Field("data/tracker.db", alias="DATABASE_PATH")

    # LLM 供應商設定 (gemini 或 ollama)
    llm_provider: str = Field("gemini", alias="LLM_PROVIDER")
    gemini_api_key: Optional[str] = Field(None, alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-3.8-flash", alias="GEMINI_MODEL")

    ollama_base_url: str = Field("http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field("qwen2.5:14b", alias="OLLAMA_MODEL")

    # 爬蟲與增量解析限制
    max_new_details_per_run: int = Field(15, alias="MAX_NEW_DETAILS_PER_RUN")
    crawler_headless: bool = Field(True, alias="CRAWLER_HEADLESS")
    crawler_jitter_min: float = Field(2.0, alias="CRAWLER_JITTER_MIN")
    crawler_jitter_max: float = Field(4.5, alias="CRAWLER_JITTER_MAX")

    # 告警預設門檻
    alert_price_drop_adult: int = Field(1500, alias="ALERT_PRICE_DROP_ADULT")
    alert_price_drop_family: int = Field(10000, alias="ALERT_PRICE_DROP_FAMILY")

    def get_litellm_provider_model(self) -> str:
        """回傳 Crawl4AI / LiteLLM 相容的 provider/model 字串。"""
        provider = self.llm_provider.strip().lower()
        if provider == "ollama":
            model = self.ollama_model
            return model if model.startswith("ollama/") else f"ollama/{model}"
        model = self.gemini_model
        return model if model.startswith("gemini/") else f"gemini/{model}"

    def get_llm_api_token(self) -> Optional[str]:
        """取得對應供應商所需的 API Token。"""
        if self.llm_provider.strip().lower() == "ollama":
            return None
        return self.gemini_api_key

    def get_llm_base_url(self) -> Optional[str]:
        """取得自訂 Base URL（Ollama 使用）。"""
        if self.llm_provider.strip().lower() == "ollama":
            return self.ollama_base_url
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_yaml_config(path: str | Path) -> Dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"找不到設定檔：{target}")
    with open(target, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_family_profile(path: str | Path = "config/family_profile.yaml") -> Dict[str, Any]:
    return load_yaml_config(path)


def load_agencies_config(path: str | Path = "config/agencies.yaml") -> Dict[str, Any]:
    return load_yaml_config(path)
