"""tests/live — pytest wrappers around certification harnesses.

These tests need a live Factorio instance and are marked `live`. pytest.ini
sets --strict-markers and does not know the marker, so it is registered here
(pytest.ini is owned by the certification ledger workflow; new-file-only
change). Offline they SKIP — a real SKIP, never a vacuous pass.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: needs a running Factorio instance (RCON); skipped offline",
    )
