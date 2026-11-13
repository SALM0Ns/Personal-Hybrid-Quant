"""Safety checks for the local development process controller."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import devctl


def test_start_refuses_occupied_port_without_launching(monkeypatch, tmp_path):
    monkeypatch.setattr(devctl, "RUN", tmp_path / "run")
    monkeypatch.setattr(devctl, "owned", lambda _: None)
    monkeypatch.setattr(devctl, "port_open", lambda _: True)
    monkeypatch.setattr(
        devctl.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    assert devctl.start() == 1
    # The stable lock file persists, but its kernel lease is released.
    import fcntl

    with (devctl.RUN / "launch.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_stop_never_signals_an_unowned_process(monkeypatch):
    monkeypatch.setattr(devctl, "owned", lambda _: None)
    monkeypatch.setattr(devctl, "port_open", lambda _: False)
    monkeypatch.setattr(
        devctl.os,
        "kill",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not signal")),
    )
    assert devctl.stop() == 0


def test_pid_record_requires_exact_worker_token(monkeypatch, tmp_path):
    monkeypatch.setattr(devctl, "RUN", tmp_path)
    token = "a" * 32
    (tmp_path / "api.json").write_text('{"pid":12345,"token":"' + token + '"}')
    monkeypatch.setattr(
        devctl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="unrelated process"),
    )
    assert devctl.owned("api") is None
    marker = f"{devctl.Path(devctl.__file__).resolve()} _worker api {token}"
    monkeypatch.setattr(
        devctl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=f"{devctl.sys.executable} {marker}"
        ),
    )
    assert devctl.owned("api") == (12345, token)


def test_status_does_not_probe_unowned_services(monkeypatch, tmp_path):
    monkeypatch.setattr(
        devctl, "runtime_paths", lambda: (tmp_path / "handoff", tmp_path / "old")
    )
    monkeypatch.setattr(devctl, "owned", lambda _: None)
    monkeypatch.setattr(devctl, "port_open", lambda _: False)
    monkeypatch.setattr(
        devctl,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not contact")),
    )
    assert devctl.status() == 1


def test_api_worker_delegates_live_lease_to_consumer(monkeypatch, tmp_path):
    monkeypatch.setattr(
        devctl, "runtime_paths", lambda: (tmp_path / "handoff", tmp_path / "old")
    )
    calls = {}

    class Child:
        def poll(self):
            return 0

        def wait(self):
            return 0

    def spawn(command, **kwargs):
        calls.update(command=command, options=kwargs)
        return Child()

    monkeypatch.setenv("MT5_DISABLE_LIVE_BRIDGE", "1")
    monkeypatch.setattr(devctl.subprocess, "Popen", spawn)
    monkeypatch.setattr(devctl.signal, "signal", lambda *args: None)
    monkeypatch.setattr(
        devctl.fcntl,
        "flock",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("worker must not own consumer lease")
        ),
    )
    assert devctl.worker("api") == 0
    assert calls["options"]["env"]["MT5_REQUIRE_EXISTING_RUNTIME"] == "1"
    assert "MT5_DISABLE_LIVE_BRIDGE" not in calls["options"]["env"]
    assert calls["options"]["env"]["PYTHONPATH"] == str(devctl.DEV / "src")
    assert calls["options"]["env"]["MT5_BRIDGE_HANDOFF"] == str(tmp_path / "handoff")
    assert calls["options"]["env"]["MT5_HISTORICAL_ROOT"] == str(tmp_path / "old")


def test_start_refuses_missing_cutover_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(devctl, "RUN", tmp_path / "run")
    monkeypatch.setattr(devctl, "DEV", tmp_path / "dev")
    monkeypatch.setattr(
        devctl, "CUTOVER", tmp_path / "dev/runtime/cutover-receipt.json"
    )
    source = devctl.DEV / "src/mt5_market_data/terminal_api.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic")
    monkeypatch.setattr(devctl, "owned", lambda _: None)
    monkeypatch.setattr(devctl, "port_open", lambda _: False)
    monkeypatch.setattr(
        devctl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="", returncode=0),
    )
    monkeypatch.setattr(
        devctl.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not start")),
    )
    assert devctl.start() == 1
    assert not Path(devctl.CUTOVER).exists()


def test_pre_cutover_backup_refuses_after_runtime_activation(monkeypatch, tmp_path):
    import pytest

    from tools import backup_runtime

    monkeypatch.setattr(backup_runtime, "DEV", tmp_path)
    receipt = tmp_path / "runtime/cutover-receipt.json"
    receipt.parent.mkdir()
    receipt.write_text("{}")
    with pytest.raises(SystemExit, match="cannot back up the active migrated runtime"):
        backup_runtime.main()


def test_stale_unlocked_launch_file_does_not_block_recovery(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(devctl, "RUN", tmp_path)
    (tmp_path / "launch.lock").write_text("stale process marker")
    monkeypatch.setattr(devctl, "owned", lambda _: None)
    monkeypatch.setattr(devctl, "port_open", lambda _: True)
    assert devctl.start() == 1
    assert "already in use" in capsys.readouterr().out
    assert (tmp_path / "launch.lock").exists()


def test_concurrent_launch_lease_is_refused(monkeypatch, tmp_path, capsys):
    import subprocess
    import sys

    monkeypatch.setattr(devctl, "RUN", tmp_path)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl,sys,time; f=open(sys.argv[1], 'a+'); fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(20)",
            str(tmp_path / "launch.lock"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        monkeypatch.setattr(
            devctl,
            "port_open",
            lambda _: (_ for _ in ()).throw(AssertionError("must not probe ports")),
        )
        assert devctl.start() == 1
        assert "Another launcher" in capsys.readouterr().out
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_pid_reuse_or_extra_arguments_are_not_owned(monkeypatch, tmp_path):
    monkeypatch.setattr(devctl, "RUN", tmp_path)
    token = "b" * 32
    (tmp_path / "api.json").write_text('{"pid":12345,"token":"' + token + '"}')
    expected = f"{devctl.sys.executable} {devctl.Path(devctl.__file__).resolve()} _worker api {token}"
    monkeypatch.setattr(
        devctl.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=expected + " --unexpected"
        ),
    )
    assert devctl.owned("api") is None


def test_symlinked_launcher_directory_is_refused(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(devctl, "RUN", link)
    assert devctl.start() == 1
    assert list(target.iterdir()) == []


def test_worker_forwards_termination_even_during_spawn(monkeypatch):
    handlers = {}
    terminated = []

    class Child:
        def poll(self):
            return None if not terminated else 0

        def terminate(self):
            terminated.append(True)

        def wait(self):
            return 0

    def install(sig, handler):
        handlers[sig] = handler

    def spawn(*_args, **_kwargs):
        handlers[devctl.signal.SIGTERM](devctl.signal.SIGTERM, None)
        return Child()

    monkeypatch.setattr(devctl.signal, "signal", install)
    monkeypatch.setattr(devctl.subprocess, "Popen", spawn)
    assert devctl.worker("frontend") == 0
    assert terminated == [True]


def test_partial_start_cleanup_only_stops_spawned_children():
    seen = []

    class Child:
        def __init__(self, running):
            self.running = running

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            seen.append("terminate")
            self.running = False

        def wait(self, timeout):
            assert timeout == 8
            seen.append("wait")
            return 0

    devctl._stop_launched([("api", Child(True)), ("frontend", Child(False))])
    assert seen == ["terminate", "wait", "wait"]


def test_stop_reports_unowned_listener_after_worker_loss(monkeypatch, capsys):
    monkeypatch.setattr(devctl, "owned", lambda _: None)
    monkeypatch.setattr(devctl, "port_open", lambda _: True)
    monkeypatch.setattr(
        devctl.os,
        "kill",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not signal")),
    )
    assert devctl.stop() == 1
    assert "unowned listener remains" in capsys.readouterr().out


def test_start_reuses_verified_healthy_pair_without_spawning(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(devctl, "RUN", tmp_path / "run")
    monkeypatch.setattr(devctl, "owned", lambda name: (100 + len(name), "a" * 32))
    monkeypatch.setattr(devctl, "status", lambda: 0)
    monkeypatch.setattr(
        devctl.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )
    assert devctl.start() == 0
    assert "no new consumer started" in capsys.readouterr().out


def test_start_refuses_unhealthy_existing_pair(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(devctl, "RUN", tmp_path / "run")
    monkeypatch.setattr(devctl, "owned", lambda name: (100 + len(name), "a" * 32))
    monkeypatch.setattr(devctl, "status", lambda: 1)
    monkeypatch.setattr(
        devctl.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )
    assert devctl.start() == 1
    assert "not healthy" in capsys.readouterr().out


def test_start_refuses_partial_existing_pair(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(devctl, "RUN", tmp_path / "run")
    monkeypatch.setattr(
        devctl, "owned", lambda name: (1234, "a" * 32) if name == "api" else None
    )
    monkeypatch.setattr(
        devctl.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )
    assert devctl.start() == 1
    assert "Only part" in capsys.readouterr().out


def test_stop_reports_listener_that_survives_its_supervisor(monkeypatch, capsys):
    stopped = []

    def owner(name):
        return (1234, "a" * 32) if name == "api" and not stopped else None

    monkeypatch.setattr(devctl, "owned", owner)
    monkeypatch.setattr(devctl.os, "kill", lambda pid, sig: stopped.append(pid))
    monkeypatch.setattr(devctl, "port_open", lambda port: port == 8000)
    assert devctl.stop() == 1
    assert stopped == [1234]
    assert "listener remains; no extra signal" in capsys.readouterr().out


def test_runtime_paths_use_receipt_and_matching_environment(monkeypatch, tmp_path):
    import json

    state, original, handoff = (
        tmp_path / "state",
        tmp_path / "old",
        tmp_path / "handoff",
    )
    receipt = tmp_path / "cutover.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "mt5-runtime-cutover-v1",
                "authoritative_state": str(state),
                "historical_read_only_root": str(original),
                "source_state": str(original / "runtime/mt5_bridge/state"),
                "handoff": str(handoff),
            }
        )
    )
    monkeypatch.setattr(devctl, "STATE", state)
    monkeypatch.setattr(devctl, "CUTOVER", receipt)
    monkeypatch.setenv("MT5_BRIDGE_HANDOFF", str(handoff))
    monkeypatch.setenv("MT5_HISTORICAL_ROOT", str(original))
    assert devctl.runtime_paths() == (handoff, original)
    monkeypatch.setenv("MT5_BRIDGE_HANDOFF", str(tmp_path / "different"))
    with pytest.raises(ValueError, match="conflicts with environment"):
        devctl.runtime_paths()


def test_runtime_paths_reject_missing_malformed_and_inconsistent_receipt(
    monkeypatch, tmp_path
):
    import json

    state, original, handoff = (
        tmp_path / "state",
        tmp_path / "old",
        tmp_path / "handoff",
    )
    receipt = tmp_path / "cutover.json"
    monkeypatch.setattr(devctl, "STATE", state)
    monkeypatch.setattr(devctl, "CUTOVER", receipt)
    monkeypatch.delenv("MT5_BRIDGE_HANDOFF", raising=False)
    monkeypatch.delenv("MT5_HISTORICAL_ROOT", raising=False)
    with pytest.raises(ValueError, match="configuration missing"):
        devctl.runtime_paths()
    receipt.write_text("invalid json")
    with pytest.raises(ValueError, match="configuration missing"):
        devctl.runtime_paths()
    record = {
        "schema": "mt5-runtime-cutover-v1",
        "authoritative_state": str(state),
        "historical_read_only_root": str(original),
        "source_state": str(tmp_path / "elsewhere"),
        "handoff": str(handoff),
    }
    receipt.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="configuration missing"):
        devctl.runtime_paths()
    record["source_state"] = str(original / "runtime/mt5_bridge/state")
    record["handoff"] = "relative"
    receipt.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="configuration missing"):
        devctl.runtime_paths()


def test_api_worker_missing_config_does_not_spawn(monkeypatch):
    monkeypatch.setattr(
        devctl,
        "runtime_paths",
        lambda: (_ for _ in ()).throw(ValueError("local config missing")),
    )
    monkeypatch.setattr(
        devctl.subprocess,
        "Popen",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )
    assert devctl.worker("api") == 1
