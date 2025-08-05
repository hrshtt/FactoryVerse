import logging
import os
import platform
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
print(ROOT_DIR)


class Scenario(Enum):
    OPEN_WORLD = "open_world"
    DEFAULT_LAB_SCENARIO = "default_lab_scenario"
    FACTORY_VERSE = "factory_verse"


class Mode(Enum):
    SAVE_BASED = "save-based"
    SCENARIO = "scenario"


def _detect_mods_path(os_name: str) -> str:
    if any(x in os_name for x in ("MINGW", "MSYS", "CYGWIN")):
        path = os.getenv("APPDATA", "")
        mods = Path(path) / "Factorio" / "mods"
        if mods.exists():
            return str(mods)
        return str(
            Path(os.getenv("USERPROFILE", ""))
            / "AppData"
            / "Roaming"
            / "Factorio"
            / "mods"
        )
    return str(
        Path.home()
        / "Applications"
        / "Factorio.app"
        / "Contents"
        / "Resources"
        / "mods"
    )


class DockerConfig(BaseSettings):
    """Configuration knobs for Factorio headless servers managed by fle.services.docker."""

    # Core system configuration
    arch: str = Field(default_factory=platform.machine)
    os_name: str = Field(default_factory=platform.system)
    address: str = "localhost"

    # Runtime mode and behavior
    mode: str = Mode.SAVE_BASED.value
    dry_run: bool = False

    # Docker and networking
    image_name: str = "factoriotools/factorio:1.1.110"
    rcon_port: int = 27015
    udp_port: int = 34197

    # Game configuration
    scenario_name: str = Scenario.FACTORY_VERSE.value
    name_prefix: str = "factorio_"

    # Paths and directories
    fv_factorio_path: Path = Field(default_factory=lambda: ROOT_DIR / "factorio")
    saves_path: Path = Field(default_factory=lambda: ROOT_DIR / ".fv" / "saves")
    mods_path: str = Field(default_factory=lambda: _detect_mods_path(platform.system()))
    temp_playing_dir: str = "/opt/factorio/temp/currently-playing"

    # Optional fields (set by validator)
    server_config_dir: Optional[Path] = None
    scenario_dir: Optional[Path] = None
    factorio_password: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def load_configs(self):
        if (self.fv_factorio_path / "config").exists():
            self.server_config_dir = self.fv_factorio_path / "config"
            if (self.server_config_dir / "rconpw").exists():
                self.factorio_password = (
                    (self.server_config_dir / "rconpw").read_text().strip()
                )
        if (self.fv_factorio_path / "scenarios").exists():
            self.scenario_dir = self.fv_factorio_path / "scenarios"
        return self
