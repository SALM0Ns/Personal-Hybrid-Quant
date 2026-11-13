# Runtime ownership and recovery

The existing Developer installation owns the live application and checkpoint. A retired copy is only a historical reference; do not run another consumer or restore its older checkpoint over newer state. The producer uses the handoff configured for the active terminal. Paths and runtime receipts are local configuration and must not be published. A source checkout alone does not create a trusted runtime, broker connection or verified historical dataset.

## Start, inspect and stop

From the project directory, after the existing runtime and local environment are configured:

```bash
.venv/bin/python tools/devctl.py start
.venv/bin/python tools/devctl.py status
.venv/bin/python tools/devctl.py stop
```

The supported launcher binds API and frontend to localhost. Healthy existing owned services may be reused; conflicting processes, missing or inconsistent runtime configuration and unsafe state fail closed. Status shows the configured paths locally. The consumer holds an advisory kernel lease; direct cooperating API starts are subject to it. This is not a security boundary against changed or uncooperative software.

The existing ignored `runtime/cutover-receipt.json` supplies the registered handoff, authoritative state and historical-reference paths. Optional `MT5_BRIDGE_HANDOFF` and `MT5_HISTORICAL_ROOT` overrides must match the receipt. A missing, malformed or conflicting receipt fails closed; these values are local operational configuration and are not broker authentication. Never publish a receipt or invent one to bypass the safety checks.

## Recovery

Do not delete persistent lock files, pending markers, checkpoint, ledger or source handoff files to force startup. Stop only the verified project-owned services, leave the terminal and producer unchanged, and inspect diagnostics. Before any recovery or migration preserve a new, separately named, hash-verified copy of the latest stopped checkpoint, revision ledger and all referenced handoff evidence. An old backup cannot safely replace a newer checkpoint. Reconciliation and any authorization to replace protected state require separate review.

## Environment

The project includes pinned Python dependency information and a macOS arm64 / Python 3.12 hash lock. Wheel bytes must be obtained from a trusted source and checked against the lock; hashes prove byte identity, not publisher identity. This lock is platform-specific and does not pin the base interpreter. For the frontend, `npm ci` uses the committed package lock. See the [user guide](USER_GUIDE_V1.md) and [analytics contract](ANALYTICS_CONTRACT_V05.md).
