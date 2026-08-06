import json

from FactoryVerse.infra.rcon_helper import RconHelper


class _FreshFreeplayRcon:
    def __init__(self):
        self.commands = []

    def send_command(self, command):
        self.commands.append(command)
        if len(self.commands) == 1:
            return None
        return json.dumps({"agent": {"list_agents": True}, "map": {}})


def test_interface_discovery_repeats_first_fresh_freeplay_console_command():
    rcon = _FreshFreeplayRcon()

    helper = RconHelper(rcon, udp_listener=None, auto_create_agent=False)

    assert helper.interfaces["agent"]["list_agents"] is True
    assert len(rcon.commands) == 2
    assert rcon.commands[0] == rcon.commands[1]
