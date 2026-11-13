"""Offline process-ownership tests using only disposable synthetic state."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from mt5_market_data.mt5_bridge import BridgeService, ConsumerOwnershipError


def test_consumer_rejects_competing_writer_and_recovers_after_abnormal_exit(
    tmp_path, monkeypatch
):
    incoming, state = tmp_path / "incoming", tmp_path / "state"
    code = """
import sys
from pathlib import Path
from mt5_market_data.mt5_bridge import BridgeService
bridge = BridgeService(Path(sys.argv[1]), Path(sys.argv[2]), enforce_consumer_lease=True)
print("owned", flush=True)
sys.stdin.readline()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    holder = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(incoming), str(state)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "owned"
        with pytest.raises(ConsumerOwnershipError, match="another consumer"):
            BridgeService(incoming, state, enforce_consumer_lease=True)
        from mt5_market_data import terminal_api

        monkeypatch.delenv("MT5_DISABLE_LIVE_BRIDGE", raising=False)
        monkeypatch.setattr(
            terminal_api,
            "BridgeService",
            lambda: BridgeService(incoming, state, enforce_consumer_lease=True),
        )
        with pytest.raises(RuntimeError, match="consumer ownership unavailable"):
            terminal_api.create_app()
        assert not state.exists()
    finally:
        holder.kill()
        holder.communicate(timeout=10)
    replacement = BridgeService(incoming, state, enforce_consumer_lease=True)
    replacement.close()
    assert not state.exists()


def test_replaced_lease_file_disables_original_writer(tmp_path):
    bridge = BridgeService(
        tmp_path / "in", tmp_path / "state", enforce_consumer_lease=True
    )
    lock = tmp_path / ".state.consumer.lock"
    lock.unlink()
    lock.touch()
    try:
        with pytest.raises(ConsumerOwnershipError, match="replaced"):
            bridge.poll()
        assert not (tmp_path / "state").exists()
    finally:
        bridge.close()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_forked_process_cannot_use_parent_consumer(tmp_path):
    bridge = BridgeService(
        tmp_path / "in", tmp_path / "state", enforce_consumer_lease=True
    )
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        try:
            bridge.poll()
        except ConsumerOwnershipError:
            os.write(write_fd, b"rejected")
        else:
            os.write(write_fd, b"accepted")
        os._exit(0)
    os.close(write_fd)
    try:
        result = os.read(read_fd, 20)
        _, status = os.waitpid(child, 0)
        assert status == 0 and result == b"rejected"
        bridge._assert_write_authority()
        with pytest.raises(ConsumerOwnershipError, match="another consumer"):
            BridgeService(
                tmp_path / "in", tmp_path / "state", enforce_consumer_lease=True
            )
    finally:
        os.close(read_fd)
        bridge.close()


def test_api_ownership_conflict_is_not_silently_downgraded(monkeypatch):
    from mt5_market_data import terminal_api

    def conflict():
        raise ConsumerOwnershipError("another consumer")

    monkeypatch.delenv("MT5_DISABLE_LIVE_BRIDGE", raising=False)
    monkeypatch.setattr(terminal_api, "BridgeService", conflict)
    with pytest.raises(RuntimeError, match="consumer ownership unavailable"):
        terminal_api.create_app()


def test_simultaneous_workers_have_exactly_one_owner(tmp_path):
    code = """
import sys
from pathlib import Path
from mt5_market_data.mt5_bridge import BridgeService, ConsumerOwnershipError
sys.stdin.readline()
try:
    bridge = BridgeService(Path(sys.argv[1]), Path(sys.argv[2]), enforce_consumer_lease=True)
except ConsumerOwnershipError:
    print("conflict", flush=True)
else:
    print("owner", flush=True)
    sys.stdin.readline()
    bridge.close()
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    workers = [
        subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                code,
                str(tmp_path / "in"),
                str(tmp_path / "state"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.stdin.write("start\n")
            worker.stdin.flush()
        assert sorted(worker.stdout.readline().strip() for worker in workers) == [
            "conflict",
            "owner",
        ]
        assert not (tmp_path / "state").exists()
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=10)


def test_live_handoff_rejects_non_authoritative_or_old_state(tmp_path, monkeypatch):
    from mt5_market_data import mt5_bridge

    monkeypatch.setattr(mt5_bridge, "PROJECT_ROOT", tmp_path)
    live_handoff = tmp_path / "synthetic-handoff"
    receipt = tmp_path / "runtime/cutover-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "schema": "mt5-runtime-cutover-v1",
                "authoritative_state": str(tmp_path / "runtime/mt5_bridge/state"),
                "handoff": str(live_handoff),
            }
        )
    )
    old_state = tmp_path / "old-checkpoint"
    with pytest.raises(ConsumerOwnershipError, match="authoritative runtime"):
        BridgeService(live_handoff, old_state)
    assert not old_state.exists()
