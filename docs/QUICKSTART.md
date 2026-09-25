# Quickstart — ZION / Apple Silicon

## 1. Keep source, live data and qualification evidence separate

Extract the release into a source directory. Never place the live database, WAL/SHM, credentials, evidence vault or prepared requests inside Google Drive or the source repository. The dropzone holds artifacts, not running storage. Do not replace the lab's existing `./lab`; use `integration/lab_router_snippet.sh` to integrate the supplied subcommand.

The delivered results are Linux compatibility evidence. The package is not a claim that this guide already ran on ZION.

## 2. Check the interpreter, then install

From the extracted package, using the SAME interpreter for installation and execution:

```sh
python3 -c 'import platform,sqlite3; print(platform.platform(), sqlite3.sqlite_version); assert sqlite3.sqlite_version_info >= (3,51,3)'
python3 -m pip install -r requirements-test.txt
```

A standalone upgraded `sqlite3` shell does not change Python's linked SQLite. Do not remove the runtime check to make the application start. Use a maintained Python installation linked to the supported library and verify the printed version. The release vendors no SQLite binary. Node is needed only for the Apps Script test harness.

## 3. Run the full target matrix before production use

```sh
OUT="$HOME/Library/Application Support/SovereignCRM/CRM-Qualification/$(date +%Y%m%d-%H%M%S)"
PYTHON=python3 ./qualification/qualify_target.sh "$OUT"
```

This creates fresh synthetic ledgers under the operating system's temporary directory, runs 100 workers and 50,000 primary operations plus exact replays, simulates quota/partition recovery, exercises claims/crash recovery, and records fixed-fixture search timings. No Google credentials, existing CRM database or live workbook is touched. Do not pass `--compatibility-only` for production qualification. Exit success means the runner completed; inspect latency and live-deployment gates instead of equating completion with universal certification.

## 4. Provision a fresh local ledger

```sh
DATA="$HOME/Library/Application Support/SovereignCRM/CRM/primary"
python3 tools/crm-admin.py init --root "$DATA" --actor-name "Leon"
export CRM_CLIENT_CONFIG="$DATA/client.json"
python3 tools/crm-host.py --config "$DATA/broker.json"
```

The explicit reference host occupies that terminal. In a second terminal, from the package directory:

```sh
DATA="$HOME/Library/Application Support/SovereignCRM/CRM/primary"
export CRM_CLIENT_CONFIG="$DATA/client.json"
./lab crm health
python3 tools/crm-make-command.py --command entity.create   --payload examples/new-person.payload.json --independent   --output "$DATA/create-person.json"
./lab crm ingest "$DATA/create-person.json"
./lab crm search "Synthetic"
./lab crm sync --dry-run
```

Initialization and packet preparation refuse overwrite. For retry, resend the SAME prepared packet; do not generate a new operation ID or base. Give workers their own narrow capabilities, not the operator's generated key. Mode 0600 is not isolation against hostile same-UID processes.

## 5. Connect Google only after local qualification

Follow `docs/DEPLOYMENT.md` for real principal/project IDs, an authorized empty workbook, pinned numeric sheet IDs and one shared quota root for principals sharing limits. Initial provisioning is explicit. The service-account key remains in the broker's protected configuration. Authenticate and test unattended access/renewal without a browser-repair fallback.

The existing lab lifecycle calls one bounded sync pass at a time. Do not make each agent poll Google or run its own retry loop. `sync --push` may perform safety reads; `--pull` captures proposals without adoption; `--dry-run` is offline and read-only. Keep ambiguous writes in UNKNOWN rather than generating a new identity.

Apps Script remains optional, ingress-only and separately provisioned. Its trigger writes metadata hints; it does not import arbitrary cell values or publish canonical state. Turn 6's Lamport extension is local-broker-only, as specified in `docs/LAMPORT_EXTENSION.md`.

Before calling the installation production-qualified, retain target matrix evidence, measured search gates, actual Google permission/token/typed-readback tests and the declared restore/fencing procedure. A filename containing v1.0.0 does not supply that evidence.

The full target runner retains its synthetic fixture databases in the generated OS temporary directory, recorded as `raw_fixture_root`. They are not production data and are not included in this release archive. Remove them only after retaining the audit evidence needed for review.
