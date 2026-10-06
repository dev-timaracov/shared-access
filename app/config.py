from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Identity(BaseModel):
    developer_id: str = Field(min_length=1, max_length=128)
    role: Literal["reader", "writer", "admin"] = "reader"
    projects: list[str] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://context:context@localhost:5432/context"
    auth_tokens: dict[str, Identity] = Field(default_factory=dict, repr=False)
    plane_base_url: str = "https://api.plane.so"
    plane_api_version: Literal["v1", "v2"] = "v1"
    plane_api_key: SecretStr = SecretStr("")
    plane_sync_reports: bool = False
    mcp_allowed_hosts: list[str] = ["localhost:*", "127.0.0.1:*", "testserver"]
    mcp_allowed_origins: list[str] = ["http://localhost:*", "http://127.0.0.1:*"]

    @model_validator(mode="after")
    def require_tokens(self):
        if not self.auth_tokens or any(not token.strip() for token in self.auth_tokens):
            raise ValueError("AUTH_TOKENS must contain non-empty bearer tokens")
        return self
