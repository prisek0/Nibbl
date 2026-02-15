"""Configuration loading for Nibbl."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class FamilyMemberConfig(BaseModel):
    name: str
    imessage_id: str
    role: str  # "parent" or "child"


class AgentConfig(BaseModel):
    poll_interval_seconds: int = 5
    preference_timeout_hours: int = 4
    pantry_timeout_hours: int = 2
    plan_days: int = 4
    language: str = "nl"


class IMessageConfig(BaseModel):
    chat_db_path: str = "~/Library/Messages/chat.db"
    group_chat_name: str | None = None
    self_id: str = ""  # your own phone number / Apple ID (the Mac owner)

    @property
    def resolved_chat_db_path(self) -> Path:
        return Path(self.chat_db_path).expanduser()


class ClaudeConfig(BaseModel):
    model_planning: str = "claude-sonnet-4-20250514"
    model_extraction: str = "claude-haiku-4-5-20251001"
    model_conversation: str = "claude-sonnet-4-20250514"


class PicnicConfig(BaseModel):
    country_code: str = "NL"


class ScheduleConfig(BaseModel):
    enabled: bool = True
    day_of_week: str = "sun"
    hour: int = 10
    minute: int = 0


class DatabaseConfig(BaseModel):
    path: str = "data/nibbl.db"


class ExportConfig(BaseModel):
    enabled: bool = True
    path: str = "~/Nibbl"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/nibbl.log"


def _load_dotenv(env_path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ (if not already set)."""
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip optional 'export ' prefix
            if line.startswith("export "):
                line = line[7:]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


class Config(BaseModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    family_members: list[FamilyMemberConfig] = Field(default_factory=list)
    imessage: IMessageConfig = Field(default_factory=IMessageConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    picnic: PicnicConfig = Field(default_factory=PicnicConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Secrets loaded from environment variables
    anthropic_api_key: str = ""
    picnic_username: str = ""
    picnic_password: str = ""

    @classmethod
    def load(cls, config_path: str | None = None) -> Config:
        path = Path(config_path or os.environ.get("NIBBL_CONFIG", "config.toml"))
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        # Load .env file from same directory as config.toml
        _load_dotenv(path.parent / ".env")

        with open(path, "rb") as f:
            raw = tomllib.load(f)

        # Flatten family.members -> family_members
        family_section = raw.pop("family", {})
        raw["family_members"] = family_section.get("members", [])

        # Load secrets from environment variables
        raw["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
        raw["picnic_username"] = os.environ.get("PICNIC_USERNAME", "")
        raw["picnic_password"] = os.environ.get("PICNIC_PASSWORD", "")

        return cls(**raw)

    @property
    def db_path(self) -> Path:
        return Path(self.database.path)
