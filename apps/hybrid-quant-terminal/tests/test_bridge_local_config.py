"""Synthetic checks for authoritative receipt and handoff binding."""

import json

import pytest

from mt5_market_data import mt5_bridge
from mt5_market_data.mt5_bridge import BridgeService, ConsumerOwnershipError


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(mt5_bridge, "PROJECT_ROOT", tmp_path)
    state = tmp_path / "runtime/mt5_bridge/state"
    state.mkdir(parents=True)
    for name in ("checkpoint.json", "revision-ledger.json", "revision-ledger.required"):
        (state / name).touch()
    handoff = tmp_path / "handoff"
    receipt = tmp_path / "runtime/cutover-receipt.json"
    data = {
        "schema": "mt5-runtime-cutover-v1",
        "authoritative_state": str(state),
        "handoff": str(handoff),
    }
    receipt.write_text(json.dumps(data))
    monkeypatch.setattr(BridgeService, "_read_state", lambda self: {})
    monkeypatch.setattr(BridgeService, "_read_revision_ledger", lambda self: {})
    monkeypatch.setattr(mt5_bridge, "load_reviews", lambda *args: {})
    return state, handoff, receipt, data


def test_registered_handoff_acquires_authoritative_lease(configured):
    state, handoff, _, _ = configured
    bridge = BridgeService(handoff, state)
    try:
        bridge._assert_write_authority()
    finally:
        bridge.close()


def test_registered_handoff_rejects_alternate_state(configured):
    state, handoff, _, _ = configured
    with pytest.raises(ConsumerOwnershipError, match="authoritative runtime"):
        BridgeService(handoff, state.parent / "old-state")


def test_authoritative_state_rejects_other_handoff(configured):
    state, _, _, _ = configured
    with pytest.raises(ConsumerOwnershipError, match="does not match"):
        BridgeService(state.parent / "other-handoff", state)


@pytest.mark.parametrize("handoff", [None, "", "relative/path", 12])
def test_malformed_handoff_receipt_fails_closed(configured, handoff):
    state, original, receipt, data = configured
    data["handoff"] = handoff
    receipt.write_text(json.dumps(data))
    with pytest.raises(ConsumerOwnershipError, match="receipt is missing or invalid"):
        BridgeService(original, state)


def test_missing_receipt_fails_closed(configured):
    state, handoff, receipt, _ = configured
    receipt.unlink()
    with pytest.raises(ConsumerOwnershipError, match="receipt is missing or invalid"):
        BridgeService(handoff, state)
    with pytest.raises(ConsumerOwnershipError, match="unregistered handoff refused"):
        BridgeService(handoff, state.parent / "alternate")


def test_wrong_state_in_receipt_fails_closed(configured):
    state, handoff, receipt, data = configured
    data["authoritative_state"] = str(state.parent / "other")
    receipt.write_text(json.dumps(data))
    with pytest.raises(ConsumerOwnershipError, match="receipt is missing or invalid"):
        BridgeService(handoff, state)


def test_malformed_receipt_json_fails_closed(configured):
    state, handoff, receipt, _ = configured
    receipt.write_text("{")
    with pytest.raises(ConsumerOwnershipError, match="receipt is missing or invalid"):
        BridgeService(handoff, state)
