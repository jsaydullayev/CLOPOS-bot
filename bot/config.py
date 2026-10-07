"""Settings read from environment variables and the .env file."""

from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """The part of the settings that migrations need."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str


class Settings(DatabaseSettings):
    bot_token: str
    admin_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    backup_channel_id: int

    webhook_url: str = ""
    webhook_secret: str = ""
    web_server_host: str = "0.0.0.0"
    web_server_port: int = 8080

    protect_content: bool = False
    max_depth: int = Field(default=5, ge=1, le=10)

    db_backup_enabled: bool = True
    db_backup_hour: int = Field(default=3, ge=0, le=23)
    timezone: str = "Asia/Tashkent"
    log_level: str = "INFO"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(int(part) for part in value.replace(";", ",").split(",") if part.strip())
        if isinstance(value, int):
            return frozenset({value})
        return value

    @property
    def webhook_path(self) -> str:
        return urlparse(self.webhook_url).path or "/webhook"

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    return Settings()
