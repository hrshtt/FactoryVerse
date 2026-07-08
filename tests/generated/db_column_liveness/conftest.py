"""Family fixtures for db_column_liveness, built on the frozen runtime.

Session shape: one cell allocation per pytest session (FV_CELL_INDEX), one rig
build per session (module fixtures request what they need via `rig`), one
snapshot ritual, one DB load. Tests then compare DB rows against engine truth
captured through the independent RCON channel.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _frozen import runtime  # noqa: E402

pytestmark = pytest.mark.live

LIVE = os.environ.get("FV_LIVE_TESTS") == "1"


def pytest_collection_modifyitems(config, items):
    if not LIVE:
        skip = pytest.mark.skip(reason="live suite: set FV_LIVE_TESTS=1 with a running lab-grid instance")
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def instance() -> runtime.Instance:
    return runtime.instance_from_env()


@pytest.fixture(scope="session")
def rcon(instance):
    r = runtime.connect(instance)
    runtime.verify_grid_config(r)
    return r


@pytest.fixture(scope="session")
def cell(rcon):
    idx = int(os.environ.get("FV_CELL_INDEX", "7"))
    session = runtime.allocate_cell(rcon, idx)
    yield session
    runtime.release_cell(rcon, session)


@pytest.fixture(scope="session")
def frozen_spec():
    from _frozen import liveness_spec
    return liveness_spec
