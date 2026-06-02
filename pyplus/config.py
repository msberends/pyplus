from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PYPLUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8080

    # Fernet key — absent means remember-me and background jobs are disabled.
    secret_key: str = ""

    # Where the SQLite DB, ML artifacts, and logs live.
    data_dir: Path = Path.home() / ".local" / "share" / "pyplus"

    # Set to True to disable the in-app APScheduler (use crontab only).
    disable_scheduler: bool = False

    # Default ntfy instance; overridden per user in Settings screen.
    ntfy_url: str = "https://ntfy.sh"

    # Public base URL used in ntfy deep links (e.g. "http://localhost:8080").
    # Leave empty to omit deep links from ntfy messages.
    base_url: str = ""

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand_data_dir(cls, v: str | Path) -> Path:
        return Path(v).expanduser() if v else Path.home() / ".local" / "share" / "pyplus"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pyplus.db"

    @property
    def encryption_available(self) -> bool:
        return bool(self.secret_key)


settings = Settings()
