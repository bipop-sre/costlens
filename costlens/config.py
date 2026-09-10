"""Agent configuration management."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudProvider(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    ALIBABA = "alibaba"
    TENCENT = "tencent"


class Language(str, Enum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"

    # AWS
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"

    # Azure
    azure_subscription_id: Optional[str] = None
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None

    # GCP
    gcp_project_id: Optional[str] = None
    gcp_billing_account_id: Optional[str] = None

    # Alibaba Cloud
    alibaba_cloud_access_key_id: Optional[str] = None
    alibaba_cloud_access_key_secret: Optional[str] = None
    alibaba_cloud_region: str = "cn-hangzhou"

    # Tencent Cloud
    tencent_cloud_secret_id: Optional[str] = None
    tencent_cloud_secret_key: Optional[str] = None
    tencent_cloud_region: str = "ap-guangzhou"


    # Database (sqlite or oceanbase)
    db_type: str = "sqlite"
    db_path: str = "costlens.db"
    oceanbase_host: str = "127.0.0.1"
    oceanbase_port: int = 2881
    oceanbase_user: str = "root"
    oceanbase_password: str = ""
    oceanbase_database: str = "costlens"

    # Alerts
    alert_budget_threshold_pct: float = 80.0
    alert_cost_anomaly_threshold: float = 20.0
    alert_webhook_url: Optional[str] = None

    # WeChat Work Bot
    wechat_work_bot_id: Optional[str] = None
    wechat_work_bot_secret: Optional[str] = None
    web_auth_token: Optional[str] = None
    alert_email: Optional[str] = None

    # Agent
    agent_language: Language = Language.ZH_CN
    agent_cost_cache_ttl: int = 3600

    # Enabled cloud providers (comma-separated in env: "aws,azure,gcp")
    enabled_providers: str = "aws"

    def get_enabled_providers(self) -> list[CloudProvider]:
        providers = []
        for name in self.enabled_providers.split(","):
            name = name.strip().lower()
            if name:
                providers.append(CloudProvider(name))
        return providers


@lru_cache
def get_settings() -> Settings:
    return Settings()
