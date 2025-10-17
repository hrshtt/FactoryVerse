import logging
import os
import platform
from enum import Enum
from pathlib import Path
from typing import Optional, Literal

from pydantic import BaseModel, Field, model_validator
# from pydantic_settings import BaseSettings, SettingsConfigDict


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
print(ROOT_DIR)


class Scenario(Enum):
    FACTORY_VERSE = "factory_verse"

def _detect_local_mods_path(os_name: str) -> str:
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


class DockerConfig(BaseModel):
    """Configuration knobs for Factorio headless servers managed by FactoryVerse."""

    # Core system configuration
    mode: Literal["save-based", "scenario"]
    arch: str = Field(default_factory=platform.machine)
    os_name: str = Field(default_factory=platform.system)
    address: str = "localhost"
    image_name: str = "factoriotools/factorio:1.1.110"
    rcon_port: int = 27015
    udp_port: int = 34197
    force_amd64: bool = False

    # Runtime mode and behavior
    dry_run: bool = False
    num_servers: int = Field(default=1, ge=1, le=33, description="Number of servers to start")

    # Game configuration
    scenario_name: str = Scenario.FACTORY_VERSE.value
    image_name_prefix: str = "factorio_"

    # Paths and directories
    fv_factorio_dir: Path = Field(default_factory=lambda: ROOT_DIR / "factorio")
    fv_saves_dir: Path = Field(default_factory=lambda: ROOT_DIR / ".fv" / "saves")
    local_mods_dir: str = Field(default_factory=lambda: _detect_local_mods_path(platform.system()))
    server_currently_playing_dir: str = "/opt/factorio/temp/currently-playing"

    # Optional fields (set by validator)
    fv_server_config_dir: Optional[Path] = None
    fv_scenario_dir: Optional[Path] = None
    server_rcon_password: Optional[str] = None

    # model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", cli_parse_args=True)

    @model_validator(mode="after")
    def load_secondary_paths(self):
        if (self.fv_factorio_dir / "config").exists():
            self.fv_server_config_dir = self.fv_factorio_dir / "config"
            if (self.fv_server_config_dir / "rconpw").exists():
                self.server_rcon_password = (
                    (self.fv_server_config_dir / "rconpw").read_text().strip()
                )
        if (self.fv_factorio_dir / "scenarios").exists():
            self.fv_scenario_dir = self.fv_factorio_dir / "scenarios"
        return self
