from enum import Enum

from pydantic import model_validator
from pydantic_settings import BaseSettings, CliApp, SettingsConfigDict

from FactoryVerse.services.docker.config import DockerConfig


class Mode(Enum):
    SAVE_BASED = "save-based"
    SCENARIO = "scenario"

class Settings(BaseSettings):
    mode: Mode = Mode.SAVE_BASED
    docker: DockerConfig

    @model_validator(mode="after")
    def sync_mode_to_docker(self):
        """Sync the mode setting to the docker config"""
        self.docker.mode = self.mode.value
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        cli_parse_args=True,
        cli_kebab_case=True,
        cli_prog_name="factoryverse",
        cli_implicit_flags=True,
    )


# parse CLI flags, env vars, and .env in one go
settings = CliApp.run(Settings)