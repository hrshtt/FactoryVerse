"""Regression: SyncService._resolve_file_io_path must tolerate both
snapshot_dir conventions (script-output root vs <root>/factoryverse/snapshots,
the latter being what tier4_runtime passes via get_snapshot_dir()).

Found live 2026-07-12: the duplicated "factoryverse" segment made live
file_io sync (power_networks / entity_status) a silent no-op while boot-time
bulk load worked — exactly the mixed-fidelity failure class MIRAGE-2 covers.
"""

from pathlib import Path

from FactoryVerse.game.infra.duckdb.sync import SyncService


def _mk(snapshot_dir: Path) -> SyncService:
    svc = object.__new__(SyncService)
    svc._snapshot_dir = snapshot_dir
    return svc


MOD_POWER = "factoryverse/snapshots/power_networks.jsonl"
MOD_STATUS = "factoryverse/status/status-12345.jsonl"


def test_resolves_from_script_output_root():
    root = Path("/data/.fv-output/server_0")
    svc = _mk(root)
    assert svc._resolve_file_io_path(MOD_POWER) == root / MOD_POWER
    assert svc._resolve_file_io_path(MOD_STATUS) == root / MOD_STATUS


def test_resolves_from_tier4_snapshot_dir():
    root = Path("/data/.fv-output/server_0")
    svc = _mk(root / "factoryverse" / "snapshots")
    assert svc._resolve_file_io_path(MOD_POWER) == root / MOD_POWER
    assert svc._resolve_file_io_path(MOD_STATUS) == root / MOD_STATUS


def test_resolves_from_factoryverse_dir():
    root = Path("/data/.fv-output/server_0")
    svc = _mk(root / "factoryverse")
    assert svc._resolve_file_io_path(MOD_POWER) == root / MOD_POWER


def test_none_when_unconfigured():
    svc = _mk(None)
    assert svc._resolve_file_io_path(MOD_POWER) is None
