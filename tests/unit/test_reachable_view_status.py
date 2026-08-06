"""Unit tests for the reachable_view status filter (C5 / status-filter mirage).

Prior behavior: options={'status': ...} compared the caller value directly
against the payload's raw int `status` — so a caller passing the documented
symbolic name (e.g. "no-power") always silently matched nothing (get_entity/
get_entities returned None/[] with no error). This pins the fix: ints match
directly, strings normalize '-'->'_' and resolve via EntityStatus, and also
match against the payload's `status_name` (mirrors the Lua
direction/direction_name pattern — C5). Unknown names raise ValueError
naming the valid options instead of silently matching nothing.
"""

import pytest

from FactoryVerse.game.agent.reachable_view import _status_matches


NO_POWER_PAYLOAD = {"status": 54}
NO_POWER_PAYLOAD_WITH_NAME = {"status": 54, "status_name": "no_power"}


class TestStatusMatchesInt:
    def test_int_matches_int(self):
        assert _status_matches(NO_POWER_PAYLOAD, 54) is True

    def test_int_mismatch(self):
        assert _status_matches(NO_POWER_PAYLOAD, 1) is False


class TestStatusMatchesString:
    def test_underscore_name_matches(self):
        assert _status_matches(NO_POWER_PAYLOAD, "no_power") is True

    def test_hyphen_name_normalizes_and_matches(self):
        assert _status_matches(NO_POWER_PAYLOAD, "no-power") is True

    def test_matches_via_status_name_when_int_absent(self):
        payload = {"status_name": "no_power"}
        assert _status_matches(payload, "no_power") is True
        assert _status_matches(payload, "no-power") is True

    def test_mismatched_name(self):
        assert _status_matches(NO_POWER_PAYLOAD, "working") is False

    def test_unknown_name_raises_value_error_naming_options(self):
        with pytest.raises(ValueError) as exc_info:
            _status_matches(NO_POWER_PAYLOAD, "not_a_status")
        message = str(exc_info.value)
        assert "not_a_status" in message
        # A couple of valid options should be named so callers can self-correct
        assert "no_power" in message
        assert "working" in message


class TestStatusMatchesEndToEnd:
    """Confirms the payload-with-both-fields case (the live Lua shape once
    reachability.lua emits status_name) matches identically for all three
    caller spellings the task specifies."""

    @pytest.mark.parametrize("wanted", [54, "no_power", "no-power"])
    def test_all_spellings_match(self, wanted):
        assert _status_matches(NO_POWER_PAYLOAD_WITH_NAME, wanted) is True

    def test_unknown_spelling_still_raises(self):
        with pytest.raises(ValueError):
            _status_matches(NO_POWER_PAYLOAD_WITH_NAME, "not_a_status")
