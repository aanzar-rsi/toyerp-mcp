import argparse

import pytest

from scripts.erp_admin import build_parser, command_payload
from scripts.mcp_client import object_json


def test_admin_payloads_and_agent_arguments():
    args = build_parser().parse_args(["set-user-active", "agent1", "inactive"])
    assert command_payload(args) == ("set_user_active", {"username": "agent1", "active": False})

    args = build_parser().parse_args(["grant-role-tool", "readers", "BAPI_VENDOR_GETLIST"])
    assert command_payload(args) == (
        "grant_role_tool",
        {"role": "readers", "tool": "BAPI_VENDOR_GETLIST"},
    )
    assert object_json('{"material_id": 1}') == {"material_id": 1}
    with pytest.raises(argparse.ArgumentTypeError):
        object_json("[]")
