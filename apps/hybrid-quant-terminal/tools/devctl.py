"""Local-only launcher for the authoritative Developer runtime and MT5 handoff."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

DEV = Path(__file__).resolve().parents[1]
RUN = DEV / ".local-dev"
STATE = DEV / "runtime/mt5_bridge/state"
CUTOVER = DEV / "runtime/cutover-receipt.json"
SERVICES = {"api": 8000, "frontend": 5173}


def runtime_paths() -> tuple[Path, Path]:
    """Read the ignored local cutover receipt; never invent another authority."""
    try:
        if CUTOVER.is_symlink():
            raise ValueError("symlinked receipt")
        receipt = json.loads(CUTOVER.read_bytes())
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema") != "mt5-runtime-cutover-v1"
            or receipt.get("authoritative_state") != str(STATE)
        ):
            raise ValueError("invalid receipt identity")
        raw_handoff = receipt.get("handoff")
        raw_original = receipt.get("historical_read_only_root")
        raw_source = receipt.get("source_state")
        if not all(
            isinstance(value, str) and value
            for value in (raw_handoff, raw_original, raw_source)
        ):
            raise ValueError("missing configured runtime paths")
        handoff, original, source = map(Path, (raw_handoff, raw_original, raw_source))
        if (
            not all(path.is_absolute() for path in (handoff, original, source))
            or source.resolve() != (original / "runtime/mt5_bridge/state").resolve()
        ):
            raise ValueError("invalid configured runtime paths")
        for name, expected in (
            ("MT5_BRIDGE_HANDOFF", handoff),
            ("MT5_HISTORICAL_ROOT", original),
        ):
            override = os.environ.get(name)
            if override is not None and (
                not override
                or Path(override).expanduser().resolve() != expected.resolve()
            ):
                raise ValueError("environment path conflicts with cutover receipt")
        return handoff, original
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            "Local runtime configuration missing, invalid, or conflicts with environment; inspect the cutover receipt."
        ) from exc


def owned(service: str) -> tuple[int, str] | None:
    try:
        value = json.loads((RUN / f"{service}.json").read_text())
        pid, token = value["pid"], value["token"]
        if (
            not isinstance(pid, int)
            or pid <= 1
            or not re.fullmatch(r"[0-9a-f]{32}", token)
        ):
            return None
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            capture_output=True,
            check=False,
        )
        expected = (
            f"{sys.executable} {Path(__file__).resolve()} _worker {service} {token}"
        )
        return (
            (pid, token)
            if result.returncode == 0 and result.stdout.strip() == expected
            else None
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def worker(service: str) -> int:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    if service == "api":
        # Test-only bridge suppression must not silently disable the live source.
        env.pop("MT5_DISABLE_LIVE_BRIDGE", None)
        # The live BridgeService acquires its own lease, including direct API launches.
        env["PYTHONPATH"] = str(DEV / "src")
        try:
            handoff, original = runtime_paths()
        except ValueError as exc:
            print(str(exc))
            return 1
        env["MT5_BRIDGE_HANDOFF"] = str(handoff)
        env["MT5_HISTORICAL_ROOT"] = str(original)
        env["MT5_REQUIRE_EXISTING_RUNTIME"] = "1"
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "mt5_market_data.terminal_api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
        cwd = DEV
    elif service == "frontend":
        env["VITE_API_PROXY_TARGET"] = "http://127.0.0.1:8000"
        command = [
            str(DEV / "frontend/node_modules/.bin/vite"),
            "--host",
            "127.0.0.1",
            "--port",
            "5173",
            "--strictPort",
        ]
        cwd = DEV / "frontend"
    else:
        raise SystemExit("Unknown service")
    child = None
    stop_requested = False

    def stop(_sig, _frame):
        nonlocal stop_requested
        stop_requested = True
        if child is not None and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        child = subprocess.Popen(command, cwd=cwd, env=env)
        if stop_requested and child.poll() is None:
            child.terminate()
        return child.wait()
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait()


def _stop_launched(launched) -> None:
    """Stop only children spawned in this start attempt, without force."""
    for _, proc in launched:
        if proc.poll() is None:
            proc.terminate()
    for name, proc in launched:
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            print(f"{name}: worker did not stop; no forced termination sent")


def start() -> int:
    if RUN.is_symlink() or (RUN.exists() and not RUN.is_dir()):
        print("Local launcher state directory is invalid; no services started.")
        return 1
    try:
        RUN.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        print(f"Cannot prepare local launcher directory: {type(exc).__name__}")
        return 1
    lock = RUN / "launch.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        launch_lease = os.fdopen(fd, "a+")
    except OSError as exc:
        print(f"Cannot access launch lease: {type(exc).__name__}")
        return 1
    try:
        try:
            fcntl.flock(launch_lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(
                "Another launcher currently holds the launch lease; no services started."
            )
            return 1
        instances = {name: owned(name) for name in SERVICES}
        if all(instances.values()):
            print("Project-owned services are already running; checking their health.")
            if status() == 0:
                print("Existing healthy services reused; no new consumer started.")
                return 0
            print(
                "Existing services are not healthy; inspect status and logs before retrying."
            )
            return 1
        if any(instances.values()):
            print(
                "Only part of the project is running; use status or stop before starting."
            )
            return 1
        for name, port in SERVICES.items():
            if port_open(port):
                print(
                    f"Refusing to start: localhost port {port} is already in use ({name})."
                )
                return 1
        try:
            handoff, original = runtime_paths()
        except ValueError as exc:
            print(str(exc))
            return 1
        try:
            ps = subprocess.run(
                ["ps", "-axo", "pid=,command="],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Cannot inspect running processes: {type(exc).__name__}")
            return 1
        for line in ps.stdout.splitlines():
            if "mt5_market_data.terminal_api:app" in line or (
                "vite" in line
                and (
                    str(DEV / "frontend") in line or str(original / "frontend") in line
                )
            ):
                print(
                    "Refusing to start: a matching API or Vite process already exists."
                )
                return 1
        state = STATE
        if (
            not (DEV / "src/mt5_market_data/terminal_api.py").is_file()
            or not handoff.is_dir()
        ):
            print(
                "Local API source or MT5 handoff is unavailable; no services started."
            )
            return 1
        if (
            not state.is_dir()
            or state.is_symlink()
            or not state.resolve().is_relative_to(DEV.resolve())
            or not os.access(state, os.R_OK | os.W_OK)
        ):
            print(
                "Local bridge state is missing, symlinked, or inaccessible; no services started."
            )
            return 1
        if (
            not (state / "revision-ledger.json").is_file()
            or not (state / "checkpoint.json").is_file()
        ):
            print(
                "Local checkpoint or revision ledger is missing; no services started."
            )
            return 1
        if not (state / "revision-ledger.required").is_file():
            print("Local revision ledger marker is missing; no services started.")
            return 1
        try:
            sys.path.insert(0, str(DEV / "src"))
            from mt5_market_data.mt5_bridge import BridgeService
            from mt5_market_data.revision_review import load_reviews

            # Validate persisted bytes without acquiring a live consumer lease.
            probe = BridgeService.__new__(BridgeService)
            probe.state_dir = state
            probe._read_state()
            revisions = probe._read_revision_ledger()
            load_reviews(state, revisions)
        except (OSError, ValueError, ImportError) as exc:
            print(f"Local checkpoint or ledger failed validation: {exc}")
            return 1
        original_state = original / "runtime/mt5_bridge/state"
        try:
            other = subprocess.run(
                ["lsof", "+D", str(original_state)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            print(f"Cannot inspect legacy state ownership: {type(exc).__name__}")
            return 1
        if other.returncode not in (0, 1) or other.stdout.strip():
            print(
                "Original state is open or cannot be checked; refusing cutover consumer startup."
            )
            return 1
        if not (DEV / "frontend/node_modules/.bin/vite").is_file():
            print(
                "Locked frontend dependencies are missing; install them before starting."
            )
            return 1
        launched = []
        try:
            for name in SERVICES:
                token = secrets.token_hex(16)
                with (RUN / f"{name}.log").open("ab") as log:
                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "_worker",
                            name,
                            token,
                        ],
                        cwd=DEV,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                launched.append((name, proc))
                record = {"pid": proc.pid, "token": token}
                (RUN / f"{name}.json").write_text(json.dumps(record) + "\n")
                print(
                    f"Started {name} supervisor PID {proc.pid}; log: {RUN / (name + '.log')}"
                )
        except (OSError, ValueError) as exc:
            _stop_launched(launched)
            print(f"Startup failed: {exc}")
            return 1
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not all(
            port_open(p) for p in SERVICES.values()
        ):
            if any(proc.poll() is not None for _, proc in launched):
                break
            time.sleep(0.2)
        ready = all(port_open(p) for p in SERVICES.values()) and all(
            proc.poll() is None for _, proc in launched
        )
        for name, proc in launched:
            print(
                f"{name}: {'listening' if port_open(SERVICES[name]) and proc.poll() is None else 'not listening or exited; inspect log'} (supervisor PID {proc.pid})"
            )
        if not ready:
            print("Startup incomplete; requesting shutdown of project-owned workers.")
            _stop_launched(launched)
        return 0 if ready else 1
    finally:
        # The stable file is never unlinked: a crash releases the kernel lease.
        launch_lease.close()


def status() -> int:
    print(f"API source: {DEV / 'src'}")
    print(f"Authoritative runtime: {STATE}")
    try:
        handoff, original = runtime_paths()
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"MT5 handoff: {handoff}")
    print(f"Historical data (read-only): {original / 'data'}")
    print(f"Pre-cutover backup root: {DEV / 'runtime-backups'}")
    instances = {name: owned(name) for name in SERVICES}
    ok = True
    for name, port in SERVICES.items():
        instance = instances[name]
        listening = port_open(port)
        print(
            f"{name}: {'owned supervisor PID ' + str(instance[0]) if instance else 'no verified project-owned supervisor'}; localhost:{port} {'listening' if listening else 'not listening'}; log: {RUN / (name + '.log')}"
        )
        ok = ok and bool(instance) and listening
    checks = (
        ("frontend", "frontend HTTP", "http://127.0.0.1:5173/"),
        ("api", "runtime identity", "http://127.0.0.1:8000/api/runtime-identity"),
        (
            "api",
            "broker evidence",
            "http://127.0.0.1:8000/api/broker-specification?symbol=EURUSDm",
        ),
        (
            "api",
            "bridge status",
            "http://127.0.0.1:8000/api/mt5/status?symbol=EURUSDm&timeframe=H1",
        ),
    )
    for owner, label, url in checks:
        if not instances[owner]:
            print(f"{label}: skipped; service ownership not established")
            continue
        try:
            with urlopen(url, timeout=3) as response:
                if owner == "api":
                    body = json.load(response)
                    observation = {
                        key: body.get(key)
                        for key in (
                            "status",
                            "specification_status",
                            "verification_status",
                            "project_root",
                            "runtime_state",
                            "handoff",
                        )
                        if key in body
                    }
                    if label == "runtime identity" and (
                        body.get("project_root") != str(DEV)
                        or body.get("runtime_state") != str(STATE)
                        or body.get("handoff") != str(handoff)
                    ):
                        ok = False
                        print("Runtime identity does not match the configured cutover")
                    print(f"{label}: HTTP {response.status} {observation}")
                else:
                    print(f"{label}: HTTP {response.status}; rendering not established")
        except (OSError, URLError, ValueError) as exc:
            ok = False
            print(f"{label}: unavailable ({type(exc).__name__})")
    return 0 if ok else 1


def stop() -> int:
    failed = False
    for name, port in SERVICES.items():
        instance = owned(name)
        if not instance:
            if port_open(port):
                print(f"{name}: unowned listener remains; no signal sent")
                failed = True
            else:
                print(f"{name}: no verified project-owned process; no signal sent")
            continue
        pid, _ = instance
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            print(f"{name}: already stopped")
            continue
        except OSError as exc:
            print(f"{name}: unable to signal owned supervisor ({type(exc).__name__})")
            failed = True
            continue
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and owned(name):
            time.sleep(0.1)
        if owned(name):
            print(f"{name}: supervisor {pid} did not stop; no forced termination sent")
            failed = True
        elif port_open(port):
            print(
                f"{name}: supervisor exited but a listener remains; no extra signal sent"
            )
            failed = True
        else:
            print(f"{name}: stopped project-owned supervisor {pid}")
    return int(failed)


if __name__ == "__main__":
    if (
        len(sys.argv) == 4
        and sys.argv[1] == "_worker"
        and re.fullmatch(r"[0-9a-f]{32}", sys.argv[3])
    ):
        raise SystemExit(worker(sys.argv[2]))
    if len(sys.argv) != 2 or sys.argv[1] not in ("start", "status", "stop"):
        raise SystemExit("Usage: .venv/bin/python tools/devctl.py {start|status|stop}")
    raise SystemExit({"start": start, "status": status, "stop": stop}[sys.argv[1]]())
