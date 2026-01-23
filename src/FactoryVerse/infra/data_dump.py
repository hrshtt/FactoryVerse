"""Factorio data dump management.

Handles dumping Factorio's data.raw to JSON and pruning it
for use by the FactoryVerse runtime.

The pipeline:
1. Run Factorio with --dump-data to produce data-raw-dump.json
2. Prune visual/audio keys to produce factorio-data-dump.json
"""

import json
import logging
from pathlib import Path
from typing import Any, Tuple

from FactoryVerse.environment.config import get_config, FactoryVerseConfig

logger = logging.getLogger(__name__)

# Keys to remove from data.raw (visual, audio, and other non-essential data)
BANNED_KEYS = (
    "sound",
    "picture",
    "shadow",
    "sprite",
    "icon",
    "font",
    "gui",
    "light_flicker",
    "smoke",
    "animation",
    "graphics_set",
    "working_visualization",
    "integration_patch",
    "pipe_covers",
    "tint",
    "dying_explosion",
    "corpse",
    "damaged_trigger_effect",
    "water_reflection",
    "wall_diode_",
    "visual_merge_group",
    "impact_category",
    "resistances",
)


def _prune_keys(obj: Any) -> Any:
    """Recursively remove keys containing banned substrings.

    Args:
        obj: JSON-like object (dict, list, or primitive)

    Returns:
        Pruned object with banned keys removed
    """
    if isinstance(obj, dict):
        return {
            k: _prune_keys(v)
            for k, v in obj.items()
            if not any(banned in k.lower() for banned in BANNED_KEYS)
        }
    elif isinstance(obj, list):
        return [_prune_keys(item) for item in obj]
    return obj


def get_data_raw_path(instance: str = "client") -> Path:
    """Get path to data-raw-dump.json for an instance.

    Args:
        instance: 'client' or 'server_N'

    Returns:
        Path to data-raw-dump.json
    """
    config = get_config()
    script_output = config.get_script_output_dir(instance)
    return script_output / "data-raw-dump.json"


def prune_data_raw(
    input_path: Path, output_path: Path, dry_run: bool = False
) -> Tuple[Path, int, int]:
    """Prune data-raw-dump.json to factorio-data-dump.json.

    Removes visual, audio, and other non-essential keys to reduce file size
    and focus on game mechanics data.

    Args:
        input_path: Path to data-raw-dump.json
        output_path: Path for output factorio-data-dump.json
        dry_run: If True, don't write output file

    Returns:
        Tuple of (output_path, original_size, pruned_size)

    Raises:
        FileNotFoundError: If input file doesn't exist
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    logger.info(f"Loading data from {input_path}")
    with open(input_path, "r") as f:
        original_data = json.load(f)

    original_size = input_path.stat().st_size

    logger.info("Pruning visual/audio keys...")
    pruned_data = _prune_keys(original_data)

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(pruned_data, f)
        pruned_size = output_path.stat().st_size
        logger.info(
            f"Saved pruned data to {output_path} "
            f"({original_size / 1024 / 1024:.1f}MB -> {pruned_size / 1024 / 1024:.1f}MB)"
        )
    else:
        # Estimate size without writing
        pruned_json = json.dumps(pruned_data)
        pruned_size = len(pruned_json.encode("utf-8"))
        logger.info(
            f"[DRY RUN] Would save to {output_path} "
            f"({original_size / 1024 / 1024:.1f}MB -> {pruned_size / 1024 / 1024:.1f}MB)"
        )

    return output_path, original_size, pruned_size


def refresh_data_dump(
    instance: str = "client", config: FactoryVerseConfig | None = None
) -> Path:
    """Full pipeline: find data-raw-dump.json and prune it.

    Args:
        instance: 'client' or 'server_N' to read data-raw-dump.json from
        config: Optional config override

    Returns:
        Path to the generated factorio-data-dump.json

    Raises:
        FileNotFoundError: If data-raw-dump.json doesn't exist.
            Run Factorio with --dump-data first.
    """
    cfg = config or get_config()

    input_path = get_data_raw_path(instance)
    output_path = cfg.data_dump_path

    if not input_path.exists():
        raise FileNotFoundError(
            f"data-raw-dump.json not found at {input_path}.\n"
            f"Run Factorio with --dump-data to generate it:\n"
            f"  For client: fv client dump-data\n"
            f"  Manual: /path/to/factorio --dump-data"
        )

    output, _, _ = prune_data_raw(input_path, output_path)
    return output
